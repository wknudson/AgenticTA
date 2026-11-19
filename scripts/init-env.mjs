#!/usr/bin/env node
/**
 * `npm run env`: creates any missing .env file from its .env.example, then shows which keys
 * are still blank.  Never overwrites an existing .env and never prints key values.
 *
 *   .env                                 project-wide (LangSmith, app, Express AI key)
 *   agents/app/agents/<agent>/.env       one per agent (that agent's model keys)
 */
import { copyFileSync, existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const agentsDir = path.join(root, 'agents', 'app', 'agents');

const targets = [{ label: 'project', dir: root }];
for (const name of readdirSync(agentsDir, { withFileTypes: true })) {
  if (name.isDirectory() && existsSync(path.join(agentsDir, name.name, '.env.example'))) {
    targets.push({ label: `agent: ${name.name}`, dir: path.join(agentsDir, name.name) });
  }
}

const parse = (file) =>
  Object.fromEntries(
    readFileSync(file, 'utf8')
      .split(/\r?\n/)
      .filter((l) => /^[A-Z0-9_]+=/.test(l))
      .map((l) => {
        const i = l.indexOf('=');
        return [l.slice(0, i), l.slice(i + 1).trim()];
      }),
  );

const projectEnv = existsSync(path.join(root, '.env')) ? parse(path.join(root, '.env')) : {};

console.log('');
for (const t of targets) {
  const example = path.join(t.dir, '.env.example');
  const env = path.join(t.dir, '.env');
  let created = false;
  if (!existsSync(env)) {
    copyFileSync(example, env);
    created = true;
  }
  const values = parse(env);
  const keys = Object.keys(values).filter((k) => k.endsWith('_API_KEY'));
  const status = keys.map((k) => {
    if (values[k]) return `${k} set`;
    if (t.label !== 'project' && projectEnv[k]) return `${k} (from project .env)`;
    return `${k} MISSING`;
  });
  const rel = path.relative(root, env) || '.env';
  console.log(`${created ? 'created ' : '        '} ${rel.padEnd(42)} ${status.join(', ') || 'no keys needed'}`);
}
console.log('\nMissing keys only matter for real runs; every agent has an offline demo that needs none.\n');
