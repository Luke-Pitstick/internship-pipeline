import { readdir, readFile, mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { gzipSync, brotliCompressSync } from 'node:zlib';
async function walk(path) {
  const entries = await readdir(path, { withFileTypes: true });
  return (await Promise.all(entries.map(entry => entry.isDirectory() ? walk(join(path, entry.name)) : join(path, entry.name)))).flat();
}
const files = (await walk('build')).filter(path => path.endsWith('.js'));
const assets = await Promise.all(files.map(async path => {
  const content = await readFile(path);
  return { path, rawBytes: content.length, gzipBytes: gzipSync(content, { level: 9 }).length, brotliBytes: brotliCompressSync(content).length };
}));
const total = assets.reduce((sum, item) => ({ rawBytes: sum.rawBytes + item.rawBytes, gzipBytes: sum.gzipBytes + item.gzipBytes, brotliBytes: sum.brotliBytes + item.brotliBytes }), { rawBytes: 0, gzipBytes: 0, brotliBytes: 0 });
const report = { method: 'Sum each independently compressed static JavaScript asset, including both routes. Conservative upper bound on initial JS; excludes maps, CSS, HTML, design assets.', budgetBytes: 200_000, total, underBudget: total.gzipBytes <= 200_000, assets };
await mkdir('reports', { recursive: true });
await writeFile('reports/t04-t05-bundle.json', JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ ...report, assets: `${assets.length} JavaScript files; see reports/t04-t05-bundle.json` }, null, 2));
if (!report.underBudget) process.exitCode = 1;
