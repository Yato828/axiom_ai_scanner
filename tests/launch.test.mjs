import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { Keypair, PublicKey, TransactionMessage, VersionedTransaction } from '@solana/web3.js';
import { validateToken, readPending, encodeBase58 } from '../web/launch-core.js';
import { pumpCreateInstruction } from '../web/pump-create.js';
import { signAndSubmit, transactionStatus } from '../web/launch-chain.js';

test('creation matches the official Pump SDK reference bytes, account order and permissions', () => {
  const reference = JSON.parse(fs.readFileSync(new URL('./fixtures/pump-create-v2.json', import.meta.url)));
  const instruction = pumpCreateInstruction(new PublicKey(reference.mint), new PublicKey(reference.user), reference.metadata);
  assert.equal(instruction.data.toString('hex'), reference.data);
  assert.deepEqual(instruction.keys.map(key => ({ address: key.pubkey.toBase58(), signer: key.isSigner, writable: key.isWritable })), reference.keys);
  assert.equal(instruction.programId.toBase58(), '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P');
});

test('token details enforce the on-chain UTF-8 name limit and HTTPS social links', () => {
  assert.throws(() => validateToken({ name: '🚀'.repeat(9), symbol: 'TEST' }, true), /UTF-8/);
  assert.throws(() => validateToken({ name: 'Token', symbol: 'TEST', website: 'javascript:alert(1)' }, true), /HTTPS/);
  assert.throws(() => validateToken({ name: 'Token', symbol: 'TEST' }, false), /artwork/);
  assert.equal(validateToken({ name: 'A token', symbol: 'test' }, true).symbol, 'TEST');
});

function preparedFixture() {
  const payer = Keypair.generate(), mint = Keypair.generate();
  const instruction = pumpCreateInstruction(mint.publicKey, payer.publicKey, { name: 'Token', symbol: 'TKN', uri: 'https://ipfs.io/ipfs/bafybeiexample' });
  const transaction = new VersionedTransaction(new TransactionMessage({ payerKey: payer.publicKey, recentBlockhash: Keypair.generate().publicKey.toBase58(), instructions: [instruction] }).compileToV0Message());
  transaction.sign([mint]);
  return { payer, mint, transaction, wallet: payer.publicKey.toBase58(), preparedAt: Date.now(), rpc: {} };
}

test('wallet refusal never submits a transaction', async () => {
  const prepared = preparedFixture();
  let submissions = 0;
  prepared.rpc.sendRawTransaction = async () => { submissions++; };
  const provider = { publicKey: prepared.payer.publicKey, signTransaction: async () => { throw new Error('declined'); } };
  await assert.rejects(signAndSubmit(prepared, provider, () => assert.fail('must not persist')), /declined/);
  assert.equal(submissions, 0);
});

test('signed transaction is persisted before an ambiguous network error', async () => {
  const prepared = preparedFixture();
  let saved = null;
  const provider = { publicKey: prepared.payer.publicKey, signTransaction: async tx => { tx.sign([prepared.payer]); return tx; } };
  prepared.rpc.sendRawTransaction = async () => { assert.ok(saved?.signature); throw new Error('network timeout'); };
  await assert.rejects(signAndSubmit(prepared, provider, value => { saved = value; }), /network timeout/);
  assert.equal(saved.wallet, prepared.wallet);
});

test('a changed transaction or wallet cannot be submitted', async () => {
  const prepared = preparedFixture();
  const provider = { publicKey: prepared.payer.publicKey, signTransaction: async tx => { tx.message.recentBlockhash = Keypair.generate().publicKey.toBase58(); return tx; } };
  await assert.rejects(signAndSubmit(prepared, provider, () => assert.fail()), /different transaction/);
  provider.publicKey = Keypair.generate().publicKey;
  await assert.rejects(signAndSubmit(prepared, provider, () => assert.fail()), /account changed/);
});

test('processed transactions are pending until the chain confirms them', async () => {
  const pending = { signature: 'abc', lastValidBlockHeight: 100 };
  const rpc = { getSignatureStatuses: async () => ({ value: [{ confirmationStatus: 'processed', err: null }] }), getBlockHeight: async () => 500 };
  assert.equal(await transactionStatus(rpc, pending), 'pending');
  rpc.getSignatureStatuses = async () => ({ value: [{ confirmationStatus: 'confirmed', err: null }] });
  assert.equal(await transactionStatus(rpc, pending), 'confirmed');
  rpc.getSignatureStatuses = async () => ({ value: [{ confirmationStatus: 'confirmed', err: { InstructionError: [0, 'error'] } }] });
  assert.equal(await transactionStatus(rpc, pending), 'failed');
});

test('saved pending transactions survive page reload and reject malformed storage', () => {
  const wallet = Keypair.generate().publicKey.toBase58();
  const pending = { wallet, mint: Keypair.generate().publicKey.toBase58(), signature: encodeBase58(new Uint8Array(64).fill(5)) };
  const storage = { getItem: () => JSON.stringify(pending) };
  assert.deepEqual(readPending(storage, wallet), pending);
  storage.getItem = () => '{broken';
  assert.equal(readPending(storage, wallet), null);
});
