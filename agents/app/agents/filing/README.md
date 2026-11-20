# Filing pipeline (Phase 1): owner Will

**What it does:** the teacher drops any file (Word, PowerPoint, PDF, text, code, photos of whiteboards, scans) into one bucket. Each file is labeled (type, unit, title, summary, dates), sorted into unit folders, and made searchable by keyword *and* by meaning. Anything it isn't sure about lands in a **Needs review** queue for the teacher.

**Kind of system:** *not an agent*. It's a fixed pipeline, the rubric's Phase 1 "non-agentic foundation". Every upload needs the same steps with no planning, so a pipeline is cheaper, faster and easier to audit.

```
dedupe (sha256) -> save original -> extract text (pypdf / python-docx / python-pptx / plain text)
  -> recursive chunking (never crosses a page/slide) -> embed chunks (Gemini embeddings)
  -> FAST LABELS: file-name rules + embeddings vs. the syllabus units (no labeling model)
  -> deterministic guardrails -> index (FTS5 keyword + sqlite-vec)
  -> only if unsure: queue for a BATCHED AI double-check (several files per request)
photos & scanned PDFs: one AI call reads AND labels them
```

## Embeddings first, AI only when unsure

The first version asked the AI to label every file. That's about 35 requests per course, and the free Gemini tier allows 20 per day. The project requirements say it directly: *if embeddings and similarity search solve the problem, use them instead of a model you don't need.* So:

| Label | How (no AI) | When the AI is asked |
|---|---|---|
| type | file-name keywords (`Unit1_Quiz...` → quiz), then the first line, then nearest "type description" by embedding | no keyword matched |
| unit | "Unit 3" written in the name/title, else the nearest **syllabus unit description** by embedding (`classify.py`, margin over the runner-up ≥ 0.025) | the top two units are too close (often a course-wide file) |
| course-wide | syllabus, calendar, paperwork (letters, contracts, permission slips) | n/a |
| title, summary | first real line; first sentences | (the AI replaces them when it labels) |
| dates | ISO, `Dec 4`, `December 4, 2026`, `12/4/2026`, labeled with the rest of the line; unit date *ranges* skipped | n/a |

- **AI queue:** unsure files get `ai_pending`. A background worker (`ai_queue.py`) waits 4 s so a drag-and-drop arrives together, then labels up to **6 files in one request**.
- **No key, or quota used up:** files keep their fast labels and wait with the reason shown. The worker retries when the quota resets.
- **When a syllabus arrives later:** earlier files are re-sorted into units from their *stored* vectors (no calls).
- **"Re-check with AI"** on one file forces an immediate AI label.

**Measured on the 32-file sample Biology course** (`evals/results/filing_eval_20261120-1150.md` and `-1152.md`):

| | AI labels every file (first version) | Embeddings first (now) |
|---|---|---|
| AI requests for the course | ~35 (more than a day's free quota) | **5**: 3 photos/scans + 2 batches for 8 unsure files |
| Labeled with no AI call | 0 | **21 / 32**, all correct |
| Type and unit both right | 69% (that run hit the quota mid-way) | **100%** (32 / 32) |

## Models (config.yaml → `filing`; key in `agents/app/agents/filing/.env`)

| Job | Model | Why |
|---|---|---|
| Embeddings (search *and* unit sorting) | `gemini-embedding-2` at 768 dims | 100 requests/min on the free tier, no download. Teacher materials only, not student data |
| Photos/scans + unsure files | `gemini-3.6-flash` | cheap, multimodal, stable |
| Fallback | `gemini-3.5-flash-lite` | when the labeler errors, times out (60 s), or is out of daily quota |

We first tried `gemini-3.8-flash`, but it was overloaded (504s, about 200 s per label). The 60 s timeout and the fallback chain came out of that.

**Free-tier limits, measured:** `gemini-3.6-flash` allows **20 requests per day**, and `gemini-embedding-2` allows **100 requests per minute**. `app/shared/quota.py` tells the limits apart:
- **Per-minute limit:** wait the delay Google sends, then retry.
- **Daily limit:** skip that model until it resets.
- **503 / overload:** go straight to the next model.

## Search: `library.search(query, class_id, k, mode=...)`

- **keyword:** SQLite FTS5 with BM25. Best for exact terms (vocabulary, assignment names).
- **semantic:** sqlite-vec cosine nearest neighbors over Gemini embeddings. Best for paraphrases.
- **hybrid** (default): both, merged with Reciprocal Rank Fusion, `score = Σ 1/(60 + rank)` (Module 4).

On the 25 test questions, semantic search put the right file first **96%** of the time vs **76%** for keyword (93% vs 67% on paraphrases). Hybrid scored 88% for the top hit, but 100% within the top 5.

**"No matches" instead of random files:** nearest-neighbor search always returns *something*, so a question about another class used to get unrelated files back. Now:
- **Cutoff:** meaning-based hits below `filing.search.min_similarity` (**0.63**, in config.yaml) are dropped.
- **Stopwords:** common words ("how", "the", "make"...) no longer count as keyword matches.
- **Measured:** 12 off-topic questions asked in the wrong class return nothing in meaning mode, while every test question with a real answer still finds it. A 0.65 cutoff was tried first; it dropped "no school around the holidays" (the calendar scored 0.645), so it's 0.63. See `evals/results/filing_eval_20261120-1222.md`.
- **Re-measure** if the embedding model changes.

## Guardrails (deterministic, on every label, whoever made it)

- `doc_type` must be one of `DOC_TYPES` (Pydantic `Literal`)
- Dates must be real `YYYY-MM-DD` dates near the school year; anything else is dropped
- Units snap to the syllabus/existing names ("unit 3 - energy" → "Unit 3: Cell Energy"); course-wide types never get a unit
- **Needs review** when: still waiting for the AI, unsure with no AI available, type `other`, no readable text, or an unfamiliar unit name. The reason is shown to the teacher
- Re-uploading the same file is detected and skipped; teacher-set labels are never overwritten

**Why no human-approval step:** filing is reversible (edit labels, archive, restore) and the teacher sees everything. That's reversibility = 5 in the matrix. The review queue keeps the human in the loop without slowing every upload.

## Files you own

- `agents/app/agents/filing/*`: `pipeline.py` (steps), `classify.py` (fast labels), `ai_queue.py` (batched AI), `labels.py` (contract + guardrails)
- `agents/app/shared/library.py`, `embeddings.py`, `quota.py`
- `frontend/components/agents/LibraryPanel.tsx`, `frontend/components/agents/library/*`
- `agents/sample_data/*`, `agents/evals/filing_eval.py`, `test_materials/`

## Try it

- **Library tab → "File the sample course"** files the 32-file Biology course (about 5 AI requests now).
- **Hand testing:** `test_materials/README.md` (two more classes + edge cases).
- **Eval:** `npm run eval:filing` (real models, own library in `agents/evals/.cache/`; `--fresh` to start over, `--search-only` for no labeling calls, `--langsmith` to log search experiments).
- **Queue status:** `GET /agents/filing/ai-queue`. Run it now: `POST /agents/filing/ai-queue/run`.

## Done when

- [x] 30+ mixed files are filed (32-file sample course: DOCX, PPTX, PDF, TXT/MD, photos, scans)
- [x] semantic search beats keyword on a labeled test set (`npm run eval:filing`)
- [x] traces are in the `agentic-ta-filing` LangSmith project
- [x] labeling fits the free tier (5 requests per 32-file course)
