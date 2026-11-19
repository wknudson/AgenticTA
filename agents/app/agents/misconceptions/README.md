# Misconception finder: owner Teammate B

**What it does:** reads the stored tutor chats (`student_chat_messages`), groups what students keep getting confused about, and suggests review material ("Students in Unit 3 confuse mitosis and meiosis: make a review game?").

**Kind of system:** workflow agent. Pipeline: load → **redact** → cluster → summarize → suggest.

**Models:** a **local Ollama model** (`phi3` by default) so student chats never leave the machine, compared against `claude-haiku-5-5` on quality and latency. The comparison table goes in the write-up.

**Controls:**
- Deterministic redaction (emails, phone numbers, enrolled students' names) runs **before** any model sees the text, and there's a test for it.
- Read-only.
- Suggestions do nothing until the teacher clicks, and a click hands the suggestion to the games or materials agent.

## Files you own
`agents/app/agents/misconceptions/*`, `frontend/components/agents/InsightsPanel.tsx`

## Setup
Install [Ollama](https://ollama.com), then `ollama pull phi3` (or change the model in `agents/config.yaml`).

## Done when
- [ ] finds planted misconceptions in seeded chats
- [ ] local vs API comparison table (quality, latency, cost) from LangSmith
- [ ] insight cards with "Make a review game" / "Draft a review sheet" buttons
