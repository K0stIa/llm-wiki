// Experiment utilities. These do not install or configure a production wiki.
import { createHash } from 'node:crypto';
import { readFileSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

export const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const work = join(root, '.cache', 'comparison');
export const results = join(root, 'research', 'results');
export const fixture = JSON.parse(readFileSync(join(root, 'research', 'fixture.json'), 'utf8'));
const managed = process.env.PI_MANAGED_INSTALL_ROOT || join(homedir(), '.pi/agent/install');
export const piPackage = process.env.PI_PACKAGE || join(managed, 'releases', readFileSync(join(managed, 'current-version'), 'utf8').trim(), 'node_modules/@earendil-works/pi-coding-agent');
export const wikiPackage = process.env.PI_WIKI_PACKAGE || join(homedir(), '.pi/agent/npm/node_modules/@zosmaai/pi-llm-wiki');
export const qmdPackage = process.env.QMD_PACKAGE || join(homedir(), '.pi/agent/npm/node_modules/@tobilu/qmd');
const require = createRequire(join(piPackage, 'package.json'));
export const jiti = require('jiti').createJiti(import.meta.url);
export const wikiLib = (name) => jiti.import(join(wikiPackage, 'extensions/llm-wiki/lib', `${name}.ts`));
export const sha256 = (text) => createHash('sha256').update(text).digest('hex');
export const version = (path) => JSON.parse(readFileSync(join(path, 'package.json'), 'utf8')).version;
mkdirSync(work, { recursive: true });
mkdirSync(results, { recursive: true });
// Prevent candidate fallback from touching the user's personal vault.
process.env.WIKI_HOME = join(work, 'isolated-personal');
