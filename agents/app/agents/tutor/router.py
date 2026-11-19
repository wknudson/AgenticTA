"""Tutor upgrade.  Owner: Will.

Today the student tutor still runs in Express (POST /api/ai/chat, backend/routes/ai.ts)
and stuffs the assignment's PDF summary into the prompt.  The upgrade moves it here:

TODO(Will):
  - create_agent(get_model("tutor"), tools=[search_library scoped to the assignment's unit])
    -> real retrieval instead of prompt stuffing; answers cite library chunks
  - port the deterministic answer-blocker (Dice similarity >= 0.72 in backend/routes/ai.ts)
    as middleware that runs before the model sees the message
  - PIIMiddleware("email", strategy="redact") + ModelCallLimitMiddleware
  - keep saving turns to student_chat_messages (the misconception finder reads them)
  - point the frontend's tutor call at /agents/tutor/chat, then retire the Express route
  - evaluation: a test set of assignment questions it must refuse + concept questions it must answer
"""
from __future__ import annotations

from app.shared.agent_router import make_router

router = make_router("tutor")
