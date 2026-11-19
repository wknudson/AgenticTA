# Filing pipeline (Phase 1): owner Will

**What it does:** the teacher drops any file (Word, PowerPoint, PDF, text, photos of whiteboards, scans) into one bucket. Each file gets auto-labeled (type, unit, title, summary, dates), sorted into unit folders, and made searchable by keyword *and* by meaning. Anything the pipeline isn't sure about lands in a **Needs review** queue for the teacher.

**Kind of system:** *not an agent*. It's a fixed pipeline, which is the rubric's Phase 1 "non-agentic foundation". Every upload needs the same steps in the same order with no planning, so a pipeline is cheaper, faster and easier to audit than an agent. The LLM does only the two jobs it's better at than rules: reading images and scans, and labeling messy documents.

```
dedupe (sha256) -> save original -> extract text (pypdf / python-docx / python-pptx, or Gemini vision for
images & scanned PDFs) -> recursive chunking (never crosses a page/slide) -> label (Gemini, Pydantic
contract) -> deterministic guardrails -> index (FTS5 keyword + sqlite-vec embeddings)
```

## Models (config.yaml → `filing`; key in `agents/app/agents/filing/.env`)

| Job | Model | Why |
|---|---|---|
| Labels + vision | `gemini-3.6-flash` | cheap, multimodal, stable |
| Fallback | `gemini-3.5-flash-lite` | used when the labeler errors or times out (60 s); if both fail, rule-based labels + review |
| Embeddings | `gemini-embedding-2` at 768 dims | no model download. Document text goes to Google; that's fine for teacher materials, not student data |

We first tried `gemini-3.8-flash`, but it was overloaded (504s, about 200 s per label). The 60 s timeout plus the fallback chain is the guardrail that came out of that, and it's a good story for the write-up.

**Free-tier limits, measured:** `gemini-3.6-flash` allows **20 generate requests per day**, and `gemini-embedding-2` allows **100 embed requests per minute**. The first full run hit both. `app/shared/quota.py` now tells the limits apart:
- **Per-minute limit:** wait the delay Google returns, then retry.
- **Daily limit:** stop calling that model until it resets and use the fallback.
- **503 / overload:** go straight to the next model.

When every model is out, the file still gets filed, with rule-based labels and a plain-language reason in Needs review. **Re-check with AI** (one file, or the whole queue) re-runs a file from its saved original later. Labels the teacher set are kept.

## Search: `library.search(query, class_id, k, mode=...)`

- **keyword:** SQLite FTS5 with BM25. Best for exact terms (vocabulary, assignment names).
- **semantic:** sqlite-vec cosine nearest neighbors over Gemini embeddings. Best for paraphrases ("how do plants make food" finds the photosynthesis slides).
- **hybrid** (default): both, merged with Reciprocal Rank Fusion, `score = Σ 1/(60 + rank)`. This is Module 4's hybrid retriever.

Every hit has a `match` field (`keyword` / `semantic` / `both`), and its page or slide number. Without a key, search falls back to keyword.

## Guardrails (deterministic, after the model)

- `doc_type` must be one of `DOC_TYPES` (the Pydantic `Literal`)
- Dates must be real `YYYY-MM-DD` dates near the school year; anything else is dropped
- Units snap to the class's existing names ("unit 3 - energy" → "Unit 3: Cell Energy"). A bare "Unit 2" folder is renamed when a file names it "Unit 2: Cell Structure"
- **Needs review** when: confidence < 0.6, type is `other`, no readable text, an unfamiliar unit name, or the labels came from rules instead of AI. The reason is shown to the teacher
- Re-uploading the same file is detected and skipped

**Why no human-approval step:** filing is reversible (edit labels, archive, restore) and the teacher sees everything. That's reversibility = 5 in the matrix. The review queue is how the human stays in the loop without slowing every upload.

## Files you own

- `agents/app/agents/filing/*`
- `agents/app/shared/library.py`, `embeddings.py` (the contract everyone calls; keep the signatures stable)
- `frontend/components/agents/LibraryPanel.tsx`, `frontend/components/agents/library/*`
- `agents/sample_data/*`, `agents/evals/filing_eval.py`

## Try it

- **Library tab → "File the sample course"** files the 32-file sample Biology course.
- **Regenerate the sample files** with `npm run sample-course` (they're committed, so you rarely need this).
- **Run the eval** (real models, on its own library in `agents/evals/.cache/`, never your dev data): `npm run eval:filing`. Add `-- --langsmith` to log keyword / semantic / hybrid as 3 LangSmith experiments, compared under Datasets → `agentic-ta-filing-search`.

### Working on the free tier (our setup)

A free Gemini key allows about **20 labeling calls per day**, and one full course needs about 35. So:

- **The eval keeps its library between runs.** AI-labeled files are reused at zero cost. Only new files, and files that fell back to rules, go to the AI again. Run it once a day and `ai_labeled` climbs until it reaches 32/32. The report shows `waiting_for_ai_quota` and `files_sent_to_ai_this_run`.
- **To re-score search only** (only embedding calls, which allow 100/minute): `npm run eval:filing -- --search-only`.
- **Before the presentation,** compare models: `--fresh` starts over (a full re-label, about two days of free quota).
- **In the app, clicking "File the sample course" spends a full day's labeling quota.** Use it sparingly. Uploading a few real files and **Re-check with AI** are cheaper.
- **Prefer an AI-labeled eval for the write-up:** the first full run (`evals/results/filing_eval_20261119-1641.md`) ran out of quota partway, which is why its unit accuracy is low.

## Done when

- [x] 30+ mixed files are filed (32-file sample course: DOCX, PPTX, PDF, TXT/MD, photos, scans)
- [x] semantic/hybrid search beats keyword on a labeled test set (`npm run eval:filing`; results in `agents/evals/results/`)
- [x] traces are in the `agentic-ta-filing` LangSmith project
