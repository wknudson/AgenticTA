import React from 'react';
import {
  CalendarDays,
  Check,
  FilePenLine,
  FolderOpen,
  Gamepad2,
  Lightbulb,
  MessagesSquare,
  ShieldCheck,
} from 'lucide-react';
import { COLORS } from '../constants';
import Logo from './Logo';

const AGENTS = [
  {
    icon: FolderOpen,
    name: 'Library',
    does: 'Drop in everything you teach with: slides, worksheets, PDFs, even photos of the whiteboard. It labels each file, sorts it into its unit, and makes it searchable by meaning, not just keywords.',
    you: 'Fix any label in one click. Unsure files wait in a review list.',
  },
  {
    icon: CalendarDays,
    name: 'Scheduler',
    does: 'Reads the dates in your syllabus and assignments and builds the student calendar. It flags quizzes on holidays, weekends, or stacked on the same day.',
    you: 'Approve the calendar before students see it.',
  },
  {
    icon: FilePenLine,
    name: 'Update materials',
    does: 'Give one instruction, like "push Unit 3 back a week and add a section on enzymes", and it plans every file and assignment change that follows.',
    you: 'Approve each change. Originals are kept, never overwritten.',
  },
  {
    icon: Gamepad2,
    name: 'Study games',
    does: 'Turns a unit into flashcards, matching, and fill-in-the-blank games with points, streaks, and levels. A second AI checks every card against your material before you see it.',
    you: 'Approve the set before it is published.',
  },
  {
    icon: Lightbulb,
    name: 'Misconception finder',
    does: 'Reads tutor chats across the class and groups what students keep mixing up, then suggests a review game or lesson update. Names and contact details are removed first.',
    you: 'Nothing happens until you pick a suggestion.',
  },
  {
    icon: MessagesSquare,
    name: 'AI tutor',
    does: 'Helps students work through what they missed on the check-in, using your filed material for that unit. It gives hints and asks questions, and students explain each fix in their own words.',
    you: 'Choose per check-in: hints only, or the answer after honest tries.',
  },
];

const PENDING = [
  { agent: 'Scheduler', text: 'Unit 3 quiz moved to Oct 14 (Oct 10 is the assembly)' },
  { agent: 'Study games', text: '24 flashcards for Unit 2: Cell Structure' },
  { agent: 'Update materials', text: 'Unit 3 slides, version 2: added enzyme section' },
];

const Home: React.FC = () => {
  const scrollTo = (id: string) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="min-h-screen bg-[#fcfcfc]">
      <header className="sticky top-0 z-50 bg-[#fcfcfc]/90 backdrop-blur border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-6 py-3.5 flex items-center justify-between gap-4">
          <a href="/" className="flex items-center">
            <Logo />
          </a>
          <a
            href="/login"
            className="px-4 py-2 rounded-xl text-sm font-semibold text-white shadow-sm hover:opacity-90 transition whitespace-nowrap"
            style={{ backgroundColor: COLORS.primary }}
          >
            Teacher login
          </a>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 pt-10 pb-16 space-y-16">
        {/* 1) Hero */}
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-10 items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Built for teachers</p>
            <h1 className="mt-3 text-4xl sm:text-5xl font-extrabold text-slate-900 tracking-tight">
              A teaching assistant for the busywork.
              <span className="block" style={{ color: COLORS.primary }}>
                You stay in charge.
              </span>
            </h1>
            <p className="mt-5 text-slate-700 leading-relaxed max-w-xl">
              AgenticTA is a learning platform with AI agents that file your class materials, build the student
              calendar, update lessons, make study games, and spot what students are confused about.{' '}
              <span className="font-semibold">Nothing reaches students until you approve it.</span>
            </p>
            <div className="mt-7 flex flex-col sm:flex-row gap-3">
              <a
                href="/login"
                className="inline-flex items-center justify-center px-5 py-3 rounded-2xl text-sm font-bold text-white shadow hover:opacity-90 transition"
                style={{ backgroundColor: COLORS.primary }}
              >
                Get Started
              </a>
              <button
                type="button"
                onClick={() => scrollTo('agents')}
                className="inline-flex items-center justify-center px-5 py-3 rounded-2xl text-sm font-semibold text-slate-700 border border-slate-300 bg-white hover:bg-slate-50 transition"
              >
                Meet the agents
              </button>
            </div>
            <div className="mt-5">
              <a href="/admin" className="text-sm font-semibold underline" style={{ color: COLORS.primary }}>
                Administrator login
              </a>
            </div>
          </div>

          {/* Approvals inbox preview */}
          <div className="bg-white border border-slate-200 rounded-[32px] p-6 sm:p-7 shadow-sm" aria-label="Example approvals inbox">
            <div className="flex items-center justify-between">
              <p className="text-sm font-bold text-slate-900">Waiting for your approval</p>
              <span
                className="text-xs font-bold text-white rounded-full px-2.5 py-0.5"
                style={{ backgroundColor: COLORS.primary }}
              >
                {PENDING.length}
              </span>
            </div>
            <ul className="mt-4 space-y-3">
              {PENDING.map((p) => (
                <li key={p.text} className="rounded-2xl border border-slate-200 bg-slate-50 p-4 flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{p.agent}</p>
                    <p className="mt-1 text-sm text-slate-800">{p.text}</p>
                  </div>
                  <span className="flex-shrink-0 inline-flex items-center gap-1 rounded-xl border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">
                    <Check className="w-3.5 h-3.5" /> Approve
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-xs text-slate-500">
              Agents do the drafting. You review it in one inbox and approve, edit, or reject.
            </p>
          </div>
        </section>

        {/* 2) The problem */}
        <section id="problem" className="bg-white border border-slate-200 rounded-[32px] p-8 sm:p-10 shadow-sm">
          <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
            Less time on logistics. More time teaching.
          </h2>
          <p className="mt-4 text-slate-700 leading-relaxed max-w-3xl">
            Planning, filing, re-dating, and rewriting eat the hours you meant to spend with students. And the clearest
            signal of who is confused usually shows up after the test.
          </p>
          <div className="mt-5 grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-semibold text-slate-900">Materials everywhere</p>
              <p className="mt-2 text-sm text-slate-700 leading-relaxed">
                Years of slides, handouts, and scans across drives and folders, and you still can't find last year's lab.
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-semibold text-slate-900">One change, ten edits</p>
              <p className="mt-2 text-sm text-slate-700 leading-relaxed">
                Moving one unit means fixing the calendar, the slides, the due dates, and the review sheet by hand.
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-semibold text-slate-900">Confusion shows up late</p>
              <p className="mt-2 text-sm text-slate-700 leading-relaxed">
                By the time a misconception appears on a grade, you've lost weeks you could have spent reteaching it.
              </p>
            </div>
          </div>
        </section>

        {/* 3) The agents */}
        <section id="agents" className="space-y-4 scroll-mt-24">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Meet the agents</p>
            <h2 className="mt-2 text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
              Six assistants, one for each job
            </h2>
            <p className="mt-3 text-slate-700 leading-relaxed max-w-3xl">
              Each one is built for its task, so the simple jobs stay fast and cheap and the hard ones get more care.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {AGENTS.map(({ icon: Icon, name, does, you }) => (
              <div key={name} className="bg-white border border-slate-200 rounded-[28px] p-6 shadow-sm flex flex-col">
                <div
                  className="w-10 h-10 rounded-2xl flex items-center justify-center"
                  style={{ backgroundColor: `${COLORS.primary}14`, color: COLORS.primary }}
                >
                  <Icon className="w-5 h-5" />
                </div>
                <p className="mt-4 text-base font-bold text-slate-900">{name}</p>
                <p className="mt-2 text-sm text-slate-700 leading-relaxed flex-1">{does}</p>
                <p className="mt-4 pt-3 border-t border-slate-100 text-xs text-slate-600">
                  <span className="font-semibold text-slate-900">You: </span>
                  {you}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* 4) How a unit flows */}
        <section id="how-it-works" className="bg-white border border-slate-200 rounded-[32px] p-8 sm:p-10 shadow-sm scroll-mt-24">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">How it works</p>
          <h2 className="mt-2 text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
            One unit, start to finish
          </h2>
          <ol className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-x-10 gap-y-5 text-sm text-slate-700">
            <li>
              <p className="font-semibold text-slate-900">1) Drop in your materials</p>
              <p className="mt-1">The library files them into units, and the syllabus dates feed the calendar.</p>
            </li>
            <li>
              <p className="font-semibold text-slate-900">2) Approve the calendar</p>
              <p className="mt-1">The scheduler proposes due dates and explains any conflicts it found.</p>
            </li>
            <li>
              <p className="font-semibold text-slate-900">3) Students practice with study games</p>
              <p className="mt-1">
                At home, before class: flashcards, matching, and fill in the blank built from your unit, with points,
                streaks, and levels.
              </p>
            </li>
            <li>
              <p className="font-semibold text-slate-900">4) Students do a check-in with the tutor</p>
              <p className="mt-1">
                Graded on completion, not correctness. Every miss gets fixed with the tutor, which follows your rules.
              </p>
            </li>
            <li>
              <p className="font-semibold text-slate-900">5) Walk in knowing what the class is stuck on</p>
              <p className="mt-1">The misconception finder groups confusion from the check-ins and suggests a fix.</p>
            </li>
            <li>
              <p className="font-semibold text-slate-900">6) Adjust with one instruction</p>
              <p className="mt-1">Tell the materials agent what to change, and approve the updated versions.</p>
            </li>
          </ol>
        </section>

        {/* 5) Guardrails */}
        <section id="guardrails" className="bg-white border border-slate-200 rounded-[32px] p-8 sm:p-10 shadow-sm">
          <div className="flex items-center gap-3">
            <ShieldCheck className="w-7 h-7" style={{ color: COLORS.primary }} />
            <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">Built with guardrails</h2>
          </div>
          <div className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-semibold text-slate-900">You approve what students see</p>
              <p className="mt-2 text-sm text-slate-700 leading-relaxed">
                Calendars, games, and lesson changes wait in your approvals inbox until you say yes.
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-semibold text-slate-900">Some things are off limits</p>
              <p className="mt-2 text-sm text-slate-700 leading-relaxed">
                No agent can change grades, delete your work, or send anything outside the app.
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-semibold text-slate-900">Student privacy first</p>
              <p className="mt-2 text-sm text-slate-700 leading-relaxed">
                Names and contact details are removed from student chats before any AI reads them.
              </p>
            </div>
          </div>
        </section>

        {/* 6) Metrics */}
        <section id="metrics" className="bg-white border border-slate-200 rounded-[32px] p-8 sm:p-10 shadow-sm">
          <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
            See real learning, not just scores
          </h2>
          <p className="mt-3 text-slate-700 leading-relaxed max-w-3xl">
            When points depend on being right, students open another tab and ask a different AI. So we flipped it:
            the learning happens in practice, the check-in rewards honest work, and every question a student asks our
            tutor tells you what to reteach.
          </p>
          <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-semibold text-slate-900">Practice that's fun</p>
              <p className="mt-2 text-sm text-slate-700 leading-relaxed">
                Flashcards, matching, and fill in the blank with points, streaks, and levels. Missed cards come back
                until they stick, and the check-in unlocks once most of the unit is mastered.
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-semibold text-slate-900">A check-in graded on completion</p>
              <p className="mt-2 text-sm text-slate-700 leading-relaxed">
                Answer every question and fix every miss for full credit. Getting it wrong never costs points, and
                students are <span className="font-semibold">encouraged</span> to use our tutor when they get stuck.
              </p>
            </div>
          </div>
          <p className="mt-6 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Learning signals, week by week for each student
          </p>
          <div className="mt-3 grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-semibold text-slate-900">First-try accuracy</p>
              <p className="mt-2 text-sm text-slate-700 leading-relaxed">
                How many check-in questions a student got right on the first try: what they knew walking in. Shown as
                feedback, never taken off the grade.
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-semibold text-slate-900">Fixed with help</p>
              <p className="mt-2 text-sm text-slate-700 leading-relaxed">
                Of the questions a student missed, how many they worked out with the tutor. Using the tutor is a good
                thing here: it means they pushed through.
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-sm font-semibold text-slate-900">Understanding</p>
              <p className="mt-2 text-sm text-slate-700 leading-relaxed">
                First-try accuracy plus half credit for misses fixed{' '}
                <span className="font-semibold">without</span> the tutor giving the answer, so you can tell who got it
                from who got walked through it.
              </p>
            </div>
          </div>
        </section>

        {/* 7) CTA */}
        <section id="cta" className="bg-slate-900 rounded-[32px] p-8 sm:p-10 text-white">
          <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight">Bring AgenticTA to your school</h2>
          <p className="mt-3 text-slate-200 max-w-2xl leading-relaxed">
            Start with one class, a department, or a pilot. We'll help you set it up so your agents are working for
            you in the first week.
          </p>
          <div className="mt-6 flex flex-col sm:flex-row gap-3">
            <a
              href="/contact"
              className="inline-flex items-center justify-center px-6 py-3 rounded-2xl text-sm font-bold text-white shadow hover:opacity-90 transition"
              style={{ backgroundColor: COLORS.primary }}
            >
              Get Started
            </a>
          </div>
        </section>
      </main>
    </div>
  );
};

export default Home;
