/**
 * Optional demo data: 6 extra students + 8 weeks of grades/metrics so the
 * metrics dashboards have something to show.  Run with `npm run db:seed-metrics`.
 *
 * Learning signals replace the old AI Dependency score (docs/flipped-classroom-plan.md section 6):
 *   practice = % of game items mastered, first try = % of check-in questions right the first time,
 *   fixed with help = % of misses the student fixed with the tutor,
 *   understanding = first try + half credit for misses fixed without the tutor explaining the answer.
 * ai_dependency_score is always written as NULL.
 */
import bcrypt from 'bcrypt';
import { query } from './connection.js';

const client = { query: <T = any>(text: string, params?: any[]) => query(text, params) as Promise<{ rows: T[] }> };

/** ISO-8601 week number (what Postgres EXTRACT(WEEK ...) returned). */
function isoWeek(d: Date): number {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
}

type MockStudent = {
  firstName: string;
  lastName: string;
  username: string;
  email: string;
  dateOfBirth: string;
  profile: Profile;
};

/**
 * steady:          knew most of it walking in, rarely needs the tutor
 * leans_on_tutor:  misses a lot on the first try, but works every miss out with the tutor
 * improving:       starts shaky and gets stronger week by week
 */
type Profile = 'steady' | 'leans_on_tutor' | 'improving';

type AssignmentRow = {
  assignment_id: number;
  class_id: number;
  max_points: number;
  mode: 'checkin' | 'graded';
};

type ExistingStudent = {
  student_id: number;
  username: string;
};

const SEED_TAG = 'metrics_seed_v1';

const MOCK_STUDENTS: MockStudent[] = [
  { firstName: 'Nora', lastName: 'Keller', username: 'nora_keller_mx', email: 'nora.keller.metrics@school.edu', dateOfBirth: '2006-02-11', profile: 'steady' },
  { firstName: 'Ethan', lastName: 'Brooks', username: 'ethan_brooks_mx', email: 'ethan.brooks.metrics@school.edu', dateOfBirth: '2006-06-03', profile: 'steady' },
  { firstName: 'Maya', lastName: 'Rios', username: 'maya_rios_mx', email: 'maya.rios.metrics@school.edu', dateOfBirth: '2006-04-19', profile: 'leans_on_tutor' },
  { firstName: 'Jordan', lastName: 'Price', username: 'jordan_price_mx', email: 'jordan.price.metrics@school.edu', dateOfBirth: '2005-12-08', profile: 'leans_on_tutor' },
  { firstName: 'Leah', lastName: 'Patel', username: 'leah_patel_mx', email: 'leah.patel.metrics@school.edu', dateOfBirth: '2006-09-22', profile: 'improving' },
  { firstName: 'Mateo', lastName: 'Diaz', username: 'mateo_diaz_mx', email: 'mateo.diaz.metrics@school.edu', dateOfBirth: '2006-01-27', profile: 'improving' },
];

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function toLetterGrade(percentage: number): string {
  if (percentage >= 93) return 'A';
  if (percentage >= 90) return 'A-';
  if (percentage >= 87) return 'B+';
  if (percentage >= 83) return 'B';
  if (percentage >= 80) return 'B-';
  if (percentage >= 77) return 'C+';
  if (percentage >= 73) return 'C';
  if (percentage >= 70) return 'C-';
  if (percentage >= 67) return 'D+';
  if (percentage >= 63) return 'D';
  if (percentage >= 60) return 'D-';
  return 'F';
}

function startOfWeek(d: Date): Date {
  const date = new Date(d);
  const day = date.getDay(); // 0=Sun
  const diff = (day + 6) % 7; // Monday-based
  date.setDate(date.getDate() - diff);
  date.setHours(0, 0, 0, 0);
  return date;
}

function addDays(d: Date, days: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + days);
  return out;
}

function fmtDate(d: Date): string {
  return d.toISOString();
}

const round1 = (n: number) => Math.round(n * 10) / 10;

type DemoSignals = {
  practice: number;           // % of game items mastered
  firstTry: number;           // % of check-in questions right the first time
  fixedWithHelp: number | null; // % of misses fixed with the tutor (null = nothing to fix)
  understanding: number;      // first try + half credit for misses fixed without the answer explained
  completion: number;         // % of check-in questions resolved (the check-in grade)
  legacyScore: number;        // score on a legacy graded assignment in the same week
};

/** Believable, deterministic learning signals for one student-week. weekIdx: 0 oldest ... 7 newest. */
function signalsForProfile(profile: Profile, weekIdx: number, slot: number): DemoSignals {
  const wobble = slot % 2 === 0 ? 2 : -2;
  const alt = weekIdx % 2 === 0 ? 1 : -1;
  let practice: number;
  let firstTry: number;
  let fixedWithHelp: number;
  let explainedShare: number; // share of fixes where the tutor had to explain the answer
  // Most students finish (every miss fixed = 100% fixed with help); the occasional unfinished
  // check-in is what a missed due date looks like.
  if (profile === 'steady') {
    practice = clamp(90 + weekIdx * 0.8 + wobble, 84, 100);
    firstTry = clamp(84 + weekIdx * 1.1 + wobble + alt, 78, 97);
    fixedWithHelp = (weekIdx + slot) % 5 === 4 ? 75 : 100;
    explainedShare = 0.1;
  } else if (profile === 'leans_on_tutor') {
    practice = clamp(74 + weekIdx * 1.3 + wobble, 62, 90);
    firstTry = clamp(55 + weekIdx * 1.6 + wobble + alt * 2, 46, 72);
    fixedWithHelp = (weekIdx + slot) % 4 === 1 ? 88 : 100;
    explainedShare = 0.5;
  } else {
    practice = clamp(46 + weekIdx * 6.6 + wobble, 40, 98);
    firstTry = clamp(42 + weekIdx * 5.8 + wobble, 36, 90);
    fixedWithHelp = clamp(56 + weekIdx * 9 + wobble, 45, 100);
    explainedShare = clamp(0.6 - weekIdx * 0.065, 0.15, 0.6);
  }
  const misses = 100 - firstTry;
  const fixedShare = fixedWithHelp / 100;
  const understanding = firstTry + 0.5 * misses * fixedShare * (1 - explainedShare);
  const completion = firstTry + misses * fixedShare;
  return {
    practice: round1(practice),
    firstTry: round1(firstTry),
    fixedWithHelp: misses > 0 ? round1(fixedWithHelp) : null,
    understanding: round1(understanding),
    completion: round1(clamp(completion, 0, 100)),
    legacyScore: round1(clamp(firstTry + 8 + alt, 0, 98)),
  };
}

function pickProfile(index: number): Profile {
  const pattern: Profile[] = ['steady', 'leans_on_tutor', 'improving'];
  return pattern[index % pattern.length];
}

function shouldEnrollInClass(studentId: number, classId: number): boolean {
  // Deterministic pseudo-random mix: ~60% enrollment chance.
  const value = (studentId * 31 + classId * 17) % 10;
  return value < 6;
}

async function main() {
  try {
    await client.query('BEGIN');

    // Step A: discover existing classes and assignments.
    const classRes = await client.query<{ class_id: number }>(
      `SELECT class_id FROM classes ORDER BY class_id ASC`
    );
    if (classRes.rows.length === 0) {
      throw new Error('No classes found. Cannot seed metrics without existing classes.');
    }
    const classIds = classRes.rows.map((r) => Number(r.class_id));

    const assignmentRes = await client.query<AssignmentRow>(
      `SELECT assignment_id, class_id, max_points, mode
       FROM assignments
       ORDER BY class_id ASC, assignment_id ASC`
    );
    const assignments: AssignmentRow[] = assignmentRes.rows.map((r) => ({
      assignment_id: Number(r.assignment_id),
      class_id: Number(r.class_id),
      max_points: Number(r.max_points),
      mode: r.mode === 'checkin' ? 'checkin' : 'graded',
    }));

    if (assignments.length === 0) {
      throw new Error('No assignments found. Cannot seed grades without existing assignments.');
    }
    const selectedAssignments = assignments;
    const assignmentsByClass = new Map<number, AssignmentRow[]>();
    for (const assignment of selectedAssignments) {
      const list = assignmentsByClass.get(assignment.class_id) ?? [];
      list.push(assignment);
      assignmentsByClass.set(assignment.class_id, list);
    }

    // Ensure each selected assignment has at least one question for response seeding.
    const selectedAssignmentIds = selectedAssignments.map((a) => a.assignment_id);
    const questionRes = await client.query<{ assignment_id: number; question_id: number }>(
      `SELECT assignment_id, MIN(question_id) AS question_id
       FROM assignment_questions
       WHERE assignment_id IN (SELECT value FROM json_each($1))
       GROUP BY assignment_id`,
      [selectedAssignmentIds]
    );
    const firstQuestionByAssignment = new Map<number, number>(
      questionRes.rows.map((r) => [Number(r.assignment_id), Number(r.question_id)])
    );

    // Step B: upsert mock students.
    const passwordHash = await bcrypt.hash('MockPass123!', 10);

    for (const s of MOCK_STUDENTS) {
      await client.query<{ student_id: number }>(
        `INSERT INTO students (first_name, last_name, email, username, password_hash, date_of_birth)
         VALUES ($1,$2,$3,$4,$5,$6)
         ON CONFLICT (username)
         DO UPDATE SET
           first_name = excluded.first_name,
           last_name = excluded.last_name,
           email = excluded.email,
           date_of_birth = excluded.date_of_birth
         RETURNING student_id`,
        [s.firstName, s.lastName, s.email, s.username, passwordHash, s.dateOfBirth]
      );
    }

    // Step C: include ALL students for full assignment + metric coverage.
    const allStudentsRes = await client.query<ExistingStudent>(
      `SELECT student_id, username
       FROM students
       ORDER BY student_id ASC`
    );
    const allStudents = allStudentsRes.rows.map((r) => ({
      student_id: Number(r.student_id),
      username: r.username,
    }));
    const studentIds = allStudents.map((s) => s.student_id);

    // Create a deterministic random enrollment mix so students are NOT in every class.
    // Also guarantee each student has at least one class and each class has at least one student.
    const studentToClassSet = new Map<number, Set<number>>();
    const classToStudentCount = new Map<number, number>(classIds.map((id) => [id, 0]));
    for (const studentId of studentIds) {
      const set = new Set<number>();
      for (const classId of classIds) {
        if (shouldEnrollInClass(studentId, classId)) set.add(classId);
      }
      if (set.size === 0) {
        const fallbackClass = classIds[studentId % classIds.length];
        set.add(fallbackClass);
      }
      studentToClassSet.set(studentId, set);
      for (const classId of set) classToStudentCount.set(classId, (classToStudentCount.get(classId) ?? 0) + 1);
    }
    for (const classId of classIds) {
      if ((classToStudentCount.get(classId) ?? 0) > 0) continue;
      const fallbackStudentId = studentIds[classId % studentIds.length];
      studentToClassSet.get(fallbackStudentId)?.add(classId);
      classToStudentCount.set(classId, 1);
    }

    for (const studentId of studentIds) {
      const enrolledClassSet = studentToClassSet.get(studentId) ?? new Set<number>();
      for (const classId of classIds) {
        const status = enrolledClassSet.has(classId) ? 'active' : 'inactive';
        await client.query(
          `INSERT INTO student_classes (student_id, class_id, enrollment_date, status)
           VALUES ($1, $2, date('now'), $3)
           ON CONFLICT (student_id, class_id)
           DO UPDATE SET status = excluded.status`,
          [studentId, classId, status]
        );
      }
    }

    // Idempotency cleanup for this seed set only.
    await client.query(
      `DELETE FROM ai_usage_logs
       WHERE json_extract(details, '$.seed_tag') = $1`,
      [SEED_TAG]
    );

    // Also remove previously seeded response rows for these students + selected assignments.
    await client.query(
      `DELETE FROM student_assignment_responses
       WHERE student_id IN (SELECT value FROM json_each($1))
         AND assignment_id IN (SELECT value FROM json_each($2))`,
      [studentIds, selectedAssignmentIds]
    );

    // Step D: seed 8 weeks of submissions + grade rows across all assignments.
    const currentWeekStart = startOfWeek(new Date());
    const weekStarts = Array.from({ length: 8 }, (_, i) => addDays(currentWeekStart, -(7 * (7 - i))));

    for (let i = 0; i < allStudents.length; i++) {
      const studentId = allStudents[i].student_id;
      const profile = pickProfile(i);
      const enrolledClassSet = studentToClassSet.get(studentId) ?? new Set<number>();
      const studentAssignments = selectedAssignments.filter((a) => enrolledClassSet.has(a.class_id));

      for (let assignmentIdx = 0; assignmentIdx < studentAssignments.length; assignmentIdx++) {
        const assignment = studentAssignments[assignmentIdx];
        const weekIdx = assignmentIdx % 8;
        const slot = Math.floor(assignmentIdx / 8);
        const weekStart = weekStarts[weekIdx];
        const sig = signalsForProfile(profile, weekIdx, slot);
        const isCheckin = assignment.mode === 'checkin';
        // Check-ins are graded on completion; legacy graded work keeps a score and has no signals.
        const percentage = isCheckin ? sig.completion : sig.legacyScore;
        const letterGrade = isCheckin ? (percentage >= 100 ? 'Complete' : 'Incomplete') : toLetterGrade(percentage);
        const pointsEarned = Number(((assignment.max_points * percentage) / 100).toFixed(2));
        const dayOffset = (assignmentIdx % 5) + 1; // spread across weekdays
        const submissionDate = addDays(weekStart, dayOffset);
        submissionDate.setHours(15, 30, 0, 0);
        const gradedDate = isCheckin ? new Date(submissionDate) : addDays(submissionDate, 1);
        if (!isCheckin) gradedDate.setHours(9, 0, 0, 0);

        await client.query(
            `INSERT INTO student_grades (
               student_id,
               assignment_id,
               points_earned,
               percentage,
               letter_grade,
               submission_date,
               graded_date,
               understanding_score,
               ai_dependency_score,
               engagement_score,
               submission_attempts,
               practice_mastery,
               first_try_accuracy,
               fixed_with_help
             ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NULL,$9,$10,$11,$12,$13)
             ON CONFLICT (student_id, assignment_id)
             DO UPDATE SET
               points_earned = excluded.points_earned,
               percentage = excluded.percentage,
               letter_grade = excluded.letter_grade,
               submission_date = excluded.submission_date,
               graded_date = excluded.graded_date,
               understanding_score = excluded.understanding_score,
               ai_dependency_score = NULL,
               engagement_score = excluded.engagement_score,
               submission_attempts = excluded.submission_attempts,
               practice_mastery = excluded.practice_mastery,
               first_try_accuracy = excluded.first_try_accuracy,
               fixed_with_help = excluded.fixed_with_help`,
            [
              studentId,
              assignment.assignment_id,
              pointsEarned,
              percentage,
              letterGrade,
              fmtDate(submissionDate),
              fmtDate(gradedDate),
              sig.understanding,
              isCheckin ? sig.practice : percentage, // engagement: practice mastery on check-ins
              1,
              isCheckin ? sig.practice : null,
              isCheckin ? sig.firstTry : null,
              isCheckin ? sig.fixedWithHelp : null,
            ]
          );

        // Check-ins keep their answers in checkin_item_status, not the legacy responses table.
        const firstQuestionId = isCheckin ? undefined : firstQuestionByAssignment.get(assignment.assignment_id);
        if (firstQuestionId) {
          await client.query(
              `INSERT INTO student_assignment_responses (
                 student_id,
                 assignment_id,
                 question_id,
                 attempt_number,
                 response_text,
                 selected_option_ids,
                 is_correct,
                 submitted_at
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
              [
                studentId,
                assignment.assignment_id,
                firstQuestionId,
                1,
                `Seeded mock response for ${allStudents[i].username}`,
                null,
                percentage >= 70 ? 1 : 0,
                fmtDate(submissionDate),
              ]
            );
        }

        // Seed tutor-chat usage logs: roughly one chat per missed question worked out with the tutor.
        const approxChatCount = Math.max(1, Math.round((100 - sig.firstTry) / 10));
        for (let c = 0; c < approxChatCount; c++) {
          const logTime = new Date(submissionDate);
          logTime.setMinutes(logTime.getMinutes() - (c + 1) * 12);
          await client.query(
              `INSERT INTO ai_usage_logs (student_id, action, timestamp, details)
               VALUES ($1, 'chat', $2, $3)`,
              [
                studentId,
                fmtDate(logTime),
                JSON.stringify({
                  seed_tag: SEED_TAG,
                  assignment_id: assignment.assignment_id,
                  week_index: weekIdx,
                  profile,
                }),
              ]
          );
        }
      }
    }

    // Step E: weekly rollup upsert into student_metrics for past 8 weeks. Same formula as
    // upsertWeeklyMetrics (backend/routes/student.ts). Demo weeks always get learning signals:
    // from real check-in grades when the week has them, otherwise from the student's profile,
    // so the dashboards have something to show before any check-in exists.
    for (let i = 0; i < studentIds.length; i++) {
      const studentId = studentIds[i];
      const profile = pickProfile(i);
      const enrolledClassIds = Array.from(studentToClassSet.get(studentId) ?? []);
      for (let weekIdx = 0; weekIdx < 8; weekIdx++) {
        const weekStart = weekStarts[weekIdx];
        const weekEnd = addDays(weekStart, 6);
        const weekNumber = isoWeek(weekStart);

        // roll up per class for this student/week (as required by student_metrics PK).
        for (const classId of enrolledClassIds) {
          const aggRes = await client.query<{
            accuracy_score: number | null;
            understanding_score: number | null;
            engagement_score: number | null;
            practice_score: number | null;
            first_try_accuracy: number | null;
            fixed_with_help: number | null;
            checkins: number | null;
          }>(
            `SELECT
               SUM(CASE WHEN sg.practice_mastery IS NOT NULL THEN 1 ELSE 0 END) AS checkins,
               AVG(COALESCE(sg.first_try_accuracy, sg.percentage)) AS accuracy_score,
               AVG(COALESCE(sg.understanding_score, sg.percentage)) AS understanding_score,
               AVG(COALESCE(sg.engagement_score, sg.percentage)) AS engagement_score,
               AVG(sg.practice_mastery) AS practice_score,
               AVG(sg.first_try_accuracy) AS first_try_accuracy,
               AVG(sg.fixed_with_help) AS fixed_with_help
             FROM student_grades sg
             JOIN assignments a ON a.assignment_id = sg.assignment_id
             WHERE sg.student_id = $1
               AND a.class_id = $2
               AND sg.submission_date >= $3
               AND sg.submission_date < $4`,
            [studentId, classId, fmtDate(weekStart), fmtDate(addDays(weekStart, 7))]
          );
          const agg = aggRes.rows[0];

          // Guarantee all students/classes have all 8 weekly metric points, even if a class had no submissions that week.
          const fallback = signalsForProfile(profile, weekIdx, 0);
          const pick = (v: number | null, fb: number | null) => (v != null ? round1(Number(v)) : fb);
          const hadCheckins = Number(agg.checkins ?? 0) > 0;
          // With real check-ins that week, a NULL fixed_with_help means "nothing to fix": keep it.
          const signal = (v: number | null, fb: number | null) => (hadCheckins ? pick(v, null) : fb);
          const practice = signal(agg.practice_score, fallback.practice);
          const firstTry = signal(agg.first_try_accuracy, fallback.firstTry);
          const fixedWithHelp = signal(agg.fixed_with_help, fallback.fixedWithHelp);
          const accuracy = pick(agg.accuracy_score, fallback.firstTry);
          const understanding = pick(agg.understanding_score, fallback.understanding);
          const engagement = pick(agg.engagement_score, fallback.practice);

          await client.query(
            `INSERT INTO student_metrics (
               student_id,
               class_id,
               week_number,
               week_start_date,
               week_end_date,
               accuracy_score,
               ai_dependency_score,
               understanding_score,
               engagement_score,
               notes,
               practice_score,
               first_try_accuracy,
               fixed_with_help
             ) VALUES ($1,$2,$3,$4,$5,$6,NULL,$7,$8,$9,$10,$11,$12)
             ON CONFLICT (student_id, class_id, week_number)
             DO UPDATE SET
               week_start_date = excluded.week_start_date,
               week_end_date = excluded.week_end_date,
               accuracy_score = excluded.accuracy_score,
               ai_dependency_score = NULL,
               understanding_score = excluded.understanding_score,
               engagement_score = excluded.engagement_score,
               notes = excluded.notes,
               practice_score = excluded.practice_score,
               first_try_accuracy = excluded.first_try_accuracy,
               fixed_with_help = excluded.fixed_with_help`,
            [
              studentId,
              classId,
              weekNumber,
              weekStart.toISOString().slice(0, 10),
              weekEnd.toISOString().slice(0, 10),
              accuracy,
              understanding,
              engagement,
              `Seeded by ${SEED_TAG}`,
              practice,
              firstTry,
              fixedWithHelp,
            ]
          );
        }
      }
    }

    await client.query('COMMIT');
    console.log(`✅ Seed complete (${SEED_TAG})`);
    console.log(`Created/updated ${MOCK_STUDENTS.length} mock students with randomized class enrollments and seeded 8 weeks of metrics.`);
  } catch (err) {
    await client.query('ROLLBACK');
    console.error('❌ Seed failed:', err);
    process.exitCode = 1;
  }
}

main();
