import { test, expect } from '@playwright/test';
import { Keypair, VersionedTransaction } from '@solana/web3.js';
import { encodeBase58 } from '../../web/launch-core.js';

async function setup(page, options = {}) {
  const payer = Keypair.generate();
  const wallet = payer.publicKey.toBase58();
  const context = { sent: 0, signed: 0, state: 'processed', rejected: false, networkError: false, wrongNetwork: false, ...options };
  await page.addInitScript(({ wallet, secret }) => {
    const handlers = new Map();
    const provider = {
      isPhantom: true, publicKey: { toString: () => wallet },
      connect: async () => ({ publicKey: provider.publicKey }), disconnect: async () => {},
      signMessage: async () => ({ signature: new Uint8Array(64) }),
      signTransaction: async tx => {
        window.__walletSigns = (window.__walletSigns || 0) + 1;
        if (window.__rejectTransaction) throw Object.assign(new Error('User rejected transaction'), { code: 4001 });
        tx.sign([{ publicKey: tx.message.staticAccountKeys[0], secretKey: new Uint8Array(secret) }]);
        return tx;
      },
      on: (name, fn) => handlers.set(name, fn), removeListener: name => handlers.delete(name),
    };
    window.phantom = { solana: provider };
  }, { wallet, secret: [...payer.secretKey] });
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAAZUlEQVR4nO3QsQ0AIAzAsIF/f+fQKQKJHSQO1t6e2c4BAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPgBHzYAAZ98c10AAAAASUVORK5CYII=', 'base64');
  let image = png;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const json = payload => route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) });
    if (path === '/api/config') return json({ launch: { enabled: true, network: 'mainnet-beta', message: 'Ready to launch on Solana mainnet.' }, generation_ready: true });
    if (path === '/api/scan') return json({ tokens: [], og_memecoins: [], narratives: [], count: 0, updated_at: 'Now', min_market_cap_usd: 10000 });
    if (path === '/api/auth/challenge') return json({ challenge_id: 'test', message: 'Test sign in. No transaction.' });
    if (path === '/api/auth/verify') return json({ wallet, csrf: 'test-csrf' });
    if (path === '/api/auth/logout') return json({ ok: true });
    if (path === '/api/launch/metadata') return json({ uri: 'https://ipfs.io/ipfs/bafybeiexamplemetadata', metadata: {} });
    if (path === '/api/images/import') return route.fulfill({ contentType: 'image/png', body: image });
    if (path === '/api/hybrid-image') return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ job_id: 'a'.repeat(64), state: 'queued' }) });
    if (path.startsWith('/api/jobs/')) return json({ state: 'completed', result: { output_url: 'https://images.example/mixed.png' } });
    if (path === '/api/rpc') {
      const request = route.request().postDataJSON();
      const wrap = result => json({ jsonrpc: '2.0', id: request.id, result });
      const value = result => wrap({ context: { slot: 100 }, value: result });
      if (request.method === 'getGenesisHash') return wrap(context.wrongNetwork ? 'devnet-genesis' : '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp');
      if (request.method === 'getLatestBlockhash') return value({ blockhash: Keypair.generate().publicKey.toBase58(), lastValidBlockHeight: 500 });
      if (request.method === 'getBalance') return value(1_000_000_000);
      if (request.method === 'getFeeForMessage') return value(10000);
      if (request.method === 'simulateTransaction') return value({ err: null, logs: [], accounts: [{ lamports: 980_000_000, owner: '11111111111111111111111111111111', data: ['', 'base64'], executable: false, rentEpoch: 0 }], unitsConsumed: 100000 });
      if (request.method === 'sendTransaction') {
        context.sent++;
        if (context.networkError) return route.abort('failed');
        const tx = VersionedTransaction.deserialize(Buffer.from(request.params[0], 'base64'));
        return wrap(encodeBase58(tx.signatures[0]));
      }
      if (request.method === 'getSignatureStatuses') return value([{ slot: 100, confirmations: 1, confirmationStatus: context.state, err: null }]);
      if (request.method === 'getBlockHeight') return wrap(100);
      throw new Error(`Unexpected RPC method: ${request.method}`);
    }
    return json({});
  });
  await page.goto('/#launch');
  await expect(page.locator('#launchStatus')).toContainText('Ready to launch');
  image = Buffer.from(await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 64; canvas.height = 64;
    const context = canvas.getContext('2d'); context.fillStyle = '#a855f7'; context.fillRect(0, 0, 64, 64);
    return canvas.toDataURL('image/png').split(',')[1];
  }), 'base64');
  return { context, wallet, image };
}

async function fill(page, image) {
  await page.locator('#launchImage').setInputFiles({ name: 'token.png', mimeType: 'image/png', buffer: image });
  await page.locator('#launchName').fill('Cosmic Bonk');
  await page.locator('#launchSymbol').fill('CBONK');
  await page.locator('#launchDescription').fill('A cosmic community token.');
  await expect(page.locator('#reviewImage')).toBeVisible();
}

async function connect(page) {
  await page.locator('#connectWallet').click();
  await page.locator('[data-wallet="phantom"]').click();
  await expect(page.locator('#walletDialog')).not.toBeVisible();
}

test('custom artwork, live preview and saved drafts work without a wallet', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const { image } = await setup(page);
  await fill(page, image);
  await expect(page.locator('#reviewName')).toHaveText('Cosmic Bonk');
  await expect(page.locator('#reviewSymbol')).toHaveText('$CBONK');
  await page.locator('#saveDraft').click();
  await page.locator('#launchName').fill('Changed');
  await page.locator('#restoreDraft').click();
  await expect(page.locator('#launchName')).toHaveValue('Cosmic Bonk');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  expect(errors).toEqual([]);
});

test('a mainnet launch requires review, consent and wallet approval', async ({ page }) => {
  const { context, image } = await setup(page);
  await fill(page, image); await connect(page);
  await page.locator('#reviewLaunch').click();
  await expect(page.locator('#confirmLaunch')).toBeVisible();
  await expect(page.locator('#reviewFee')).toContainText('0.020000');
  await page.locator('#confirmLaunch').click();
  await expect(page.locator('#launchFormError')).toContainText('accept the mainnet');
  expect(context.sent).toBe(0);
  await page.evaluate(() => { window.__rejectTransaction = true; });
  await page.locator('#launchConsent').check();
  await page.locator('#confirmLaunch').click();
  await expect(page.locator('#launchFormError')).toContainText('declined');
  expect(context.sent).toBe(0);
});

test('the wrong network is rejected before a wallet transaction is requested', async ({ page }) => {
  const { context, image } = await setup(page, { wrongNetwork: true });
  await fill(page, image); await connect(page);
  await page.locator('#reviewLaunch').click();
  await expect(page.locator('#launchFormError')).toContainText('not mainnet');
  expect(context.sent).toBe(0);
  expect(await page.evaluate(() => window.__walletSigns || 0)).toBe(0);
});

test('launch cost above the chosen maximum is rejected before signing', async ({ page }) => {
  const { context, image } = await setup(page);
  await fill(page, image); await connect(page);
  await page.locator('#maxLaunchCost').fill('0.005');
  await page.locator('#reviewLaunch').click();
  await expect(page.locator('#launchFormError')).toContainText('exceeds your maximum');
  expect(context.sent).toBe(0);
  expect(await page.evaluate(() => window.__walletSigns || 0)).toBe(0);
});

test('repeated clicks submit once and success waits for chain confirmation', async ({ page }) => {
  const { context, image } = await setup(page);
  await fill(page, image); await connect(page);
  await page.locator('#reviewLaunch').click();
  await expect(page.locator('#confirmLaunch')).toBeVisible();
  await page.locator('#launchConsent').check();
  await page.locator('#confirmLaunch').evaluate(button => { button.click(); button.click(); });
  await expect(page.locator('#launchStatus')).toContainText('pending');
  await expect(page.locator('#launchSuccess')).toBeHidden();
  expect(context.sent).toBe(1);
  context.state = 'confirmed';
  await expect(page.locator('#launchSuccess')).toBeVisible({ timeout: 8000 });
  await expect(page.locator('#pumpTokenLink')).toHaveAttribute('href', /https:\/\/pump.fun\/coin\//);
  expect(context.sent).toBe(1);
});

test('an RPC timeout preserves the signed launch across reload and prevents duplicates', async ({ page }) => {
  const { context, image } = await setup(page, { networkError: true });
  await fill(page, image); await connect(page);
  await page.locator('#reviewLaunch').click();
  await expect(page.locator('#confirmLaunch')).toBeVisible();
  await page.locator('#launchConsent').check();
  await page.locator('#confirmLaunch').click();
  await expect(page.locator('#launchStatus')).toContainText('uncertain');
  await expect(page.locator('#launchSuccess')).toBeHidden();
  expect(context.sent).toBe(1);
  await page.reload(); await connect(page);
  await expect(page.locator('#reviewLaunch')).toBeHidden();
  await expect(page.locator('#checkLaunchStatus')).toBeVisible();
  context.state = 'confirmed';
  await page.locator('#checkLaunchStatus').click();
  await expect(page.locator('#launchSuccess')).toBeVisible();
  expect(context.sent).toBe(1);
  await page.locator('#startNewToken').click();
  await expect(page.locator('#launchName')).toHaveValue('');
  await expect(page.locator('#reviewLaunch')).toBeVisible();
});

test('queued image generation can be carried into the launch form', async ({ page }) => {
  const { image } = await setup(page);
  await connect(page);
  await page.evaluate(() => { location.hash = 'studio?title=Cosmic+Bonk&ticker=CBONK'; });
  await page.locator('#imageAFile').setInputFiles({ name: 'a.png', mimeType: 'image/png', buffer: image });
  await page.locator('#imageBFile').setInputFiles({ name: 'b.png', mimeType: 'image/png', buffer: image });
  await page.locator('#hybridButton').click();
  await expect(page.locator('#hybridStatus')).toHaveText('Mix ready');
  await page.locator('#useMixForLaunch').click();
  await expect(page.locator('#launchName')).toHaveValue('Cosmic Bonk');
  await expect(page.locator('#reviewImage')).toBeVisible();
});
