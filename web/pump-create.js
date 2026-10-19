import { PublicKey, SystemProgram, TransactionInstruction } from '@solana/web3.js';
import { validateToken } from './launch-core.js';

// SOL-paired create_v2 ABI, checked byte-for-byte against @pump-fun/pump-sdk 4.1.0.
// https://github.com/pump-fun/pump-public-docs/blob/main/docs/instructions/COIN_CREATION.md
// Keep this small fixed instruction surface: no swaps, transfers, approvals or arbitrary instructions.
export const PUMP_PROGRAM = new PublicKey('6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P');
const TOKEN_2022 = new PublicKey('TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb');
const ASSOCIATED = new PublicKey('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL');
const MAYHEM = new PublicKey('MAyhSmzXzV1pTf7LsNkrNwkWKTo4ougAJ1PPg47MD4e');
const pda = (program, ...seeds) => PublicKey.findProgramAddressSync(seeds, program)[0];
const seed = value => Buffer.from(value, 'utf8');
const ata = (owner, mint) => pda(ASSOCIATED, owner.toBuffer(), TOKEN_2022.toBuffer(), mint.toBuffer());
const key = (pubkey, isWritable = false, isSigner = false) => ({ pubkey, isWritable, isSigner });

function borshString(value) {
  const bytes = Buffer.from(value, 'utf8');
  const length = Buffer.alloc(4);
  length.writeUInt32LE(bytes.length);
  return Buffer.concat([length, bytes]);
}

export function pumpCreateInstruction(mint, wallet, metadata) {
  const checked = validateToken(metadata, true);
  if (typeof metadata.uri !== 'string' || !metadata.uri.startsWith('https://ipfs.io/ipfs/') || Buffer.byteLength(metadata.uri) > 200) throw new Error('Invalid token metadata URI.');
  const curve = pda(PUMP_PROGRAM, seed('bonding-curve'), mint.toBuffer());
  const solVault = pda(MAYHEM, seed('sol-vault'));
  return new TransactionInstruction({
    programId: PUMP_PROGRAM,
    keys: [
      key(mint, true, true), key(pda(PUMP_PROGRAM, seed('mint-authority'))),
      key(curve, true), key(ata(curve, mint), true), key(pda(PUMP_PROGRAM, seed('global'))),
      key(wallet, true, true), key(SystemProgram.programId), key(TOKEN_2022), key(ASSOCIATED),
      key(MAYHEM, true), key(pda(MAYHEM, seed('global-params'))), key(solVault, true),
      key(pda(MAYHEM, seed('mayhem-state'), mint.toBuffer()), true), key(ata(solVault, mint), true),
      key(pda(PUMP_PROGRAM, seed('__event_authority'))), key(PUMP_PROGRAM),
    ],
    data: Buffer.concat([
      Buffer.from([214, 144, 76, 236, 95, 139, 49, 180]),
      borshString(checked.name), borshString(checked.symbol), borshString(metadata.uri), wallet.toBuffer(),
      Buffer.alloc(11), // mayhem=false, cashback=false, creator fee=0, holder rewards=false
    ]),
  });
}
