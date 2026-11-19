/**
 * Startup data checks (runs every time the API starts).
 *
 * The schema itself lives in schema.sql and is created by `npm run db:init`.
 * The old Postgres column-by-column migrations were dropped when the app moved
 * to SQLite: every database is now created fresh from schema.sql.
 */
import bcrypt from 'bcrypt';
import crypto from 'crypto';
import { db, query } from './connection.js';

function generatePassword(length = 10): string {
  // Avoid ambiguous chars (0/O, 1/I/l)
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
  const bytes = crypto.randomBytes(length);
  let out = '';
  for (let i = 0; i < length; i++) out += alphabet[bytes[i] % alphabet.length];
  return out;
}

// The bcrypt hash used by seed.sql for every seeded account.
const SEEDED_DEFAULT_PASSWORD_HASH = '$2b$12$8zdkLMBe8.oFbsRIl9ycp.uPg5u1NYIBCzdgtoqzgovrPis4vajai';

function tableExists(table: string): boolean {
  return !!db.prepare(`SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?`).get(table);
}

async function ensureDefaultAdmin(): Promise<void> {
  const { rows } = await query(`SELECT COUNT(*) AS c FROM admins WHERE username = 'admin'`);
  if (Number(rows[0]?.c ?? 0) === 0) {
    const hash = await bcrypt.hash('adminMetrics!', 12);
    await query('INSERT INTO admins (username, password_hash) VALUES ($1, $2) ON CONFLICT (username) DO NOTHING', [
      'admin',
      hash,
    ]);
    console.log('Startup: seeded default admin user (username: admin)');
  }
}

/**
 * Every student gets a random password plus a teacher-visible plaintext copy.
 * Existing plaintext rows are left alone so teacher edits persist.
 */
async function ensureStudentPasswords(): Promise<void> {
  const { rows } = await query(
    `SELECT s.student_id
     FROM students s
     LEFT JOIN student_passwords_plaintext sp ON sp.student_id = s.student_id
     WHERE sp.student_id IS NULL OR s.password_hash = $1
     ORDER BY s.student_id`,
    [SEEDED_DEFAULT_PASSWORD_HASH]
  );
  for (const row of rows) {
    const studentId = Number(row.student_id);
    if (!Number.isFinite(studentId) || studentId <= 0) continue;
    const password = generatePassword(10);
    const hash = await bcrypt.hash(password, 12);
    await query('UPDATE students SET password_hash = $1 WHERE student_id = $2', [hash, studentId]);
    await query(
      `INSERT INTO student_passwords_plaintext (student_id, password_plaintext)
       VALUES ($1, $2)
       ON CONFLICT (student_id)
       DO UPDATE SET password_plaintext = excluded.password_plaintext, updated_at = NOW()`,
      [studentId, password]
    );
  }
  if (rows.length > 0) console.log(`Startup: set random passwords for ${rows.length} student(s)`);
}

/** Every assignment should have a due date (the scheduler agent relies on it). */
async function backfillDueDates(): Promise<void> {
  const { rows } = await query(
    `UPDATE assignments
     SET due_date = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+7 days')
     WHERE due_date IS NULL
     RETURNING assignment_id`
  );
  if (rows.length > 0) console.log(`Startup: backfilled due_date for ${rows.length} assignment(s)`);
}

export async function runMigrations(): Promise<void> {
  if (!tableExists('students')) {
    throw new Error('Database is empty. Run `npm run db:init` first.');
  }
  await ensureDefaultAdmin();
  await ensureStudentPasswords();
  await backfillDueDates();
}
