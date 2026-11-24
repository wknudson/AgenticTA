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

/**
 * Columns added after schema.sql was first written (flipped classroom check-ins).
 * Fresh databases get them from schema.sql; this adds them to existing ones, so nobody
 * has to run db:reset (which would also wipe the Library). Keep in sync with
 * ADDED_COLUMNS in agents/app/shared/db.py, which adds the same columns when the agents
 * service starts first.
 */
const ADDED_COLUMNS: Record<string, Record<string, string>> = {
  assignments: {
    mode: "TEXT NOT NULL DEFAULT 'graded'",
    unit: 'TEXT',
    tutor_mode: "TEXT NOT NULL DEFAULT 'hints_only'",
    tutor_reveal_after: 'INTEGER NOT NULL DEFAULT 2',
    mastery_threshold: 'REAL NOT NULL DEFAULT 0.8',
    lesson_date: 'TEXT',
  },
  assignment_questions: { explain_rubric: 'TEXT' },
  student_chat_messages: { question_id: 'INTEGER' },
  student_grades: { practice_mastery: 'REAL', first_try_accuracy: 'REAL', fixed_with_help: 'REAL' },
  student_metrics: { practice_score: 'REAL', first_try_accuracy: 'REAL', fixed_with_help: 'REAL' },
};

function ensureColumns(): void {
  for (const [table, cols] of Object.entries(ADDED_COLUMNS)) {
    if (!tableExists(table)) continue;
    const have = new Set((db.prepare(`PRAGMA table_info(${table})`).all() as { name: string }[]).map((c) => c.name));
    for (const [name, ddl] of Object.entries(cols)) {
      if (!have.has(name)) {
        db.exec(`ALTER TABLE ${table} ADD COLUMN ${name} ${ddl}`);
        console.log(`Startup: added ${table}.${name}`);
      }
    }
  }
}

export async function runMigrations(): Promise<void> {
  if (!tableExists('students')) {
    throw new Error('Database is empty. Run `npm run db:init` first.');
  }
  ensureColumns();
  await ensureDefaultAdmin();
  await ensureStudentPasswords();
  await backfillDueDates();
}
