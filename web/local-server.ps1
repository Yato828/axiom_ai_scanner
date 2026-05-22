$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $root
$server = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse('127.0.0.1'), 5173)
$server.Start()

$contentTypes = @{
  '.html' = 'text/html; charset=utf-8'
  '.css' = 'text/css; charset=utf-8'
  '.js' = 'application/javascript; charset=utf-8'
  '.json' = 'application/json; charset=utf-8'
  '.png' = 'image/png'
  '.jpg' = 'image/jpeg'
  '.jpeg' = 'image/jpeg'
  '.webp' = 'image/webp'
  '.svg' = 'image/svg+xml'
}

$script:LiveTokenCache = $null
$script:OgMemecoinCache = $null

function New-Token {
  param(
    [int]$Rank,
    [string]$Symbol,
    [string]$Name,
    [string]$Signal,
    [double]$Score,
    [double]$MarketCap,
    [double]$Liquidity,
    [double]$Volume,
    [double]$Change,
    [int]$Txns,
    [double]$Age,
    [string]$Why
  )

  @{
    rank = $Rank
    token = $Symbol
    name = $Name
    chain = 'solana'
    address = ('So111111111111111111111111111111111111{0:d4}' -f $Rank)
    image_url = "/assets/tokens/$Symbol.svg"
    score = $Score
    signal = $Signal
    price_usd = 0
    market_cap = $MarketCap
    fdv = $MarketCap
    liquidity_usd = $Liquidity
    volume_1h = $Volume
    volume_24h = $Volume * 7.4
    txns_1h = $Txns
    buys_1h = [Math]::Round($Txns * 0.58)
    sells_1h = [Math]::Round($Txns * 0.42)
    price_change_5m = [Math]::Round($Change / 4, 2)
    price_change_1h = $Change
    price_change_6h = [Math]::Round($Change * 1.9, 2)
    price_change_24h = [Math]::Round($Change * 3.1, 2)
    age_minutes = $Age
    risk_flags = @('local fallback data', 'verify contract before trading')
    why = $Why
    url = "https://dexscreener.com/solana/$Symbol"
  }
}

function Get-FallbackTokens {
  $path = Join-Path $projectRoot 'data\solana_memecoins.json'
  if (Test-Path $path) {
    try {
      $rows = @()
      $items = @((Get-Content -Raw -Path $path | ConvertFrom-Json).tokens)
      for ($index = 0; $index -lt $items.Count; $index++) {
        $item = $items[$index]
        $rows += New-Token `
          ($index + 1) `
          ([string]$item.symbol) `
          ([string]$item.name) `
          ([string]$item.signal) `
          ([double]$item.score) `
          ([double]$item.market_cap) `
          ([double]$item.liquidity) `
          ([double]$item.volume) `
          ([double]$item.change) `
          ([int]$item.txns) `
          ([double]$item.age) `
          ("$($item.theme) momentum on Solana meme watchlist. Local DegenMixer fallback entry with image asset.")
      }
      return @(Select-UniqueTokens $rows)
    } catch {}
  }

  return @(
    New-Token 1 'SAHUR' 'Tung Tung Tung Sahur' 'HOT' 96.4 15400000 920000 1820000 38.4 5280 74 'Brainrot chant meme with fast remix potential and strong short-form recognition.'
  )
}

function Get-LiveTokens {
  if ($null -ne $script:LiveTokenCache) {
    return $script:LiveTokenCache
  }

  $path = Join-Path $projectRoot 'data\solana_live_tokens.json'
  if (Test-Path $path) {
    try {
      $tokens = @((Get-Content -Raw -Path $path | ConvertFrom-Json).tokens)
      if ($tokens.Count -gt 0) {
        $script:LiveTokenCache = @(Select-UniqueTokens $tokens)
        return $script:LiveTokenCache
      }
    } catch {}
  }
  $script:LiveTokenCache = @(Select-UniqueTokens (Get-FallbackTokens))
  return $script:LiveTokenCache
}

function Get-TokenKeys {
  param([object]$Token)
  $address = ([string]$Token.address).Trim().ToLowerInvariant()
  $symbol = ([string]$Token.token).Trim().ToLowerInvariant().TrimStart('$')
  if (-not $symbol) { $symbol = ([string]$Token.symbol).Trim().ToLowerInvariant().TrimStart('$') }
  $name = ([string]$Token.name).Trim().ToLowerInvariant()
  $keys = @("label:$symbol`:$name")
  if ($address) { $keys += "address:$address" }
  return $keys
}

function Select-UniqueTokens {
  param([object[]]$Tokens)
  $seen = @{}
  $rows = @()
  foreach ($token in @($Tokens)) {
    $keys = @(Get-TokenKeys $token)
    $exists = $false
    foreach ($key in $keys) {
      if ($seen.ContainsKey($key)) { $exists = $true; break }
    }
    if ($exists) { continue }
    foreach ($key in $keys) { $seen[$key] = $true }
    $rows += $token
  }
  return $rows
}

function Find-TokenImage {
  param([string]$Name, [string]$Symbol)
  $needleSymbol = $Symbol.Trim().ToLowerInvariant().TrimStart('$')
  $needleName = $Name.Trim().ToLowerInvariant()
  foreach ($token in @(Get-LiveTokens)) {
    $tokenSymbol = ([string]$token.token).Trim().ToLowerInvariant().TrimStart('$')
    $tokenName = ([string]$token.name).Trim().ToLowerInvariant()
    if (
      $token.image_url -and (
        ($needleSymbol -and $tokenSymbol -eq $needleSymbol) -or
        ($needleName -and $tokenName -eq $needleName)
      )
    ) {
      return [string]$token.image_url
    }
  }
  return ''
}

function Get-OgMemecoins {
  if ($null -ne $script:OgMemecoinCache) {
    return $script:OgMemecoinCache
  }

  $path = Join-Path $projectRoot 'data\og_memecoins.json'
  if (Test-Path $path) {
    try {
      $rows = @()
      foreach ($token in @((Get-Content -Raw -Path $path | ConvertFrom-Json).tokens)) {
        $rows += [ordered]@{
          name = [string]$token.name
          symbol = [string]$token.symbol
          archetype = [string]$token.archetype
          image_url = Find-TokenImage ([string]$token.name) ([string]$token.symbol)
        }
      }
      $script:OgMemecoinCache = $rows
      return $script:OgMemecoinCache
    } catch {}
  }
  $script:OgMemecoinCache = @()
  return $script:OgMemecoinCache
}

function New-Narratives {
  param([object[]]$Tokens, [object[]]$OgTokens, [int]$Limit = 12)
  $rows = @()
  if (-not $Tokens -or $Tokens.Count -eq 0) {
    $Tokens = Get-FallbackTokens
  }
  if (-not $OgTokens -or $OgTokens.Count -eq 0) {
    $OgTokens = Get-OgMemecoins
  }

  for ($index = 0; $index -lt $Limit; $index++) {
    $token = $Tokens[$index % $Tokens.Count]
    $og = $OgTokens[$index % $OgTokens.Count]
    $ticker = (($token.token + $og.symbol) -replace '[^A-Za-z0-9]', '').ToUpper()
    if ($ticker.Length -gt 10) { $ticker = $ticker.Substring(0, 10) }
    $rows += @{
      name = "$($token.name) x $($og.name)"
      ticker = $ticker
      hook = "Solana remix: $($token.token) energy fused with $($og.symbol) culture."
      narrative = "A fast meme blend built for short clips, sticker drops and degen community raids."
      visual_brief = "Use $($token.name) as the trend base and blend it with $($og.archetype)."
      image_prompt = "Create a bright Solana meme poster for $($token.name) mixed with $($og.name), ticker $ticker."
      trend_token = $token.token
      og_token = $og.symbol
      og_name = $og.name
      og_image_url = if ($og.image_url) { [string]$og.image_url } else { Find-TokenImage ([string]$og.name) ([string]$og.symbol) }
      trend_image_url = if ($token.image_url) { [string]$token.image_url } else { Find-TokenImage ([string]$token.name) ([string]$token.token) }
      change_1h = $token.price_change_1h
    }
  }
  return $rows
}

function Send-Json {
  param([System.Net.Sockets.NetworkStream]$Stream, [object]$Payload, [int]$Status = 200)
  $statusText = if ($Status -eq 200) { 'OK' } elseif ($Status -eq 404) { 'Not Found' } else { 'Error' }
  $body = [System.Text.Encoding]::UTF8.GetBytes(($Payload | ConvertTo-Json -Depth 12 -Compress))
  $header = "HTTP/1.1 $Status $statusText`r`nContent-Type: application/json; charset=utf-8`r`nCache-Control: no-store`r`nContent-Length: $($body.Length)`r`nConnection: close`r`n`r`n"
  $headerBytes = [System.Text.Encoding]::ASCII.GetBytes($header)
  $Stream.Write($headerBytes, 0, $headerBytes.Length)
  $Stream.Write($body, 0, $body.Length)
}

function Send-Bytes {
  param([System.Net.Sockets.NetworkStream]$Stream, [byte[]]$Body, [string]$ContentType, [int]$Status = 200)
  $statusText = if ($Status -eq 200) { 'OK' } elseif ($Status -eq 404) { 'Not Found' } elseif ($Status -eq 403) { 'Forbidden' } else { 'Error' }
  $header = "HTTP/1.1 $Status $statusText`r`nContent-Type: $ContentType`r`nCache-Control: no-store`r`nContent-Length: $($Body.Length)`r`nConnection: close`r`n`r`n"
  $headerBytes = [System.Text.Encoding]::ASCII.GetBytes($header)
  $Stream.Write($headerBytes, 0, $headerBytes.Length)
  if ($Body.Length -gt 0) {
    $Stream.Write($Body, 0, $Body.Length)
  }
}

function Read-RequestBody {
  param([System.IO.StreamReader]$Reader, [hashtable]$Headers)
  $length = 0
  if ($Headers.ContainsKey('content-length')) {
    [void][int]::TryParse($Headers['content-length'], [ref]$length)
  }
  if ($length -le 0) { return '' }
  $buffer = New-Object char[] $length
  $read = $Reader.ReadBlock($buffer, 0, $length)
  if ($read -le 0) { return '' }
  return -join $buffer[0..($read - 1)]
}

while ($true) {
  $client = $server.AcceptTcpClient()
  try {
    $client.ReceiveTimeout = 2000
    $client.SendTimeout = 5000
    $stream = $client.GetStream()
    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $false, 4096, $true)
    $requestLine = $reader.ReadLine()
    if (-not $requestLine) { continue }

    $headers = @{}
    while ($true) {
      $line = $reader.ReadLine()
      if ([string]::IsNullOrEmpty($line)) { break }
      $parts = $line.Split(':', 2)
      if ($parts.Count -eq 2) {
        $headers[$parts[0].Trim().ToLowerInvariant()] = $parts[1].Trim()
      }
    }

    $method = 'GET'
    $target = '/'
    if ($requestLine -match '^([A-Z]+)\s+([^\s]+)') {
      $method = $matches[1]
      $target = $matches[2]
    }
    $uri = [Uri]::new("http://127.0.0.1$target")
    $path = $uri.AbsolutePath

    if ($method -eq 'GET' -and $path -eq '/api/scan') {
      $limit = 0
      if ($uri.Query -match 'limit=(\d+)') { $limit = [int]$matches[1] }
      $allTokens = @(Select-UniqueTokens (Get-LiveTokens))
      $tokens = if ($limit -gt 0) { @($allTokens | Select-Object -First $limit) } else { $allTokens }
      $og = @(Get-OgMemecoins)
      Send-Json $stream @{
        updated_at = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        count = $tokens.Count
        min_market_cap_usd = 0
        tokens = $tokens
        og_memecoins = $og
        narratives = New-Narratives $tokens $og 12
      }
      continue
    }

    if ($method -eq 'GET' -and $path -eq '/api/og') {
      Send-Json $stream @{ og_memecoins = @(Get-OgMemecoins) }
      continue
    }

    if ($method -eq 'GET' -and $path -eq '/api/og-image') {
      $name = ''
      $symbol = ''
      foreach ($part in $uri.Query.TrimStart('?').Split('&')) {
        $pieces = $part.Split('=', 2)
        if ($pieces.Count -ne 2) { continue }
        $key = [Uri]::UnescapeDataString($pieces[0])
        $value = [Uri]::UnescapeDataString($pieces[1].Replace('+', ' '))
        if ($key -eq 'name') { $name = $value }
        if ($key -eq 'symbol') { $symbol = $value }
      }
      Send-Json $stream @{ image_url = Find-TokenImage $name $symbol }
      continue
    }

    if ($method -eq 'POST' -and $path -eq '/api/narratives') {
      $bodyText = Read-RequestBody $reader $headers
      $payload = @{}
      if ($bodyText) {
        try { $payload = $bodyText | ConvertFrom-Json } catch {}
      }
      $tokens = @($payload.tokens)
      $og = @($payload.og_memecoins)
      $limit = if ($payload.limit) { [int]$payload.limit } else { 12 }
      Send-Json $stream @{ narratives = New-Narratives $tokens $og $limit }
      continue
    }

    if ($method -eq 'POST' -and $path -eq '/api/generate-image') {
      $bodyText = Read-RequestBody $reader $headers
      $payload = @{}
      if ($bodyText) {
        try { $payload = $bodyText | ConvertFrom-Json } catch {}
      }
      $name = if ($payload.narrative.name) { $payload.narrative.name } else { 'Solana meme remix' }
      $ticker = if ($payload.narrative.ticker) { $payload.narrative.ticker } else { 'MEME' }
      $svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1024 1024'><rect width='1024' height='1024' fill='#090615'/><circle cx='820' cy='180' r='190' fill='#a855f7' opacity='.78'/><circle cx='180' cy='820' r='240' fill='#f15bb5' opacity='.65'/><rect x='112' y='256' width='800' height='512' rx='42' fill='#171027' stroke='#34224e' stroke-width='6'/><text x='512' y='430' text-anchor='middle' font-family='Arial' font-size='58' font-weight='900' fill='#fbf7ff'>$ticker</text><text x='512' y='535' text-anchor='middle' font-family='Arial' font-size='34' font-weight='800' fill='#67e8f9'>DEGENMIXER REMIX</text><text x='512' y='625' text-anchor='middle' font-family='Arial' font-size='30' font-weight='700' fill='#e8ddf4'>$name</text></svg>"
      Send-Json $stream @{ image_data_url = "data:image/svg+xml;charset=utf-8,$([Uri]::EscapeDataString($svg))" }
      continue
    }

    if ($method -eq 'POST' -and $path -eq '/api/hybrid-image') {
      Send-Json $stream @{
        error = 'DegenMixer Studio uses the Python backend. Start it with: python main.py web --port 8080'
        code = 'python_backend_required'
      } 501
      continue
    }

    $filePath = if ($path -eq '/') { 'index.html' } else { [Uri]::UnescapeDataString($path.TrimStart('/')) }
    $fullPath = [System.IO.Path]::GetFullPath((Join-Path $root $filePath))
    if (-not $fullPath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
      Send-Bytes $stream ([System.Text.Encoding]::UTF8.GetBytes('Forbidden')) 'text/plain; charset=utf-8' 403
      continue
    }
    if (-not [System.IO.File]::Exists($fullPath)) {
      Send-Bytes $stream ([System.Text.Encoding]::UTF8.GetBytes('Not found')) 'text/plain; charset=utf-8' 404
      continue
    }

    $bytes = [System.IO.File]::ReadAllBytes($fullPath)
    $extension = [System.IO.Path]::GetExtension($fullPath).ToLowerInvariant()
    $contentType = if ($contentTypes.ContainsKey($extension)) { $contentTypes[$extension] } else { 'application/octet-stream' }
    Send-Bytes $stream $bytes $contentType
  } catch [System.IO.IOException] {
    continue
  } finally {
    $client.Close()
  }
}
