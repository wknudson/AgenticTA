# Filing pipeline (Phase 1): owner Will

**What it does:** the teacher drops any file into one bucket. It gets auto-labeled (type, unit, title, dates) and becomes searchable by meaning.

**Kind of system:** *not an agent*. It's a fixed sequential pipeline: save → extract → (vision OCR) → chunk → embed → label → index. This is the Phase 1 "non-agentic foundation" the rubric asks for.

**Models:** open-source embeddings in-process (`BAAI/bge-small-en-v1.5` via fastembed); `gemini-3.8-flash` for labels and vision, returning the `FileLabels` Pydantic contract.

**Controls:** labels below `REVIEW_THRESHOLD` go to `needs_review`. Filing is reversible and visible to the teacher, so there's no human-approval step. Argue that in the matrix (reversibility = 5).

## Files you own
- `agents/app/agents/filing/*`
- `agents/app/shared/library.py` (the contract everyone else calls; keep the signatures stable)
- `frontend/components/agents/LibraryPanel.tsx`

## Status
- [x] upload endpoint, save, text extraction (PDF/DOCX/PPTX/TXT), chunking, keyword search
- [ ] embeddings → `library_chunk_vec`, then make `library.search()` use vectors
- [ ] LLM labels (`with_structured_output(FileLabels)`)
- [ ] images and scanned PDFs through the vision model
- [ ] UI: drag-and-drop, folder view by unit/type, Needs-review queue with label editing

## Done when
- [ ] 30+ real mixed files are filed
- [ ] semantic search beats keyword search on a small labeled test set (precision@5)
- [ ] traces are in the `agentic-ta-filing` LangSmith project
