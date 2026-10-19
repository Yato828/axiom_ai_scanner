import { build } from 'esbuild';
import { readFile, writeFile, rm } from 'node:fs/promises';
import { gzipSync, brotliCompressSync } from 'node:zlib';
await rm('web/dist', { recursive: true, force: true });
await build({
  entryPoints: ['web/launcher.js'],
  outdir: 'web/dist',
  entryNames: '[name]',
  chunkNames: '[name]-[hash]',
  bundle: true,
  splitting: true,
  format: 'esm',
  platform: 'browser',
  target: ['es2022'],
  minify: true,
  sourcemap: false,
  define: { global: 'globalThis', 'process.env.NODE_ENV': '"production"' },
  inject: ['web/buffer-shim.js'],
  metafile: true,
}).then(async result => {
  for (const [path, output] of Object.entries(result.metafile.outputs)) {
    const data = await readFile(path);
    const compressed = gzipSync(data);
    await Promise.all([writeFile(path + '.gz', compressed), writeFile(path + '.br', brotliCompressSync(data))]);
    console.log(`${path}: ${(output.bytes / 1024).toFixed(1)} KB (${(compressed.length / 1024).toFixed(1)} KB gzip)`);
  }
});
