import { readPending, validateToken } from './launch-core.js';

const $ = selector => document.querySelector(selector);
const form = $('#launchForm');
const dialog = $('#walletDialog');
const walletButton = $('#connectWallet');
const status = $('#launchStatus');
const errorSlot = $('#launchFormError');
const reviewButton = $('#reviewLaunch');
const confirmButton = $('#confirmLaunch');
const checkButton = $('#checkLaunchStatus');
let session = null;
let provider = null;
let settings = null;
let artwork = null;
let artworkUrl = null;
let latestMix = null;
let prepared = null;
let pending = null;
let busy = false;
let connecting = false;
let resolveConnection = null;
let disconnectListeners = [];
let revision = 0;
let pinnedMetadata = null;
const encoder = new TextEncoder();

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 65_000);
  try {
    const response = await fetch(path, {
      ...options, signal: options.signal || controller.signal, credentials: 'same-origin',
      headers: { ...options.headers, ...(session ? { 'X-CSRF-Token': session.csrf } : {}) },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      if (response.status === 401) clearSession();
      throw new Error(payload.error || `Request failed (${response.status}). Please try again.`);
    }
    return response;
  } finally { clearTimeout(timeout); }
}

function jsonPost(path, payload) {
  return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then(response => response.json());
}

function showError(message) {
  errorSlot.textContent = message || '';
  errorSlot.hidden = !message;
}

function shortWallet(value) { return `${value.slice(0, 4)}…${value.slice(-4)}`; }

function invalidate() {
  revision++;
  prepared = null;
  confirmButton.hidden = true;
  reviewButton.hidden = Boolean(pending);
  $('#reviewFee').textContent = 'Available after review';
  $('#launchConsent').checked = false;
  $('#launchSuccess').hidden = true;
  document.querySelectorAll('.launch-steps li').forEach((step, index) => step.classList.toggle('active', index === 0));
}

function setBusy(value) {
  busy = value;
  reviewButton.disabled = value || !settings?.launch?.enabled || Boolean(pending);
  confirmButton.disabled = value;
  checkButton.disabled = value;
  walletButton.disabled = value;
  for (const element of form.elements) element.disabled = value;
  $('#maxLaunchCost').disabled = value;
}

function clearSession() {
  session = null;
  provider = null;
  pending = null;
  for (const remove of disconnectListeners) remove();
  disconnectListeners = [];
  invalidate();
  walletButton.textContent = 'Connect wallet';
  $('#reviewWallet').textContent = 'Not connected';
  checkButton.hidden = true;
  window.dispatchEvent(new CustomEvent('memorphia:wallet-change', { detail: null }));
}

function updateSession(value, walletProvider) {
  session = value;
  provider = walletProvider;
  walletButton.textContent = `${shortWallet(value.wallet)} · Disconnect`;
  $('#reviewWallet').textContent = shortWallet(value.wallet);
  invalidate();
  try { pending = readPending(localStorage, value.wallet); } catch { pending = null; }
  if (pending) {
    checkButton.hidden = false;
    reviewButton.hidden = true;
    status.textContent = 'A signed launch is saved on this device. Check its status before creating another token.';
  }
  const onChanged = key => {
    if (!key || key.toString() !== session?.wallet) {
      clearSession();
      status.textContent = 'Wallet account changed. Connect again before continuing.';
    }
  };
  const onDisconnected = () => { clearSession(); status.textContent = 'Wallet disconnected.'; };
  walletProvider.on?.('accountChanged', onChanged);
  walletProvider.on?.('disconnect', onDisconnected);
  disconnectListeners.push(() => walletProvider.removeListener?.('accountChanged', onChanged));
  disconnectListeners.push(() => walletProvider.removeListener?.('disconnect', onDisconnected));
  window.dispatchEvent(new CustomEvent('memorphia:wallet-change', { detail: value.wallet }));
}

function injectedWallet(name) {
  if (name === 'phantom') return window.phantom?.solana?.isPhantom ? window.phantom.solana : null;
  return window.solflare?.isSolflare ? window.solflare : null;
}

function requireWallet() {
  if (session && provider?.publicKey?.toString() === session.wallet) return Promise.resolve(session);
  if (resolveConnection) return resolveConnection.promise;
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  resolveConnection = { resolve, reject, promise };
  $('#walletError').hidden = true;
  dialog.showModal();
  return promise;
}

async function connect(name) {
  if (connecting) return;
  const selected = injectedWallet(name);
  const error = $('#walletError');
  error.hidden = true;
  if (!selected) {
    error.textContent = `${name === 'phantom' ? 'Phantom' : 'Solflare'} is not detected. Install the wallet extension, or open this website in your wallet's mobile browser.`;
    error.hidden = false;
    return;
  }
  connecting = true;
  for (const button of dialog.querySelectorAll('[data-wallet]')) button.disabled = true;
  try {
    await selected.connect();
    if (typeof selected.signMessage !== 'function' || typeof selected.signTransaction !== 'function') throw new Error('This wallet does not support the required Solana signing methods.');
    const wallet = selected.publicKey.toString();
    const challenge = await jsonPost('/api/auth/challenge', { wallet });
    const signed = await selected.signMessage(encoder.encode(challenge.message), 'utf8');
    if (selected.publicKey?.toString() !== wallet) throw new Error('Wallet account changed during sign-in. Please try again.');
    const signature = signed.signature || signed;
    const verified = await jsonPost('/api/auth/verify', {
      challenge_id: challenge.challenge_id,
      signature: btoa(String.fromCharCode(...signature)),
    });
    if (verified.wallet !== wallet) throw new Error('Wallet verification returned a different account.');
    updateSession(verified, selected);
    const waiting = resolveConnection;
    resolveConnection = null;
    dialog.close();
    waiting?.resolve(verified);
  } catch (failure) {
    error.textContent = failure.code === 4001 ? 'Connection or sign-in was declined. Nothing was sent.' : failure.message;
    error.hidden = false;
  } finally {
    connecting = false;
    for (const button of dialog.querySelectorAll('[data-wallet]')) button.disabled = false;
  }
}

async function disconnect() {
  const previous = provider;
  try { await api('/api/auth/logout', { method: 'POST' }); }
  catch { /* The wallet can always be disconnected locally. */ }
  clearSession();
  await previous?.disconnect?.().catch(() => {});
}

function readFields() {
  return Object.fromEntries(['name', 'symbol', 'description', 'website', 'twitter'].map(key => [key, form.elements.namedItem(key).value]));
}

function renderPreview() {
  const values = readFields();
  $('#reviewName').textContent = values.name || 'Your next big idea';
  $('#reviewSymbol').textContent = `$${values.symbol || 'YOURTOKEN'}`;
  $('#reviewDescription').textContent = values.description || 'Your token story will appear here.';
  $('#nameCount').textContent = `${encoder.encode(values.name || '').length} / 32 bytes`;
}

async function setArtwork(blob) {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(blob.type) || blob.size > 3 * 1024 * 1024 || blob.size === 0) {
    throw new Error('Choose a PNG, JPG or WebP image smaller than 3 MB.');
  }
  const bitmap = await createImageBitmap(blob);
  const valid = bitmap.width >= 32 && bitmap.height >= 32 && bitmap.width * bitmap.height <= 16_000_000;
  bitmap.close();
  if (!valid) throw new Error('Artwork must be at least 32 × 32 px and no larger than 16 megapixels.');
  if (artworkUrl) URL.revokeObjectURL(artworkUrl);
  artwork = blob;
  artworkUrl = URL.createObjectURL(blob);
  for (const image of [$('#launchImagePreview'), $('#reviewImage')]) { image.src = artworkUrl; image.hidden = false; }
  $('#reviewPlaceholder').hidden = true;
  $('#launchImageHint').hidden = true;
  pinnedMetadata = null;
  invalidate();
}

async function useMixedImage() {
  if (!latestMix) throw new Error('Generate an image in Mixer Studio first.');
  await requireWallet();
  setBusy(true);
  try {
    status.textContent = 'Loading your mixed artwork…';
    const response = await api('/api/images/import', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: latestMix.url }),
    });
    await setArtwork(await response.blob());
    if (latestMix.name) $('#launchName').value = latestMix.name.slice(0, 32);
    if (latestMix.symbol) $('#launchSymbol').value = latestMix.symbol.replace(/[^a-z0-9]/gi, '').slice(0, 13).toUpperCase();
    renderPreview();
    location.hash = 'launch';
    status.textContent = settings.launch.message;
  } finally { setBusy(false); }
}

async function reviewLaunch() {
  if (busy || pending) return;
  showError('');
  try {
    if (!form.reportValidity()) return;
    const fields = validateToken(readFields(), Boolean(artwork));
    const maxCost = Number($('#maxLaunchCost').value);
    if (!Number.isFinite(maxCost) || maxCost < 0.001 || maxCost > 1) throw new Error('Maximum launch cost must be between 0.001 and 1 SOL.');
    if (!settings?.launch.enabled) throw new Error(settings?.launch.message || 'Launch is not configured yet.');
    await requireWallet();
    if (pending) throw new Error('Check your saved transaction before creating another token.');
    const version = revision;
    const wallet = session.wallet;
    setBusy(true);
    status.textContent = 'Storing artwork and checking the launch…';
    const serialized = JSON.stringify(fields);
    if (!pinnedMetadata || pinnedMetadata.fields !== serialized) {
      const upload = new FormData();
      for (const [key, value] of Object.entries(fields)) upload.set(key, value);
      upload.set('image', artwork, 'token.png');
      const payload = await (await api('/api/launch/metadata', { method: 'POST', body: upload })).json();
      pinnedMetadata = { fields: serialized, payload };
    }
    const chain = await import('./launch-chain.js');
    const quote = await chain.prepareLaunch({
      wallet, csrf: session.csrf, metadata: { ...fields, uri: pinnedMetadata.payload.uri }, maxCost,
    });
    if (version !== revision || session?.wallet !== wallet) throw new Error('Token details or wallet changed. Review again.');
    prepared = quote;
    $('#reviewFee').textContent = `≈ ${(quote.estimatedLamports / 1e9).toFixed(6)} SOL`;
    reviewButton.hidden = true;
    confirmButton.hidden = false;
    status.textContent = 'Simulation passed. Review your details, accept the mainnet notice, then confirm in your wallet. This review expires in 60 seconds.';
    document.querySelectorAll('.launch-steps li').forEach((step, index) => step.classList.toggle('active', index === 1));
  } catch (failure) { showError(failure.message); status.textContent = 'No transaction was sent.'; }
  finally { setBusy(false); }
}

function persistPending(value) {
  // Require persistence so a refresh during RPC failure cannot silently create another mint.
  localStorage.setItem(`memorphia:pending:${value.wallet}`, JSON.stringify(value));
  pending = value;
  confirmButton.hidden = true;
  reviewButton.hidden = true;
  checkButton.hidden = false;
  $('#launchTxLink').href = `https://solscan.io/tx/${value.signature}`;
  prepared = null;
}

async function confirmLaunch() {
  if (busy || !prepared || pending) return;
  showError('');
  if (!$('#launchConsent').checked) { showError('Review and accept the mainnet launch notice first.'); return; }
  setBusy(true);
  try {
    const quote = prepared;
    const chain = await import('./launch-chain.js');
    status.textContent = 'Confirm the token creation transaction in your wallet.';
    document.querySelectorAll('.launch-steps li').forEach((step, index) => step.classList.toggle('active', index === 2));
    await chain.signAndSubmit(quote, provider, persistPending);
    status.textContent = 'Transaction submitted. Waiting for Solana confirmation…';
    await pollConfirmation();
  } catch (failure) {
    if (pending) {
      status.textContent = 'Transaction status is uncertain. Check the saved transaction before trying another launch.';
    } else {
      invalidate();
      showError(failure.code === 4001 ? 'Transaction declined in your wallet. No launch was submitted.' : failure.message);
      status.textContent = 'Review your launch again when ready.';
    }
  } finally { setBusy(false); }
}

async function checkStatus() {
  if (!pending || !session) return 'pending';
  const value = pending;
  const wallet = session.wallet;
  if (value.wallet !== wallet) throw new Error('Connect the wallet that signed this launch.');
  const chain = await import('./launch-chain.js');
  const state = await chain.transactionStatus(chain.connection(session.csrf), value);
  if (session?.wallet !== wallet || pending !== value) return 'pending';
  if (state === 'confirmed') {
    $('#launchSuccess').hidden = false;
    $('#pumpTokenLink').href = `https://pump.fun/coin/${value.mint}`;
    $('#launchTxLink').href = `https://solscan.io/tx/${value.signature}`;
    status.textContent = 'Token creation confirmed on Solana mainnet.';
    checkButton.hidden = true;
    $('#startNewToken').hidden = false;
    // Retain the completed transaction until the user explicitly starts a fresh draft.
    localStorage.setItem(`memorphia:pending:${wallet}`, JSON.stringify({ ...value, confirmed: true }));
  } else if (state === 'expired' || state === 'failed') {
    localStorage.removeItem(`memorphia:pending:${wallet}`);
    pending = null;
    checkButton.hidden = true;
    invalidate();
    status.textContent = state === 'failed' ? 'Solana rejected the launch. Network fees may have been charged. You can review again.' : 'The transaction expired without confirmation. You can review a new launch.';
  } else {
    status.textContent = 'Confirmation is pending. Check this transaction again; do not create a duplicate launch.';
  }
  return state;
}

async function pollConfirmation() {
  for (let count = 0; count < 20 && pending && session; count++) {
    try { if (await checkStatus() !== 'pending') return; }
    catch { status.textContent = 'Waiting for the Solana connection. Your signed transaction is saved.'; }
    await new Promise(resolve => setTimeout(resolve, 2500));
  }
  if (pending) status.textContent = 'Confirmation is taking longer. Check the saved transaction status before another launch.';
}

walletButton.addEventListener('click', () => {
  if (session) disconnect().catch(failure => showError(failure.message));
  else requireWallet().catch(() => {});
});
dialog.addEventListener('click', event => {
  const button = event.target.closest('[data-wallet]');
  if (button) connect(button.dataset.wallet);
});
function closeWalletDialog() { if (!connecting) dialog.close(); }
$('#closeWalletDialog').addEventListener('click', closeWalletDialog);
dialog.addEventListener('cancel', event => { if (connecting) event.preventDefault(); });
dialog.addEventListener('close', () => {
  resolveConnection?.reject(new Error('Wallet connection was cancelled.'));
  resolveConnection = null;
});
form.addEventListener('submit', event => event.preventDefault());
form.addEventListener('input', () => { pinnedMetadata = null; invalidate(); renderPreview(); });
$('#maxLaunchCost').addEventListener('input', invalidate);
$('#launchSymbol').addEventListener('input', event => { event.target.value = event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''); renderPreview(); });
$('#launchImage').addEventListener('change', async event => {
  showError('');
  try { if (event.target.files[0]) await setArtwork(event.target.files[0]); }
  catch (failure) { showError(failure.message); event.target.value = ''; }
});
$('#chooseOwnImage').addEventListener('click', () => $('#launchImage').click());
for (const button of [$('#chooseMixedImage'), $('#useMixForLaunch')]) button.addEventListener('click', () => useMixedImage().catch(failure => showError(failure.message)));
reviewButton.addEventListener('click', reviewLaunch);
confirmButton.addEventListener('click', confirmLaunch);
checkButton.addEventListener('click', async () => {
  if (busy) return;
  setBusy(true);
  try { await checkStatus(); } catch (failure) { showError(failure.message); }
  finally { setBusy(false); }
});
$('#saveDraft').addEventListener('click', () => {
  try {
    localStorage.setItem('memorphia:draft', JSON.stringify(readFields()));
    $('#restoreDraft').hidden = false;
    status.textContent = 'Draft details saved on this device. Keep a copy of your artwork separately.';
  } catch { showError('Device storage is unavailable. Download your draft instead.'); }
});
$('#restoreDraft').addEventListener('click', () => {
  try {
    const fields = JSON.parse(localStorage.getItem('memorphia:draft'));
    for (const key of ['name', 'symbol', 'description', 'website', 'twitter']) {
      const input = form.elements.namedItem(key);
      input.value = typeof fields[key] === 'string' ? fields[key].slice(0, input.maxLength) : '';
    }
    invalidate(); renderPreview();
    status.textContent = 'Draft restored. Choose its artwork before reviewing your launch.';
  } catch { showError('This draft could not be restored.'); }
});
$('#downloadDraft').addEventListener('click', () => {
  const blob = new Blob([JSON.stringify({ ...readFields(), network: 'mainnet-beta', platform: 'pump.fun' }, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = 'token-draft.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
});
$('#startNewToken').addEventListener('click', () => {
  if (busy || !session || !pending) return;
  localStorage.removeItem(`memorphia:pending:${session.wallet}`);
  pending = null;
  form.reset();
  artwork = null;
  if (artworkUrl) URL.revokeObjectURL(artworkUrl);
  artworkUrl = null;
  pinnedMetadata = null;
  for (const img of [$('#launchImagePreview'), $('#reviewImage')]) { img.hidden = true; img.removeAttribute('src'); }
  $('#reviewPlaceholder').hidden = false;
  $('#launchImageHint').hidden = false;
  $('#startNewToken').hidden = true;
  invalidate(); renderPreview();
  setBusy(false);
  status.textContent = 'Start a new draft with your own image or a fresh mix.';
});
window.addEventListener('memorphia:mix-ready', event => {
  latestMix = event.detail;
  $('#chooseMixedImage').disabled = false;
  $('#useMixForLaunch').hidden = false;
});
window.memorphia = { requireWallet, api, getSession: () => session };

try {
  const response = await api('/api/config');
  settings = await response.json();
  status.textContent = settings.launch.message;
  reviewButton.disabled = !settings.launch.enabled;
  if (!settings.generation_ready) {
    $('#hybridStatus').textContent = 'Image generation needs configuration';
  }
  try { $('#restoreDraft').hidden = !localStorage.getItem('memorphia:draft'); } catch { /* Optional draft storage. */ }
} catch {
  status.textContent = 'Launch settings could not be loaded. Reload this page to try again.';
  reviewButton.disabled = true;
}
