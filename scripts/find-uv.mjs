/**
 * Finds a working uv command: `uv` on PATH, else `python -m uv`, `python3 -m uv`, `py -m uv`.
 * (pip installs uv into a user Scripts folder that often isn't on PATH on Windows.)
 */
import { spawnSync } from 'node:child_process';

const candidates = [['uv'], ['python', '-m', 'uv'], ['python3', '-m', 'uv'], ['py', '-m', 'uv']];

export function findUv() {
  for (const cmd of candidates) {
    const r = spawnSync(cmd[0], [...cmd.slice(1), '--version'], { stdio: 'ignore', shell: process.platform === 'win32' });
    if (r.status === 0) return cmd;
  }
  return null;
}
