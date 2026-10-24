import { test, expect } from '@playwright/test';

const tokens = [
  { token: 'BONK', name: 'Bonk', address: 'BonkTestAddress', chain: 'solana', signal: 'HOT', score: 86.4, image_url: '/assets/tokens/BONK.svg', market_cap: 1_200_000, liquidity_usd: 200_000, volume_1h: 80_000, price_change_1h: 12.5, txns_1h: 210, age_minutes: 180, why: 'Strong volume and liquidity.', risk_flags: [], url: 'https://dexscreener.com/solana/test' },
  { token: 'WIF', name: 'dogwifhat', address: 'WifTestAddress', chain: 'solana', signal: 'WATCH', score: 72.1, image_url: '/assets/tokens/WIF.svg', market_cap: 900_000, liquidity_usd: 150_000, volume_1h: 40_000, price_change_1h: -2.1, txns_1h: 110, age_minutes: 120, why: 'An established community.', risk_flags: ['Sell pressure'], url: 'https://dexscreener.com/solana/test-wif' },
];
const og = [{ name: 'Pudgy Penguins', symbol: 'PENGU', image_url: '/assets/tokens/PENGU.svg', archetype: 'penguin' }];
const narrative = { name: 'Pudgy Bonk', ticker: 'PBONK', trend_token: 'BONK', og_token: 'PENGU', og_name: 'Pudgy Penguins', hook: 'A new perspective on familiar faces.', visual_brief: 'A penguin with Bonk features.', image_prompt: 'Mix the dog and penguin into one character.', change_1h: 12.5 };

async function mockFeed(page) {
  const requests = { scans: [], narratives: [] };
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    let body = {};
    if (url.pathname === '/api/config') body = { launch: { enabled: false, message: 'Launch is not configured.' }, generation_ready: false };
    if (url.pathname === '/api/scan') {
      requests.scans.push(url.searchParams.get('limit'));
      body = { tokens, og_memecoins: og, narratives: [narrative], min_market_cap_usd: 10000, updated_at: '12:00:00' };
    }
    if (url.pathname === '/api/narratives') {
      requests.narratives.push(route.request().postDataJSON());
      body = { narratives: [narrative] };
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
  return requests;
}

test('the original native animation loads locally under the unchanged CSP and can be paused', async ({ page }) => {
  const errors = [];
  const external = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (new URL(request.url()).origin !== 'http://127.0.0.1:8080') external.push(request.url());
  });
  await page.addInitScript(() => {
    window.cspViolations = [];
    document.addEventListener('securitypolicyviolation', event => window.cspViolations.push(event.violatedDirective));
  });
  await mockFeed(page);
  const response = await page.goto('/');
  expect(response.headers()['content-security-policy']).toContain("script-src 'self'");
  await expect(page.locator('#mindWave')).toHaveAttribute('data-scene-state', 'ready');
  await expect(page.locator('#mindWave canvas')).toHaveCount(1);
  await expect.poll(() => page.evaluate(() => document.fonts.check('20px Adelphe'))).toBeTruthy();
  await expect.poll(async () => Number(await page.locator('#mindWave canvas').getAttribute('data-frame'))).toBeGreaterThan(2);
  await expect(page.locator('script[src*="unicorn"], img[src*="unicorn"]')).toHaveCount(0);
  await page.getByRole('button', { name: 'Pause background animation' }).click();
  await expect(page.locator('#motionToggle')).toHaveAttribute('aria-pressed', 'true');
  const frozenFrame = await page.locator('#mindWave canvas').getAttribute('data-frame');
  await page.waitForTimeout(150);
  await expect(page.locator('#mindWave canvas')).toHaveAttribute('data-frame', frozenFrame);
  await page.reload();
  await expect(page.locator('#mindWave')).toHaveAttribute('data-scene-state', 'poster');
  await expect(page.locator('#mindWave canvas')).toHaveCount(0);
  await page.getByRole('button', { name: 'Play background animation' }).click();
  await expect(page.locator('#mindWave')).toHaveAttribute('data-scene-state', 'ready');
  await expect(page.locator('#motionToggle')).toHaveAttribute('aria-pressed', 'false');
  expect(await page.evaluate(() => window.cspViolations)).toEqual([]);
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
});

test('reduced motion uses original artwork and the three mascot variants retain transparency', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mockFeed(page);
  await page.goto('/');
  await expect(page.locator('#mindWave')).toHaveAttribute('data-scene-state', 'poster');
  await expect(page.locator('#mindWave canvas')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Play background animation' })).toHaveAttribute('aria-pressed', 'true');
  const poster = await page.request.get('/assets/signal-wave.svg');
  expect(poster.ok()).toBeTruthy();
  expect(poster.headers()['content-type']).toBe('image/svg+xml');
  const placements = [
    ['.mascot-mark', '/assets/mascots/avatar.png'],
    ['.hero-mascot', '/assets/mascots/hero.png'],
    ['.result-placeholder img', '/assets/mascots/studio.png'],
    ['#reviewPlaceholder img', '/assets/mascots/avatar.png'],
  ];
  for (const [selector, source] of placements) {
    for (const image of await page.locator(selector).all()) await expect(image).toHaveAttribute('src', source);
  }
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', '/assets/mascots/avatar.png');
  const alpha = await page.evaluate(async () => Promise.all(['avatar', 'studio', 'hero'].map(async variant => {
    const image = new Image(); image.src = `/assets/mascots/${variant}.png`; await image.decode();
    const canvas = document.createElement('canvas'); canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
    const context = canvas.getContext('2d'); context.drawImage(image, 0, 0);
    const at = (x, y) => context.getImageData(x, y, 1, 1).data[3];
    return { variant, corner: at(0, 0), character: at(Math.floor(canvas.width / 2), Math.floor(canvas.height * 0.4)) };
  })));
  for (const sample of alpha) {
    expect(sample.corner, sample.variant).toBe(0);
    expect(sample.character, sample.variant).toBeGreaterThan(240);
  }
});

test('the redesigned feed still refreshes, mixes narratives and fills studio references', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const requests = await mockFeed(page);
  await page.goto('/#discover');
  await expect(page.locator('#foundCount')).toHaveText('2');
  await expect(page.locator('#hotCount')).toHaveText('1');
  await expect(page.locator('.token-card')).toHaveCount(2);
  await expect(page.locator('.badge.hot')).toHaveText('HOT');
  await expect(page.locator('.badge.watch')).toHaveText('WATCH');
  await page.locator('#limitInput').fill('12');
  await page.locator('#scanButton').click();
  await expect.poll(() => requests.scans.at(-1)).toBe('12');
  await page.locator('#ogInput').fill('Pudgy Penguins,PENGU,penguin');
  await page.locator('#narrativeButton').click();
  await expect.poll(() => requests.narratives.length).toBe(1);
  expect(requests.narratives[0].tokens).toEqual(tokens);
  expect(requests.narratives[0].og_memecoins).toEqual([{ name: 'Pudgy Penguins', symbol: 'PENGU', archetype: 'penguin' }]);
  await page.locator('.hybrid-studio-button').click();
  await expect(page.locator('#hybridStatus')).toHaveText('References loaded');
  await expect(page.locator('#imageAPreview')).toHaveAttribute('src', '/assets/tokens/BONK.svg');
  await expect(page.locator('#imageBPreview')).toHaveAttribute('src', '/assets/tokens/PENGU.svg');
  await expect(page.locator('#hybridPrompt')).toHaveValue(/Mix the dog and penguin into one character/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.locator('#connectWallet').click();
  await expect(page.locator('#walletDialog')).toBeVisible();
  await page.getByRole('button', { name: 'Close wallet selection' }).click();
  await expect(page.locator('#walletDialog')).not.toBeVisible();
});

test('a missing animation runtime leaves the feed and mixer usable', async ({ page }) => {
  await mockFeed(page);
  await page.route('**/signal-wave.js*', route => route.abort());
  await page.goto('/');
  await expect(page.locator('#mindWave')).toHaveAttribute('data-scene-state', 'fallback');
  await expect(page.locator('#foundCount')).toHaveText('2');
  await expect(page.locator('.token-card')).toHaveCount(2);
  await page.locator('.hero-secondary').click();
  await expect(page).toHaveURL(/#studio$/);
  await expect(page.locator('#hybridForm')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
