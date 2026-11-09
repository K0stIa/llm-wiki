// IPC worker for synthetic multi-process write tests. Never points at a real vault.
import { join, resolve, sep } from 'node:path';
import { work, wikiLib } from './lib.mjs';
const [directory, mode, workerId, countText] = process.argv.slice(2);
if (!resolve(directory).startsWith(resolve(work) + sep)) throw new Error('Test vault must be under .cache/comparison');
const { getVaultPaths } = await wikiLib('utils');
const { saveInsight } = await wikiLib('retro');
const { captureText } = await wikiLib('source-packet');
const paths = getVaultPaths(directory);
process.send({ ready: true });
process.once('message', () => {
  const writes = [];
  try {
    for (let n = 0; n < Number(countText); n++) {
      const marker = `writer-${workerId}-entry-${n}`;
      if (mode === 'capture') {
        const captured = captureText(paths, `Synthetic raw marker ${marker}\n` + 'padding '.repeat(1000), marker);
        writes.push({ marker, id: captured.sourceId });
      } else {
        const slug = mode === 'same-page' ? 'shared-proposal' : marker;
        saveInsight(paths, slug, marker, `Synthetic concurrent insight ${marker}`);
        writes.push({ marker, id: `sources/${slug}` });
      }
    }
    process.send({ writes });
  } catch (error) { process.send({ error: String(error), writes }); process.exitCode = 1; }
  process.disconnect();
});
