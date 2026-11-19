/**
 * SQLite connection shared by the Express API.
 *
 * The Python agents service opens the SAME file (see agents/app/shared/db.py),
 * so WAL mode is enabled to let both processes read while one writes.
 *
 * `query(text, params)` keeps the old Postgres-style call signature so the
 * route code barely changed:
 *   - `$1, $2 ...` placeholders are rewritten to named `@p1, @p2 ...`
 *     (named, so a placeholder can be reused in one statement like in Postgres)
 *   - booleans -> 1/0, Date -> ISO string, arrays/objects -> JSON text
 *     (array params are read in SQL with `IN (SELECT value FROM json_each($1))`)
 *   - returns `{ rows }` for SELECT / RETURNING statements, `{ rows: [], changes }` otherwise
 */
import Database from 'better-sqlite3';
import dotenv from 'dotenv';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.join(__dirname, '..', '..');

dotenv.config({ path: path.join(repoRoot, '.env') });

/** Absolute path of the shared SQLite file (default: <repo>/data/agenticta.sqlite). */
export const DB_PATH = path.resolve(repoRoot, process.env.SQLITE_DB_PATH || 'data/agenticta.sqlite');

fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });

export const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');
db.pragma('busy_timeout = 5000');

/** Timestamps are stored as ISO-8601 UTC text, e.g. 2026-11-19T21:02:17.123Z */
export const nowIso = () => new Date().toISOString();

// Postgres functions the route SQL still uses.
db.function('NOW', () => nowIso());
db.function('GREATEST', { varargs: true }, (...args: unknown[]) => {
  const vals = args.filter((a) => a !== null && a !== undefined) as (number | string)[];
  return vals.length ? vals.reduce((a, b) => (b > a ? b : a)) : null;
});
db.function('LEAST', { varargs: true }, (...args: unknown[]) => {
  const vals = args.filter((a) => a !== null && a !== undefined) as (number | string)[];
  return vals.length ? vals.reduce((a, b) => (b < a ? b : a)) : null;
});

function toSqliteParam(v: unknown): unknown {
  if (v === undefined) return null;
  if (typeof v === 'boolean') return v ? 1 : 0;
  if (v instanceof Date) return v.toISOString();
  if (Array.isArray(v) || (v !== null && typeof v === 'object' && !Buffer.isBuffer(v))) {
    return JSON.stringify(v);
  }
  return v;
}

/** `$1` -> `@p1` (named, so one placeholder can appear several times, like in Postgres). */
function toSqliteSql(text: string): string {
  return text.replace(/\$(\d+)/g, '@p$1');
}

export async function query(text: string, params: any[] = []): Promise<{ rows: any[]; changes?: number }> {
  const stmt = db.prepare(toSqliteSql(text));
  const bound: Record<string, unknown> = {};
  params.forEach((v, i) => {
    bound[`p${i + 1}`] = toSqliteParam(v);
  });
  const args = params.length ? [bound] : [];
  if (stmt.reader) {
    return { rows: stmt.all(...args) as any[] };
  }
  const info = stmt.run(...args);
  return { rows: [], changes: info.changes };
}

export default { query };
