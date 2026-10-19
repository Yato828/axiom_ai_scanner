import { pumpCreateInstruction } from './pump-create.js';
import { ComputeBudgetProgram, Connection, Keypair, PublicKey, TransactionMessage, VersionedTransaction } from '@solana/web3.js';
import { encodeBase58 } from './launch-core.js';

const MAINNET_GENESIS = '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp';
const PUMP_PROGRAM = '6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P';

export function connection(csrf) {
  return new Connection(`${location.origin}/api/rpc`, {
    commitment: 'confirmed', disableRetryOnRateLimit: true,
    httpHeaders: { 'X-CSRF-Token': csrf },
  });
}

export async function createInstructions(mint, wallet, metadata) {
  const instruction = pumpCreateInstruction(mint, wallet, metadata);
  if (instruction.programId.toBase58() !== PUMP_PROGRAM) throw new Error('Unexpected launch program.');
  return [
    ComputeBudgetProgram.setComputeUnitLimit({ units: 400_000 }),
    ComputeBudgetProgram.setComputeUnitPrice({ microLamports: 10_000 }),
    instruction,
  ];
}

export async function prepareLaunch({ wallet, metadata, csrf, maxCost }) {
  const rpc = connection(csrf);
  if (await rpc.getGenesisHash() !== MAINNET_GENESIS) throw new Error('The configured Solana connection is not mainnet.');
  const payer = new PublicKey(wallet);
  const mint = Keypair.generate();
  const instructions = await createInstructions(mint.publicKey, payer, metadata);
  const latest = await rpc.getLatestBlockhash('confirmed');
  const transaction = new VersionedTransaction(new TransactionMessage({
    payerKey: payer, recentBlockhash: latest.blockhash, instructions,
  }).compileToV0Message());
  transaction.sign([mint]);
  const [balance, simulation, fee] = await Promise.all([
    rpc.getBalance(payer, 'confirmed'),
    rpc.simulateTransaction(transaction, {
      sigVerify: false, replaceRecentBlockhash: true, commitment: 'confirmed',
      accounts: { encoding: 'base64', addresses: [wallet] },
    }),
    rpc.getFeeForMessage(transaction.message, 'confirmed'),
  ]);
  if (simulation.value.err) throw new Error('Launch simulation failed. Check your SOL balance and token details. No transaction was sent.');
  const after = simulation.value.accounts?.[0]?.lamports;
  if (!Number.isSafeInteger(after) || fee.value === null) throw new Error('Solana did not return a reliable cost estimate. Please review again.');
  const estimatedLamports = Math.max(balance - after, fee.value);
  // Reserve a small margin for concurrent balance changes. This launch contains no buy or transfer.
  if (estimatedLamports + 10_000 > balance) throw new Error('Your wallet needs more SOL for network fees and account rent.');
  if (estimatedLamports > Math.floor(maxCost * 1e9)) throw new Error('Estimated launch cost exceeds your maximum. Raise your limit only after reviewing the estimate.');
  return { transaction, rpc, wallet, mint: mint.publicKey.toBase58(), ...latest, estimatedLamports, preparedAt: Date.now() };
}

export async function signAndSubmit(prepared, provider, onSigned) {
  if (Date.now() - prepared.preparedAt > 60_000) throw new Error('This review expired. Review your launch again for a fresh transaction.');
  if (provider.publicKey?.toString() !== prepared.wallet) throw new Error('Wallet account changed. Reconnect and review again.');
  const originalMessage = prepared.transaction.message.serialize();
  const signed = await provider.signTransaction(prepared.transaction);
  if (provider.publicKey?.toString() !== prepared.wallet) throw new Error('Wallet account changed before submission. Nothing was sent.');
  const returnedMessage = signed.message.serialize();
  if (returnedMessage.length !== originalMessage.length || !originalMessage.every((byte, index) => byte === returnedMessage[index])) {
    throw new Error('Wallet returned a different transaction. Nothing was sent.');
  }
  if (!signed.signatures[0]?.some(byte => byte !== 0)) throw new Error('Wallet did not sign the transaction.');
  const signature = encodeBase58(signed.signatures[0]);
  const pending = { wallet: prepared.wallet, mint: prepared.mint, signature, blockhash: prepared.blockhash, lastValidBlockHeight: prepared.lastValidBlockHeight };
  // Persist BEFORE sending. An HTTP timeout must never invite a duplicate launch.
  onSigned(pending);
  const returnedSignature = await prepared.rpc.sendRawTransaction(signed.serialize(), { skipPreflight: false, maxRetries: 2 });
  if (returnedSignature !== signature) throw new Error('Unexpected transaction response. Check the saved transaction status.');
  return pending;
}

export async function transactionStatus(rpc, pending) {
  const result = await rpc.getSignatureStatuses([pending.signature], { searchTransactionHistory: true });
  const status = result.value[0];
  if (status?.err) return 'failed';
  if (['confirmed', 'finalized'].includes(status?.confirmationStatus)) return 'confirmed';
  // Expiry only permits a new launch when no transaction was observed on chain.
  if (!status && await rpc.getBlockHeight('confirmed') > pending.lastValidBlockHeight) return 'expired';
  return 'pending';
}
