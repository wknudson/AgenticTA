# Misconception and materials update agent: owner Merrick

**What it does:** reads stored tutor chats (`student_chat_messages`), groups recurring misunderstandings, and recommends a focused class-material update plus a reteaching activity.

**Kind of system:** private analysis workflow with a teacher-approved handoff. Pipeline: load → **redact** → cluster → recommend → teacher approves → materials agent drafts a revision → teacher approves the actual revision.

**Models:** a **local Ollama model** (`phi3` by default) so student chats never leave the machine, compared against `claude-haiku-5-5` on quality and latency. The comparison table goes in the write-up.

**Controls:**
- Deterministic redaction (emails, phone numbers, enrolled students' names) runs **before** any model sees the text, and there's a test for it.
- Analysis is read-only. The teacher must approve a recommendation before it is sent to Materials.
- Materials creates a draft revision; a second teacher approval is required before that revision changes the class library.

## Files you own
`agents/app/agents/misconceptions/*`, `frontend/components/agents/InsightsPanel.tsx`

## Setup
Install [Ollama](https://ollama.com), then `ollama pull phi3` (or change the model in `agents/config.yaml`).

## Implemented
- Chat loading is bounded to the 100 most recent user messages. Emails, phone numbers, and enrolled student names are scrubbed before clustering; database and student identifiers are replaced with run-local IDs.
- The local and baseline clustering roles share the same structured output validation. Model calls run with LangSmith tracing disabled; only aggregate counts and elapsed time are traced afterward.
- The `/insights` endpoint returns stored redacted examples and structured recommendations. The teacher panel offers anonymized examples, the proposed material edit, and a reteaching activity.
- Clicking **Approve suggestion & draft update** is the teacher's approval to start a materials draft. The `/insights/{id}/draft` endpoint sends only the topic and recommendation to the materials agent, records the insight as sent, and relies on the materials agent's separate approval before any file changes are applied.
- Offline demo groups synthetic examples with keyword rules and labels them as a demonstration, not model inference.
- `python -m app.agents.misconceptions.evaluate --offline` scores the synthetic fixture without model calls. Add `--baseline` for local-versus-Haiku evaluation on synthetic text only; its output reports pair precision, recall, F1, and latency. Provider cost is not yet measured.

### Local fixture run (2026-11-19)

One run with the configured `ollama:phi3` model took 27.227 seconds and scored pair precision 1.000, recall 0.667, and F1 0.800 on the six-question synthetic fixture. This is a single local result, not a general quality claim. LangSmith upload was blocked by the current network sandbox, so this run is not visible in the LangSmith project.

## Remaining verification
- [ ] Verify grouping on seeded tutor chats with Ollama available.
- [ ] Run the privacy, insight-card, and scheduler checks in `agents/tests/test_merrick_agents.py` when ready to verify.
- [ ] Capture provider token usage/cost for a cost comparison; current evaluation does not claim a measured baseline cost.
