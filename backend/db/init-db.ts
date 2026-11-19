/**
 * Creates the shared SQLite database from schema.sql + seed.sql.
 *
 *   npm run db:init           create the DB if it doesn't exist yet
 *   npm run db:reset          delete the DB file and recreate it (also wipes agent tables)
 *
 * The Python agents service creates its own tables in the same file on startup.
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function main() {
  const reset = process.argv.includes('--reset') || process.env.RESET_DB === 'true' || process.env.RESET_DB === '1';

  // Resolve the path the same way connection.ts does, before opening it.
  const { default: dotenv } = await import('dotenv');
  dotenv.config({ path: path.join(__dirname, '..', '..', '.env') });
  const dbPath = path.resolve(__dirname, '..', '..', process.env.SQLITE_DB_PATH || 'data/agenticta.sqlite');

  if (reset) {
    // App DB + the agents' LangGraph checkpoints + uploaded library files.
    const checkpointPath = path.join(path.dirname(dbPath), 'checkpoints.sqlite');
    for (const file of [dbPath, checkpointPath]) {
      for (const suffix of ['', '-wal', '-shm']) {
        if (fs.existsSync(file + suffix)) fs.rmSync(file + suffix);
      }
    }
    const filesDir = path.join(path.dirname(dbPath), 'files');
    if (fs.existsSync(filesDir)) fs.rmSync(filesDir, { recursive: true });
    console.log(`Reset: deleted ${dbPath}, agent checkpoints and uploaded files`);
  }

  const { db } = await import('./connection.js');

  const hasStudents = db.prepare(`SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'students'`).get();
  if (hasStudents) {
    console.log(`SQLite DB already initialized at ${dbPath}`);
    return;
  }

  console.log('Creating schema...');
  db.exec(fs.readFileSync(path.join(__dirname, 'schema.sql'), 'utf-8'));
  console.log('Seeding demo data...');
  db.exec(fs.readFileSync(path.join(__dirname, 'seed.sql'), 'utf-8'));

  const { runMigrations } = await import('./migrate.js');
  await runMigrations();

  console.log(`SQLite database initialized at ${dbPath}`);
}

main().catch((err) => {
  console.error('DB init error', err);
  process.exit(1);
});
