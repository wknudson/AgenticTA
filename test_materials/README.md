# Test materials for the Library (filing system)

Fake class files to drag into the Library tab. Everything is invented. Regenerate any time with `npm run test-materials`.

| Folder | Class to drop it into | Files |
|---|---|---|
| `algebra2/` | **Algebra II - Period 2** | 18: syllabus, calendar, slides, notes, worksheets, quizzes, a test, rubric, reading, a whiteboard photo, a scanned quiz |
| `intro_cs/` | **Intro to CS - Period 6** | 12: syllabus, slides, notes, worksheets, a quiz, rubric, two `.py` files, a whiteboard photo |
| `edge_cases/` | **Algebra II - Period 2** | 6 tricky files (see the table at the end) |

Both classes belong to the teacher `sarah_b` (password `password123`), so one login covers everything. `expected.json` lists the right type and unit for every file, so you can check the labels.

## Before you start

1. **In VS Code,** pull `main` and run the task **setup: first time** (or `npm run setup:agents` if you set up before).
2. **Check your Gemini key:** `npm run env` should show `GOOGLE_API_KEY set` on the filing line.
3. **Start the app:** Ctrl+Shift+B, then open http://localhost:5173. If `npm run dev` was already running, stop it with Ctrl+C and start it again so it picks up the new code.
4. **Clean slate:** `npm run library:reset -- --class 1` empties Algebra II's library and `--class 4` does Intro to CS. Everything else in the database stays.

## AI quota (free tier)

Most files are labeled **without the AI**, using file-name rules plus embeddings against the syllabus units. Only photos and scans (one request each) and files the rules aren't sure about go to the AI, and the unsure ones are batched up to 6 per request. Uploading **all 36 files should take roughly 10 AI requests** of the free 20 per day.

- **"AI checking…":** files that show it are queued. The list refreshes itself and the badge goes away within a few seconds.
- **If the quota does run out:** files keep their automatic labels and wait in Needs review with the reason. They finish on their own once the quota resets, or you can label them yourself.

## Test checklist

Log in as `sarah_b` and open **Algebra II - Period 2 → Library**.

**1. Syllabus first** (it teaches the labeler the units)
- [ ] Drop `algebra2/Algebra2_Syllabus_Fall2026.docx` alone. It files as **Syllabus**, no unit, with 5 dates (open it to see).

**2. The rest of the class**
- [ ] Drop all the other files in `algebra2/` at once. The upload list shows each file's progress.
- [ ] The folders on the left are **Unit 1: Linear Functions** through **Unit 4: Exponential Functions**, plus **Whole course**.
- [ ] Files that never say their unit still land in the right one: `slope_intercept_notes.txt` (Unit 1), `Systems_Substitution_Elimination_Notes.docx` (Unit 2), `Factoring_Practice_Worksheet.docx` (Unit 3), `Exponential_Growth_Notes.md` (Unit 4).
- [ ] `whiteboard_vertex_form.jpg` and `Unit3_Quiz_Quadratics_SCANNED.pdf` were **read by AI**: open each and expand "Text the pipeline read".
- [ ] The type chips (Quiz, Worksheet...) filter the list.

**3. Search** (Search tab; try all three modes and watch the badges)

These were checked with real embeddings; what you should see:

| Search for | Meaning (and hybrid) finds | What keyword does instead |
|---|---|---|
| `how steep a line is` | slope slides, graphing worksheet, slope notes | puts the quadratics textbook first |
| `two equations at the same time` | systems test, systems notes, word problems | also pulls in the exponential notes |
| `ball thrown in the air` | textbook excerpt **p. 8** (projectile motion) | same top hit |
| `money that keeps growing` | credit card reading, exponential notes, compound interest rubric | finds the reading, then a textbook page |
| `discriminant` | quadratics slides, textbook **p. 7** (and the scanned quiz once AI has read it) | similar, plus the syllabus |
| `Unit 2 test` | `Unit2_Test_Systems.pdf` first | ranks the syllabus and calendar first (they mention the test date). A good example for the write-up |
| `vertex form` | slides, textbook **p. 3** (and the whiteboard photo once AI has read it) | same files |

**4. Edge cases:** drop all of `edge_cases/` into Algebra II

| File | Expected |
|---|---|
| `Graphing_Lines_Worksheet (1).docx` | "already in your library" (same bytes as the original) |
| `Graphing_Lines_Worksheet_v2.docx` | filed as a separate worksheet (Unit 1). Different content, so not a duplicate |
| `gradebook_export.xlsx` | Needs review: "can't read .xlsx files yet" |
| `scan_blank_page.pdf` | Needs review: nothing to read |
| `IMG_4021.jpg` | sticky-note photo: the AI reads it, finds the 2026-12-04 date, type schedule or other |
| `Algebra2_Textbook_Ch3_Excerpt.pdf` | Reading, Unit 3. Search hits show page numbers |

**5. How the labels were made**
- [ ] Most files show **auto** as the labeler (open one: "Labeled automatically… (no AI call)"). Photos, scans and a few unclear files show **AI**.
- [ ] Upload files *before* the syllabus in a fresh class. Run `npm run library:reset -- --class 4`, then drop `intro_cs/If_Statements_Notes.md` and `intro_cs/Loops_Practice_Problems.pdf` into Intro to CS. They land in Whole course. Then drop `IntroCS_Syllabus.docx`: both move into **Unit 2: Decisions and Loops** on their own, with no AI call. (Checked with real embeddings.)
- [ ] `GET http://localhost:8000/agents/filing/ai-queue` shows what's queued and how many AI requests were made since the service started.

**6. Teacher controls**
- [ ] Open a file in Needs review, fix the type or unit, then **Save & file it**. It leaves the queue, and the list shows "you" as the labeler.
- [ ] **Re-check with AI** on a file that was labeled by rules. It gets AI labels (when quota is left).
- [ ] **Archive** a file. It disappears from the list and from search.
- [ ] **Download original** gives back the exact file.

**7. Intro to CS** (switch class)
- [ ] Drop `intro_cs/IntroCS_Syllabus.docx` first, then the rest.
- [ ] `hello_world_starter.py` and `guessing_game_project.py` are read as text. The guessing game should pick up the 2026-11-06 due date from its comment.
- [ ] Search `make the computer repeat something`: meaning mode finds the loops worksheet and quiz, while keyword mode misses them (it finds the lists cheat sheet).
- [ ] Check that Algebra II files never show up in Intro to CS search, because each class has its own library.

**8. Behind the scenes**
- [ ] LangSmith → project **agentic-ta-filing**: each upload is one trace, with steps for extract, chunk, label and embed, and their timings.
- [ ] Optional: open `data/agenticta.sqlite` in VS Code (SQLite viewer) and look at `library_files`.

## If something looks off

- **Labels are wrong:** compare with `expected.json`, then fix it in the app. Your fix is saved as a teacher label.
- **"waiting for AI" for a long time:** the daily quota is used up. Files finish on their own after it resets, or label them yourself.
- **A new Python change doesn't show up:** restart `npm run dev` (Windows sometimes gets stuck reloading).
- **Start over:** `npm run library:reset -- --class 1` (or `--class 4`).
