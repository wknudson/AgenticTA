import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchClassMetricStudents,
  fetchStudentMetricHistory,
  fetchClassMetricAverages,
  type ClassMetricStudentSummary,
  type StudentMetricHistoryPoint,
  type ClassMetricWeekAverage,
  type ClassMetricAveragesPayload,
} from '../services/api';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import {
  SIGNAL_KEYS,
  SIGNAL_META,
  LearningSignalsExplainer,
  fmtSignal,
  signalValue,
  type SignalKey,
} from './learningSignals';
import { STAGE_LABEL, STAGE_STYLE, formatDay } from './checkin/format';
import { getStudentCheckins, type StudentCheckinRow } from '../services/classOverviewApi';

interface TeacherMetricsProps {
  classId: number;
  /** When set, metrics are loaded via authenticated admin API */
  adminToken?: string;
  /** Teacher dashboard: open the Insights briefing on one check-in. When set (and not admin),
   *  a student's detail lists their check-ins with links to the briefing behind the numbers. */
  onOpenCheckin?: (assignmentId: number) => void;
}

/** Shown while every signal is a dash (no check-in work yet). */
const SignalsEmptyNote: React.FC = () => (
  <p className="rounded-xl border border-dashed border-gray-300 bg-white px-4 py-3 text-sm text-gray-600">
    Learning signals appear after students do their first unit check-in. Each number is a weekly average, so a
    dash (—) means no check-in work yet.
  </p>
);

const allSignalsEmpty = (rows: Array<Parameters<typeof signalValue>[0]>) =>
  rows.every((row) => SIGNAL_KEYS.every((key) => signalValue(row, key) == null));

type MetricKey = SignalKey;
type MetricsLevel = 'student_list' | 'student_detail';
type SortField = 'name' | MetricKey;
type SortDirection = 'asc' | 'desc';

function fmtWeekRange(start: string, end: string): string {
  if (!start?.trim() && !end?.trim()) return '';
  try {
    const s = new Date(start);
    const e = new Date(end);
    if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) return '';
    return `${s.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} – ${e.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`;
  } catch {
    return '';
  }
}

const MetricPills: React.FC<{ selected: MetricKey; onSelect: (m: MetricKey) => void }> = ({ selected, onSelect }) => (
  <div className="flex flex-wrap gap-2 mb-3">
    {SIGNAL_KEYS.map((metric) => (
      <button
        key={metric}
        type="button"
        onClick={() => onSelect(metric)}
        title={SIGNAL_META[metric].help}
        className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
          selected === metric ? 'bg-black text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
        }`}
      >
        {SIGNAL_META[metric].label}
      </button>
    ))}
  </div>
);

const SignalLineChart: React.FC<{ data: Array<{ weekLabel: string; value: number | null }>; metric: MetricKey }> = ({
  data,
  metric,
}) => (
  <ResponsiveContainer width="100%" height="100%">
    <LineChart data={data}>
      <CartesianGrid stroke="#e5e7eb" />
      <XAxis dataKey="weekLabel" tick={{ fontSize: 11 }} />
      <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
      <Tooltip formatter={(value: number | null) => [fmtSignal(value), SIGNAL_META[metric].label]} />
      <Line
        type="monotone"
        dataKey="value"
        stroke={SIGNAL_META[metric].color}
        strokeWidth={3}
        dot={{ r: 4, fill: SIGNAL_META[metric].color }}
        connectNulls
      />
    </LineChart>
  </ResponsiveContainer>
);

const TeacherMetrics: React.FC<TeacherMetricsProps> = ({ classId, adminToken, onOpenCheckin }) => {
  const STUDENTS_PER_PAGE = 8;
  const [level, setLevel] = useState<MetricsLevel>('student_list');
  const [students, setStudents] = useState<ClassMetricStudentSummary[]>([]);
  const [selectedStudent, setSelectedStudent] = useState<ClassMetricStudentSummary | null>(null);
  const [selectedMetric, setSelectedMetric] = useState<MetricKey>('understanding');
  const [showLearnMore, setShowLearnMore] = useState(false);
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const [studentSearch, setStudentSearch] = useState('');
  const [studentPage, setStudentPage] = useState(1);
  const [history, setHistory] = useState<StudentMetricHistoryPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showClassAveragesModal, setShowClassAveragesModal] = useState(false);
  const [classAvgLoading, setClassAvgLoading] = useState(false);
  const [classAvgError, setClassAvgError] = useState<string | null>(null);
  const [classAvgWeekly, setClassAvgWeekly] = useState<ClassMetricWeekAverage[]>([]);
  const [classAvgCurrent, setClassAvgCurrent] = useState<ClassMetricAveragesPayload['currentAverages']>(null);
  const [classAvgWeekMeta, setClassAvgWeekMeta] = useState<ClassMetricAveragesPayload['currentWeek']>(null);
  const [classAvgSelectedMetric, setClassAvgSelectedMetric] = useState<MetricKey>('understanding');

  const metricFetchOpts = useMemo(
    () => (adminToken ? { adminToken } : undefined),
    [adminToken]
  );

  // A student's check-ins (teacher dashboard only), with links to each briefing.
  const canOpenCheckins = !!onOpenCheckin && !adminToken;
  const [studentCheckins, setStudentCheckins] = useState<StudentCheckinRow[] | null>(null);
  const [checkinsError, setCheckinsError] = useState<string | null>(null);
  const detailStudentId = level === 'student_detail' ? selectedStudent?.studentId ?? null : null;
  useEffect(() => {
    setStudentCheckins(null);
    setCheckinsError(null);
    if (!canOpenCheckins || detailStudentId == null) return;
    const controller = new AbortController();
    getStudentCheckins(classId, detailStudentId, controller.signal)
      .then((r) => setStudentCheckins(r.checkins))
      .catch((err) => {
        if (!controller.signal.aborted) setCheckinsError(err instanceof Error ? err.message : String(err));
      });
    return () => controller.abort();
  }, [classId, detailStudentId, canOpenCheckins]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchClassMetricStudents(classId, metricFetchOpts)
      .then((data) => {
        if (!cancelled) setStudents(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load metrics.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [classId, metricFetchOpts]);

  const selectedStudentName = useMemo(() => {
    if (!selectedStudent) return '';
    return `${selectedStudent.firstName} ${selectedStudent.lastName}`;
  }, [selectedStudent]);

  const sortedStudents = useMemo(() => {
    const getNumericMetric = (s: ClassMetricStudentSummary, metric: MetricKey): number => {
      const val = signalValue(s.currentWeek, metric);
      // Put missing values at the end in asc and start in desc by mapping to +/-infinity.
      if (val == null) return sortDirection === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY;
      return val;
    };

    const search = studentSearch.trim().toLowerCase();
    const filtered = !search
      ? students
      : students.filter((s) => {
          const fullName = `${s.firstName} ${s.lastName}`.toLowerCase();
          return fullName.includes(search) || s.username.toLowerCase().includes(search);
        });

    return [...filtered].sort((a, b) => {
      if (sortField === 'name') {
        const aName = `${a.lastName}, ${a.firstName}`.toLowerCase();
        const bName = `${b.lastName}, ${b.firstName}`.toLowerCase();
        const cmp = aName.localeCompare(bName);
        return sortDirection === 'asc' ? cmp : -cmp;
      }
      const aVal = getNumericMetric(a, sortField);
      const bVal = getNumericMetric(b, sortField);
      if (aVal === bVal) return 0;
      return sortDirection === 'asc' ? (aVal < bVal ? -1 : 1) : aVal > bVal ? -1 : 1;
    });
  }, [students, sortField, sortDirection, studentSearch]);

  const totalStudentPages = Math.max(1, Math.ceil(sortedStudents.length / STUDENTS_PER_PAGE));

  const paginatedStudents = useMemo(() => {
    const start = (studentPage - 1) * STUDENTS_PER_PAGE;
    return sortedStudents.slice(start, start + STUDENTS_PER_PAGE);
  }, [sortedStudents, studentPage]);

  useEffect(() => {
    setStudentPage(1);
  }, [classId, sortField, sortDirection, studentSearch]);

  useEffect(() => {
    if (studentPage > totalStudentPages) {
      setStudentPage(totalStudentPages);
    }
  }, [studentPage, totalStudentPages]);

  const openStudentDetail = async (student: ClassMetricStudentSummary) => {
    setSelectedStudent(student);
    setLevel('student_detail');
    setLoading(true);
    setError(null);
    try {
      const data = await fetchStudentMetricHistory(classId, student.studentId, metricFetchOpts);
      setHistory(data.history);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load student metrics.');
      setHistory([]);
    } finally {
      setLoading(false);
    }
  };

  const chartData = useMemo(() => {
    const recentHistory = history.slice(-8);
    return recentHistory.map((h, index) => ({
      weekLabel: `Week ${index + 1}`,
      value: signalValue(h, selectedMetric),
    }));
  }, [history, selectedMetric]);

  const lastThreeWeekAverages = useMemo(() => {
    const recent = history.slice(-3);
    const avg = (values: Array<number | null>) => {
      const nums = values.filter((v): v is number => v != null);
      if (nums.length === 0) return null;
      return nums.reduce((sum, n) => sum + n, 0) / nums.length;
    };
    const out = {} as Record<MetricKey, number | null>;
    for (const key of SIGNAL_KEYS) out[key] = avg(recent.map((h) => signalValue(h, key)));
    return out;
  }, [history]);

  const classAvgChartData = useMemo(() => {
    return classAvgWeekly.map((h, index) => ({
      weekLabel: `Week ${index + 1}`,
      value: signalValue(h, classAvgSelectedMetric),
    }));
  }, [classAvgWeekly, classAvgSelectedMetric]);

  const openClassAveragesModal = useCallback(async () => {
    setShowClassAveragesModal(true);
    setClassAvgLoading(true);
    setClassAvgError(null);
    try {
      const data = await fetchClassMetricAverages(classId, metricFetchOpts);
      setClassAvgWeekly(data.weekly);
      setClassAvgCurrent(data.currentAverages);
      setClassAvgWeekMeta(data.currentWeek);
    } catch (err) {
      setClassAvgError(err instanceof Error ? err.message : 'Failed to load class averages.');
      setClassAvgWeekly([]);
      setClassAvgCurrent(null);
      setClassAvgWeekMeta(null);
    } finally {
      setClassAvgLoading(false);
    }
  }, [classId, metricFetchOpts]);

  const learnMoreModal = showLearnMore ? (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={() => setShowLearnMore(false)}
    >
      <div
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-white rounded-2xl shadow-xl border border-gray-100 p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-xl font-bold text-black">How metrics work</h3>
            <p className="text-sm text-gray-600 mt-1">
              Students practice with games, then do a check-in where using the tutor is encouraged. These numbers
              show what they knew, where they needed help, and whether they got there. Each is a weekly average.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowLearnMore(false)}
            className="text-gray-500 hover:text-gray-700"
            aria-label="Close"
          >
            x
          </button>
        </div>
        <LearningSignalsExplainer />
      </div>
    </div>
  ) : null;

  const classAveragesModal = showClassAveragesModal ? (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={() => setShowClassAveragesModal(false)}
    >
      <div
        className="w-full max-w-4xl max-h-[90vh] overflow-y-auto bg-white rounded-2xl shadow-xl border border-gray-100 p-4 sm:p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-xl font-bold text-black">Class averages</h3>
            <p className="text-sm text-gray-600 mt-1">
              Average of each signal across enrolled students, by week (up to 8 most recent weeks).
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowClassAveragesModal(false)}
            className="text-gray-500 hover:text-gray-700 shrink-0"
            aria-label="Close"
          >
            x
          </button>
        </div>

        {classAvgLoading ? (
          <div className="flex items-center justify-center py-16">
            <div className="w-8 h-8 border-4 border-gray-200 border-t-[#ba3638] rounded-full animate-spin" />
          </div>
        ) : classAvgError ? (
          <p className="text-red-600 text-sm">{classAvgError}</p>
        ) : classAvgWeekly.length === 0 ? (
          <p className="text-gray-600 text-sm">
            No weekly numbers yet. They show up once students start working through check-ins.
          </p>
        ) : (
          <>
            {classAvgCurrent && classAvgWeekMeta && (
              <div className="rounded-xl border border-gray-200 bg-gray-50/80 p-4 space-y-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Latest week (class average)</p>
                  <p className="text-sm text-gray-700">
                    {fmtWeekRange(classAvgWeekMeta.weekStartDate, classAvgWeekMeta.weekEndDate) || `Week ${classAvgWeekMeta.weekNumber}`}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {SIGNAL_KEYS.map((key) => (
                    <span
                      key={key}
                      title={SIGNAL_META[key].help}
                      className={`px-3 py-1.5 rounded-full text-sm font-medium ${SIGNAL_META[key].badge}`}
                    >
                      {SIGNAL_META[key].label} {fmtSignal(signalValue(classAvgCurrent, key))}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <MetricPills selected={classAvgSelectedMetric} onSelect={setClassAvgSelectedMetric} />
              <h4 className="text-lg font-semibold text-center text-black mb-1">
                Class average: {SIGNAL_META[classAvgSelectedMetric].label} over time
              </h4>
              <p className="text-xs text-gray-500 text-center mb-2 max-w-xl mx-auto">
                {SIGNAL_META[classAvgSelectedMetric].help}
              </p>
              <div className="h-[260px] sm:h-[280px] w-full">
                <SignalLineChart data={classAvgChartData} metric={classAvgSelectedMetric} />
              </div>
            </div>

            <div className="rounded-xl border border-gray-200 overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="p-2 font-semibold text-gray-700">Week</th>
                    <th className="p-2 font-semibold text-gray-700">Dates</th>
                    {SIGNAL_KEYS.map((key) => (
                      <th key={key} className="p-2 font-semibold whitespace-nowrap" style={{ color: SIGNAL_META[key].color }}>
                        {SIGNAL_META[key].short}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {classAvgWeekly.map((w) => (
                    <tr key={`${w.weekStartDate}-${w.weekNumber}`} className="border-b border-gray-100">
                      <td className="p-2 text-gray-800">{w.weekNumber}</td>
                      <td className="p-2 text-gray-600 whitespace-nowrap">
                        {fmtWeekRange(w.weekStartDate, w.weekEndDate) || '—'}
                      </td>
                      {SIGNAL_KEYS.map((key) => (
                        <td key={key} className="p-2">{fmtSignal(signalValue(w, key))}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  ) : null;

  if (loading && level === 'student_list') {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-4 border-gray-200 border-t-[#ba3638] rounded-full animate-spin" />
      </div>
    );
  }

  if (error && level === 'student_list') {
    return <p className="text-red-500 text-center py-10">{error}</p>;
  }

  if (level === 'student_list') {
    return (
      <>
        <div className="space-y-6 animate-fadeIn">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-4xl font-bold text-black">Metrics</h2>
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="text"
                value={studentSearch}
                onChange={(e) => setStudentSearch(e.target.value)}
                placeholder="Search for student..."
                className="px-3 py-2 rounded-lg border border-gray-300 bg-white text-sm text-gray-700"
              />
              <select
                value={sortField}
                onChange={(e) => setSortField(e.target.value as SortField)}
                className="px-3 py-2 rounded-lg border border-gray-300 bg-white text-sm font-medium text-gray-700"
                title="Sort by"
              >
                <option value="name">Sort: Name</option>
                {SIGNAL_KEYS.map((key) => (
                  <option key={key} value={key}>
                    Sort: {SIGNAL_META[key].label}
                  </option>
                ))}
              </select>
              <select
                value={sortDirection}
                onChange={(e) => setSortDirection(e.target.value as SortDirection)}
                className="px-3 py-2 rounded-lg border border-gray-300 bg-white text-sm font-medium text-gray-700"
                title="Sort direction"
              >
                {sortField === 'name' ? (
                  <>
                    <option value="asc">A to Z</option>
                    <option value="desc">Z to A</option>
                  </>
                ) : (
                  <>
                    <option value="asc">Lowest first</option>
                    <option value="desc">Highest first</option>
                  </>
                )}
              </select>
              <button
                type="button"
                onClick={() => setShowLearnMore(true)}
                className="px-3 py-2 rounded-lg border border-slate-300 bg-slate-100 text-sm font-medium text-slate-700 hover:text-slate-900 hover:bg-slate-100 active:bg-slate-100"
              >
                Learn more about metrics
              </button>
              <button
                type="button"
                onClick={() => void openClassAveragesModal()}
                className="px-3 py-2 rounded-lg border border-gray-900 bg-gray-900 text-sm font-medium text-white hover:bg-gray-800 transition-colors"
              >
                Class averages
              </button>
            </div>
          </div>
          {students.length > 0 && allSignalsEmpty(students.map((s) => s.currentWeek)) && <SignalsEmptyNote />}
          {students.length === 0 ? (
            <p className="text-gray-400 italic">No students enrolled in this class yet.</p>
          ) : (
            <div className="space-y-3">
              {paginatedStudents.map((s) => (
                <button
                  key={s.studentId}
                  type="button"
                  onClick={() => openStudentDetail(s)}
                  className="w-full text-left bg-white border border-gray-200 rounded-2xl p-4 shadow-sm hover:shadow-md transition-all"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-semibold text-black">{s.firstName} {s.lastName}</p>
                      <p className="text-xs text-gray-500">@{s.username}</p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                      {SIGNAL_KEYS.map((key) => (
                        <span
                          key={key}
                          title={SIGNAL_META[key].help}
                          className={`px-2 py-1 rounded-full text-xs font-medium ${SIGNAL_META[key].badge}`}
                        >
                          {SIGNAL_META[key].short} {fmtSignal(signalValue(s.currentWeek, key))}
                        </span>
                      ))}
                    </div>
                  </div>
                </button>
              ))}
              {totalStudentPages > 1 && (
                <div className="pt-1 flex items-center justify-between">
                  <p className="text-xs text-gray-500">
                    Page {studentPage} of {totalStudentPages}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setStudentPage((p) => Math.max(1, p - 1))}
                      disabled={studentPage === 1}
                      className="px-3 py-1.5 text-xs rounded-lg border border-gray-300 bg-white text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      onClick={() => setStudentPage((p) => Math.min(totalStudentPages, p + 1))}
                      disabled={studentPage === totalStudentPages}
                      className="px-3 py-1.5 text-xs rounded-lg border border-gray-300 bg-white text-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
        {learnMoreModal}
        {classAveragesModal}
      </>
    );
  }

  if (level === 'student_detail' && selectedStudent) {
    return (
      <>
        <div className="space-y-3 animate-fadeIn w-full max-w-7xl mx-auto">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => setLevel('student_list')}
              className="inline-flex items-center px-3 py-2 rounded-lg border border-gray-300 bg-white text-sm font-medium text-gray-700 hover:text-black hover:bg-gray-50"
            >
              ← Back to students
            </button>
            <button
              type="button"
              onClick={() => setShowLearnMore(true)}
              className="px-3 py-2 rounded-lg border border-slate-300 bg-slate-100 text-sm font-medium text-slate-700 hover:text-slate-900 hover:bg-slate-100 active:bg-slate-100"
            >
              Learn more about metrics
            </button>
          </div>
          <div>
            <h2 className="text-2xl font-bold text-black">{selectedStudentName}</h2>
            <p className="text-sm text-gray-500 mt-1">@{selectedStudent.username}</p>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-8 h-8 border-4 border-gray-200 border-t-[#ba3638] rounded-full animate-spin" />
            </div>
          ) : error ? (
            <p className="text-red-500">{error}</p>
          ) : (
            <>
            {allSignalsEmpty(history) && <SignalsEmptyNote />}
            <div className="bg-[#f4f4f5] border border-gray-200 rounded-2xl p-3.5">
              <div className="flex items-center justify-between gap-3 mb-3">
                <h3 className="text-xl md:text-2xl font-bold text-black">
                  Student Metrics: {selectedStudentName}
                </h3>
                <div className="w-8 h-8 shrink-0 rounded-full bg-gray-300 text-gray-700 text-xs font-semibold flex items-center justify-center">
                  {selectedStudent.firstName[0]}{selectedStudent.lastName[0]}
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-[205px_1fr] gap-3">
                <div className="bg-white/60 rounded-2xl overflow-hidden border border-gray-200">
                  <div className="px-3 py-2 border-b border-gray-200 bg-white text-lg font-bold text-black">
                    Last three weeks:
                  </div>
                  <div className="p-3 grid grid-cols-2 lg:grid-cols-1 gap-2">
                    {SIGNAL_KEYS.map((key) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setSelectedMetric(key)}
                        title={SIGNAL_META[key].help}
                        className={`w-full text-left rounded-lg px-2 py-1.5 border-b border-gray-200 lg:last:border-b-0 ${
                          selectedMetric === key ? SIGNAL_META[key].selectedBg : ''
                        }`}
                      >
                        <div className="text-2xl sm:text-3xl font-bold" style={{ color: SIGNAL_META[key].color }}>
                          {fmtSignal(lastThreeWeekAverages[key])}
                        </div>
                        <div className="text-sm sm:text-base text-gray-700 mt-1">{SIGNAL_META[key].label}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="bg-white rounded-2xl border border-gray-200 p-4 min-w-0">
                  <MetricPills selected={selectedMetric} onSelect={setSelectedMetric} />
                  <h4 className="text-lg md:text-xl font-semibold text-center text-black mb-1">
                    {SIGNAL_META[selectedMetric].label} Over Time (8 Weeks) - {selectedStudentName}
                  </h4>
                  <p className="text-xs text-gray-500 text-center mb-2.5 max-w-xl mx-auto">
                    {SIGNAL_META[selectedMetric].help}
                  </p>
                  <div className="h-[260px] sm:h-[300px] w-full">
                    <SignalLineChart data={chartData} metric={selectedMetric} />
                  </div>
                </div>
              </div>
            </div>
            </>
          )}

          {canOpenCheckins && onOpenCheckin && (
            <section className="bg-white rounded-2xl border border-gray-200 p-4" aria-labelledby="student-checkins-heading">
              <h3 id="student-checkins-heading" className="text-lg font-bold text-black">Check-ins</h3>
              <p className="text-xs text-gray-500 mt-0.5">
                The unit check-ins behind these numbers. Open one to see {selectedStudent.firstName}'s answers in its briefing.
              </p>
              {checkinsError ? (
                <p className="text-sm text-gray-500 mt-3">Couldn't load check-ins: {checkinsError}</p>
              ) : studentCheckins === null ? (
                <p className="text-sm text-gray-500 mt-3">Loading check-ins…</p>
              ) : studentCheckins.length === 0 ? (
                <p className="text-sm text-gray-500 mt-3">No unit check-ins in this class yet.</p>
              ) : (
                <ul className="mt-2 divide-y divide-gray-100">
                  {studentCheckins.map((c) => {
                    const p = c.student;
                    return (
                      <li key={c.assignment_id} className="py-2.5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <div className="min-w-0">
                          <p className="font-medium text-gray-900 break-words">{c.title}</p>
                          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1 text-xs text-gray-600">
                            <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 ${STAGE_STYLE[p.stage].tile}`}>
                              <span className={`w-1.5 h-1.5 rounded-full ${STAGE_STYLE[p.stage].dot}`} aria-hidden="true" />
                              {STAGE_LABEL[p.stage]}
                            </span>
                            {c.lesson_date && <span>Lesson {formatDay(c.lesson_date)}</span>}
                            {p.total > 0 && <span>{p.resolved}/{p.total} questions resolved</span>}
                            {p.first_try_accuracy != null && <span>First try {fmtSignal(p.first_try_accuracy)}</span>}
                            {p.understanding != null && p.answered > 0 && <span>Understanding {fmtSignal(p.understanding)}</span>}
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => onOpenCheckin(c.assignment_id)}
                          className="self-start sm:self-auto shrink-0 px-3 py-1.5 rounded-lg border border-gray-300 bg-white text-sm font-medium text-gray-700 hover:text-black hover:bg-gray-50"
                        >
                          Open briefing
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          )}
        </div>
        {learnMoreModal}
      </>
    );
  }

  return null;
};

export default TeacherMetrics;
