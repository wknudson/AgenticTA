#!/usr/bin/env node
/**
 * Runs uv with the given args, wherever uv is installed (see find-uv.mjs).
 *   node ../scripts/uv.mjs sync        (from agents/)
 */
import { spawnSync } from 'node:child_process';
import { findUv } from './find-uv.mjs';

const uv = findUv();
if (!uv) {
  console.error('\nuv is not installed. Install it with:  pip install uv   (or see https://docs.astral.sh/uv/)\n');
  process.exit(1);
}
const r = spawnSync(uv[0], [...uv.slice(1), ...process.argv.slice(2)], {
  stdio: 'inherit',
  shell: process.platform === 'win32',
});
process.exit(r.status ?? 1);
