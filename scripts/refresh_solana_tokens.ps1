param(
  [int]$Target = 220
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$outputPath = Join-Path $projectRoot 'data\solana_live_tokens.json'
$baseUrl = 'https://api.dexscreener.com'

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null

function Get-Json {
  param([string]$Url)
  try {
    return Invoke-RestMethod -Uri $Url -Headers @{ 'User-Agent' = 'Memorphia/1.0' } -TimeoutSec 15
  } catch {
    return $null
  }
}

function To-Double {
  param($Value)
  if ($null -eq $Value) { return 0.0 }
  try { return [double]$Value } catch { return 0.0 }
}

function To-Int {
  param($Value)
  if ($null -eq $Value) { return 0 }
  try { return [int]$Value } catch { return 0 }
}

function Get-PairImage {
  param($Pair)
  $info = $Pair.info
  if (-not $info) { return '' }
  foreach ($field in @('imageUrl', 'openGraph', 'icon')) {
    $value = [string]$info.$field
    if ($value -and $value.StartsWith('http')) {
      return $value
    }
  }
  return ''
}

function Convert-Pair {
  param($Pair, [int]$Rank)
  $base = $Pair.baseToken
  if (-not $base) { return $null }

  $symbol = ([string]$base.symbol).Trim()
  $name = ([string]$base.name).Trim()
  $address = ([string]$base.address).Trim()
  if (-not $symbol -or -not $address) { return $null }

  $imageUrl = Get-PairImage $Pair
  if (-not $imageUrl -and $profileImages.ContainsKey($address.ToLowerInvariant())) {
    $imageUrl = [string]$profileImages[$address.ToLowerInvariant()]
  }
  if (-not $imageUrl) { return $null }

  $liquidity = To-Double $Pair.liquidity.usd
  $volume1h = To-Double $Pair.volume.h1
  $volume24h = To-Double $Pair.volume.h24
  $marketCap = To-Double $Pair.marketCap
  $fdv = To-Double $Pair.fdv
  $change1h = To-Double $Pair.priceChange.h1
  $change24h = To-Double $Pair.priceChange.h24
  $txns1h = (To-Int $Pair.txns.h1.buys) + (To-Int $Pair.txns.h1.sells)
  $score = [Math]::Round(
    [Math]::Min($liquidity / 100000, 30) +
    [Math]::Min($volume1h / 50000, 30) +
    [Math]::Min([Math]::Abs($change1h), 25) +
    [Math]::Min($txns1h / 80, 15),
    2
  )
  $signal = if ($score -ge 70) { 'HOT' } elseif ($score -ge 45) { 'WATCH' } elseif ($score -ge 22) { 'POTENTIAL' } else { 'SPECULATIVE' }
  $createdAt = To-Double $Pair.pairCreatedAt
  $ageMinutes = $null
  if ($createdAt -gt 0) {
    $ageMinutes = [Math]::Round(([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - $createdAt) / 60000, 2)
  }

  [ordered]@{
    rank = $Rank
    token = $symbol.Substring(0, [Math]::Min($symbol.Length, 24))
    name = $name.Substring(0, [Math]::Min($name.Length, 80))
    chain = 'solana'
    address = $address
    image_url = $imageUrl
    score = $score
    signal = $signal
    price_usd = To-Double $Pair.priceUsd
    market_cap = if ($marketCap -gt 0) { $marketCap } else { $fdv }
    fdv = $fdv
    liquidity_usd = $liquidity
    volume_1h = $volume1h
    volume_24h = $volume24h
    txns_1h = $txns1h
    buys_1h = To-Int $Pair.txns.h1.buys
    sells_1h = To-Int $Pair.txns.h1.sells
    price_change_5m = To-Double $Pair.priceChange.m5
    price_change_1h = $change1h
    price_change_6h = To-Double $Pair.priceChange.h6
    price_change_24h = $change24h
    age_minutes = $ageMinutes
    risk_flags = @('live DexScreener image', 'verify contract before trading')
    why = "Live Solana pair with original token image from DexScreener. Theme fit: meme/search trend liquidity and volume."
    url = [string]$Pair.url
  }
}

function Convert-Profile {
  param($Profile, [int]$Rank)
  $address = ([string]$Profile.tokenAddress).Trim()
  if (-not $address) { return $null }

  $imageUrl = ''
  foreach ($field in @('icon', 'openGraph', 'header')) {
    $value = [string]$Profile.$field
    if ($value -and $value.StartsWith('http')) {
      $imageUrl = $value
      break
    }
  }
  if (-not $imageUrl) { return $null }

  $description = ([string]$Profile.description).Trim()
  $words = @($description -split '\s+' | Where-Object { $_ -match '[A-Za-z0-9]' } | Select-Object -First 3)
  $name = if ($words.Count -gt 0) { ($words -join ' ') } else { "Solana Meme $($address.Substring(0, 6))" }
  $symbolSeed = (($name -replace '[^A-Za-z0-9]', '').ToUpper())
  $symbol = if ($symbolSeed.Length -ge 3) { $symbolSeed.Substring(0, [Math]::Min($symbolSeed.Length, 10)) } else { $address.Substring(0, 6).ToUpperInvariant() }

  [ordered]@{
    rank = $Rank
    token = $symbol
    name = $name.Substring(0, [Math]::Min($name.Length, 80))
    chain = 'solana'
    address = $address
    image_url = $imageUrl
    score = 18.0
    signal = 'SPECULATIVE'
    price_usd = 0
    market_cap = 0
    fdv = 0
    liquidity_usd = 0
    volume_1h = 0
    volume_24h = 0
    txns_1h = 0
    buys_1h = 0
    sells_1h = 0
    price_change_5m = 0
    price_change_1h = 0
    price_change_6h = 0
    price_change_24h = 0
    age_minutes = $null
    risk_flags = @('live DexScreener profile image', 'metrics unavailable in profile-only row')
    why = 'Latest Solana token profile from DexScreener with original profile artwork. Verify contract and liquidity before trading.'
    url = [string]$Profile.url
  }
}

function Convert-RegistryToken {
  param($RegistryToken, [int]$Rank)
  $address = ([string]$RegistryToken.address).Trim()
  $symbol = ([string]$RegistryToken.symbol).Trim()
  $name = ([string]$RegistryToken.name).Trim()
  $imageUrl = ([string]$RegistryToken.logoURI).Trim()
  if (-not $address -or -not $symbol -or -not $imageUrl.StartsWith('http')) { return $null }

  [ordered]@{
    rank = $Rank
    token = $symbol.Substring(0, [Math]::Min($symbol.Length, 24))
    name = $name.Substring(0, [Math]::Min($name.Length, 80))
    chain = 'solana'
    address = $address
    image_url = $imageUrl
    score = 16.0
    signal = 'SPECULATIVE'
    price_usd = 0
    market_cap = 0
    fdv = 0
    liquidity_usd = 0
    volume_1h = 0
    volume_24h = 0
    txns_1h = 0
    buys_1h = 0
    sells_1h = 0
    price_change_5m = 0
    price_change_1h = 0
    price_change_6h = 0
    price_change_24h = 0
    age_minutes = $null
    risk_flags = @('original token-list logo', 'registry supplement row')
    why = 'Supplemental Solana token-list entry with original logoURI, included to expand browsing choice beyond live trending pairs.'
    url = "https://dexscreener.com/solana/$address"
  }
}

$searchTerms = @(
  'meme','pump','solana meme','new meme','trending','moon','degen','dog','cat','frog','pepe',
  'bonk','wif','bome','popcat','michi','fwog','pengu','fartcoin','pnut','goat','ai16z',
  'sahur','tung','tralala','boneca','bombardiro','patapim','lirili','cappuccino','bananini',
  'chill','moodeng','myro','slerf','ponke','giga','aura','lock in','house','harambe',
  'trump','melania','banana','bull','wen','useless','mumu','mother','samo','meow',
  'mascot','cto','community','viral','brainrot','animal','sol','based','coin',
  'rat','hamster','monkey','ape','fish','shark','bird','duck','goose','cow','goat','horse',
  'bear','wolf','tiger','lion','dragon','wizard','baby','mini','turbo','rocket','banana',
  'pizza','burger','coffee','chad','sigma','wojak','mog','spx','npc','terminal','agent',
  'ai','grok','truth','elon','tesla','apple','meta','game','arcade','pixel','based',
  'america','china','russia','europe','liberty','reserve','gold','silver','oil','war',
  'cult','cto','dev','moonshot','fair','launch','pumpfun','pump fun','raydium','jupiter'
)

$searchTerms = @(
  $searchTerms +
  ([char[]](97..122) | ForEach-Object { [string]$_ }) +
  @('aa','ai','an','ba','be','bo','ca','ch','co','da','de','do','fa','fi','fo','go','ha','ho','ki','ko','la','li','ma','mi','mo','mu','pa','pe','pi','po','pu','sa','se','sh','si','so','ta','te','to','tu','wa','we','wo','za','ze')
) | Select-Object -Unique

$pairs = New-Object System.Collections.Generic.List[object]
$seenPairAddresses = @{}
$profileImages = @{}
$profileEntries = New-Object System.Collections.Generic.List[object]

foreach ($profileUrl in @(
  "$baseUrl/token-profiles/latest/v1",
  "$baseUrl/token-boosts/latest/v1",
  "$baseUrl/token-boosts/top/v1"
)) {
  $profiles = @(Get-Json $profileUrl)
  foreach ($profile in $profiles) {
    if ($profile.chainId -ne 'solana' -or -not $profile.tokenAddress) { continue }
    foreach ($field in @('icon', 'openGraph', 'header')) {
      $value = [string]$profile.$field
      if ($value -and $value.StartsWith('http')) {
        $profileImages[([string]$profile.tokenAddress).ToLowerInvariant()] = $value
        $profileEntries.Add($profile)
        break
      }
    }
  }
  $addresses = @(
    $profiles |
      Where-Object { $_.chainId -eq 'solana' -and $_.PSObject.Properties.Name -contains 'tokenAddress' -and $_.tokenAddress } |
      ForEach-Object { [string]$_.tokenAddress } |
      Select-Object -Unique
  )
  for ($i = 0; $i -lt $addresses.Count; $i += 30) {
    $chunk = @($addresses[$i..([Math]::Min($i + 29, $addresses.Count - 1))])
    if ($chunk.Count -eq 0) { continue }
    $tokenPairs = @(Get-Json "$baseUrl/tokens/v1/solana/$($chunk -join ',')")
    foreach ($pair in $tokenPairs) {
      $pairAddress = ([string]$pair.pairAddress).ToLowerInvariant()
      if ($pair.chainId -eq 'solana' -and $pairAddress -and -not $seenPairAddresses.ContainsKey($pairAddress)) {
        $seenPairAddresses[$pairAddress] = $true
        $pairs.Add($pair)
      }
    }
  }
}

foreach ($term in $searchTerms) {
  $encoded = [Uri]::EscapeDataString($term)
  $payload = Get-Json "$baseUrl/latest/dex/search?q=$encoded"
  foreach ($pair in @($payload.pairs)) {
    $pairAddress = ([string]$pair.pairAddress).ToLowerInvariant()
    if ($pair.chainId -eq 'solana' -and $pairAddress -and -not $seenPairAddresses.ContainsKey($pairAddress)) {
      $seenPairAddresses[$pairAddress] = $true
      $pairs.Add($pair)
    }
  }
  if ($pairs.Count -ge ($Target * 3)) { break }
  Start-Sleep -Milliseconds 120
}

$seenTokens = @{}
$tokens = New-Object System.Collections.Generic.List[object]
$rank = 1
$sortedPairs = $pairs | Sort-Object `
  @{ Expression = { To-Double $_.liquidity.usd }; Descending = $true },
  @{ Expression = { To-Double $_.volume.h1 }; Descending = $true }

foreach ($pair in $sortedPairs) {
  $address = ([string]$pair.baseToken.address).ToLowerInvariant()
  if (-not $address -or $seenTokens.ContainsKey($address)) { continue }
  $token = Convert-Pair $pair $rank
  if (-not $token) { continue }
  $seenTokens[$address] = $true
  $tokens.Add($token)
  $rank += 1
  if ($tokens.Count -ge $Target) { break }
}

if ($tokens.Count -lt $Target) {
  foreach ($profile in $profileEntries) {
    $address = ([string]$profile.tokenAddress).ToLowerInvariant()
    if (-not $address -or $seenTokens.ContainsKey($address)) { continue }
    $token = Convert-Profile $profile $rank
    if (-not $token) { continue }
    $seenTokens[$address] = $true
    $tokens.Add($token)
    $rank += 1
    if ($tokens.Count -ge $Target) { break }
  }
}

if ($tokens.Count -lt $Target) {
  $registry = Get-Json 'https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens/solana.tokenlist.json'
  foreach ($registryToken in @($registry.tokens)) {
    if ($registryToken.chainId -ne 101 -or -not $registryToken.logoURI) { continue }
    $address = ([string]$registryToken.address).ToLowerInvariant()
    if (-not $address -or $seenTokens.ContainsKey($address)) { continue }
    $token = Convert-RegistryToken $registryToken $rank
    if (-not $token) { continue }
    $seenTokens[$address] = $true
    $tokens.Add($token)
    $rank += 1
    if ($tokens.Count -ge $Target) { break }
  }
}

$ogPath = Join-Path $projectRoot 'data\og_memecoins.json'
if (Test-Path $ogPath) {
  $ogTokens = @((Get-Content -Raw -Path $ogPath | ConvertFrom-Json).tokens)
  foreach ($og in $ogTokens) {
    $queries = @([string]$og.symbol, [string]$og.name) | Where-Object { $_ } | Select-Object -Unique
    foreach ($query in $queries) {
      $payload = Get-Json "$baseUrl/latest/dex/search?q=$([Uri]::EscapeDataString($query))"
      $candidatePairs = @($payload.pairs) |
        Where-Object { $_.chainId -eq 'solana' -and (Get-PairImage $_) } |
        Sort-Object @{ Expression = { To-Double $_.liquidity.usd }; Descending = $true }

      foreach ($pair in $candidatePairs) {
        $address = ([string]$pair.baseToken.address).ToLowerInvariant()
        if (-not $address -or $seenTokens.ContainsKey($address)) { continue }
        $token = Convert-Pair $pair $rank
        if (-not $token) { continue }
        $seenTokens[$address] = $true
        $tokens.Add($token)
        $rank += 1
        break
      }

      $matchSymbol = ([string]$og.symbol).Trim().ToLowerInvariant().TrimStart('$')
      if (@($tokens | Where-Object { ([string]$_.token).Trim().ToLowerInvariant().TrimStart('$') -eq $matchSymbol }).Count -gt 0) {
        break
      }
      Start-Sleep -Milliseconds 90
    }
  }
}

$payload = [ordered]@{
  updated_at = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
  source = 'DexScreener live Solana scan'
  count = $tokens.Count
  tokens = $tokens
}

$payload | ConvertTo-Json -Depth 12 | Set-Content -Path $outputPath -Encoding UTF8
"Saved $($tokens.Count) live Solana tokens with original images to $outputPath"
