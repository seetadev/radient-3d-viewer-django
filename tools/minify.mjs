// Minifies every .js file under a directory in place, one file at a time (no bundling), so the
// ES-module structure and import-map specifiers keep working. Used by the Dockerfile only; the
// committed sources stay readable.   usage: node tools/minify.mjs static
import { transform } from 'esbuild';
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const walk = (d) => readdirSync(d).flatMap((n) => {
  const p = join(d, n);
  return statSync(p).isDirectory() ? walk(p) : p.endsWith('.js') ? [p] : [];
});

let before = 0, after = 0;
for (const f of walk(process.argv[2] || 'static')) {
  const src = readFileSync(f, 'utf8');
  const { code } = await transform(src, { minify: true, format: 'esm', target: 'es2022', legalComments: 'inline' });
  writeFileSync(f, code);
  before += src.length; after += code.length;
}
console.log(`minified ${(before / 1024).toFixed(0)} KiB -> ${(after / 1024).toFixed(0)} KiB`);
