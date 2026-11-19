#!/usr/bin/env node
/**
 * `npm run dev`: starts all three processes on Windows, macOS and Linux.
 *   web     Vite frontend          http://localhost:5173   (open this one)
 *   api     Express API            http://localhost:3001
 *   agents  Python agent service   http://localhost:8000/docs
 */
import concurrently from 'concurrently';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { findUv } from './find-uv.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const uv = findUv();
if (!uv) {
  console.error('\nuv is not installed. Run:  pip install uv   then  npm run setup\n');
  process.exit(1);
}
if (!existsSync(path.join(root, 'data', 'agenticta.sqlite'))) {
  console.error('\nNo database yet. Run:  npm run setup   (or  npm run db:init)\n');
  process.exit(1);
}

console.log('\n  AgenticTA  ->  open http://localhost:5173\n');

const { result } = concurrently(
  [
    { name: 'api', command: 'npm run dev:backend', cwd: root, prefixColor: 'blue' },
    { name: 'web', command: 'npm run dev:frontend', cwd: root, prefixColor: 'magenta' },
    {
      name: 'agents',
      command: [...uv, 'run', 'uvicorn', 'app.main:app', '--reload', '--port', '8000'].join(' '),
      cwd: path.join(root, 'agents'),
      prefixColor: 'green',
    },
  ],
  { killOthers: ['failure'], restartTries: 0 },
);

result.catch(() => process.exit(1));
