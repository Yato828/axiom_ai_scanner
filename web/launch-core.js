export function validateToken(values, hasImage) {
  const bytes = value => new TextEncoder().encode(value).length;
  const name = String(values.name || '').trim().normalize('NFC');
  const symbol = String(values.symbol || '').trim().toUpperCase();
  if (!name || bytes(name) > 32) throw new Error('Token name must use 1–32 UTF-8 bytes.');
  if (!/^[A-Z0-9]{1,13}$/.test(symbol)) throw new Error('Ticker must use 1–13 letters or numbers.');
  const description = String(values.description || '').trim();
  if (bytes(description) > 1000) throw new Error('Description must fit within 1000 UTF-8 bytes.');
  if (!hasImage) throw new Error('Choose your token artwork first.');
  const result = { name, symbol, description };
  for (const key of ['website', 'twitter', 'telegram']) {
    const value = String(values[key] || '').trim();
    if (!value) continue;
    let url;
    try { url = new URL(value); } catch { throw new Error(`${key}: enter a valid HTTPS link.`); }
    if (url.protocol !== 'https:' || url.username || url.password || value.length > 256 || (url.port && url.port !== '443')) {
      throw new Error(`${key}: enter a valid HTTPS link.`);
    }
    if (key === 'twitter' && !['x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'].includes(url.hostname)) throw new Error('X link must use x.com or twitter.com.');
    if (key === 'telegram' && !['t.me', 'www.t.me'].includes(url.hostname)) throw new Error('Telegram link must use t.me.');
    result[key] = value;
  }
  return result;
}

export function encodeBase58(bytes) {
  const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  let number = 0n;
  for (const byte of bytes) number = number * 256n + BigInt(byte);
  let result = '';
  while (number > 0n) { result = alphabet[Number(number % 58n)] + result; number /= 58n; }
  for (const byte of bytes) { if (byte !== 0) break; result = '1' + result; }
  return result;
}

export function readPending(storage, wallet) {
  try {
    const value = JSON.parse(storage.getItem(`degenmixer:pending:${wallet}`));
    if (value && /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(value.mint) && /^[1-9A-HJ-NP-Za-km-z]{64,90}$/.test(value.signature)) return value;
  } catch { /* Device storage can be unavailable or contain an old draft. */ }
  return null;
}
