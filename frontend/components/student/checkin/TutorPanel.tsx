import React, { useEffect, useId, useRef, useState } from 'react';
import { Bot, Lightbulb, Send } from 'lucide-react';
import {
  CheckinApiError,
  getCheckinChat,
  isStudentMessage,
  postCheckinChat,
  type CheckinQuestion,
  type TutorMessage,
  type TutorMode,
} from '../../../services/checkinApi';
import { Spinner, primaryBtn, textInput } from './ui';

interface Props {
  assignmentId: number;
  token: string;
  question: CheckinQuestion;
  tutorMode: TutorMode;
  revealAfter: number;
  readOnly: boolean;
  onQuestion: (q: CheckinQuestion) => void;
  onAuthError: (message: string) => void;
}

/** The tutor, scoped to one check-in question. Its transcript is kept for the teacher's briefing. */
const TutorPanel: React.FC<Props> = ({ assignmentId, token, question, tutorMode, revealAfter, readOnly, onQuestion, onAuthError }) => {
  const [messages, setMessages] = useState<TutorMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');
  const logRef = useRef<HTMLDivElement | null>(null);
  const inputId = useId();
  const headingId = useId();

  const canChat = !readOnly && (question.status === 'unanswered' || question.status === 'needs_fix');

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError('');
    getCheckinChat(assignmentId, question.question_id, token, controller.signal)
      .then((r) => { if (!controller.signal.aborted) setMessages(Array.isArray(r.messages) ? r.messages : []); })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (err instanceof CheckinApiError && err.status === 401) onAuthError(err.message);
        setLoadError("Couldn't load your earlier messages. You can still ask the tutor.");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignmentId, question.question_id, token]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  const send = async () => {
    const msg = input.trim();
    if (!msg || sending || !canChat) return;
    setSendError('');
    setSending(true);
    setInput('');
    setMessages((m) => [...m, { role: 'user', content: msg }]);
    try {
      const r = await postCheckinChat(assignmentId, token, { question_id: question.question_id, message: msg });
      setMessages((m) => [...m, { role: 'assistant', content: r.reply }]);
      if (r.question) onQuestion(r.question);
    } catch (err) {
      setMessages((m) => m.slice(0, -1));
      setInput(msg);
      if (err instanceof CheckinApiError && err.status === 401) onAuthError(err.message);
      setSendError(err instanceof Error ? err.message : "The tutor couldn't answer just now. Try again.");
    } finally {
      setSending(false);
    }
  };

  const intro =
    question.status === 'needs_fix'
      ? "Let's work this one out together. Tell me what you were thinking, or ask me for a hint."
      : "Let's work this one out together. Ask me about this question and I'll help you think it through.";

  return (
    <section aria-labelledby={headingId} className="rounded-2xl border border-gray-200 bg-white">
      <div className="flex items-start gap-3 border-b border-gray-100 px-4 py-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#ba3638]/10 text-[#ba3638]">
          <Bot className="w-4 h-4" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h3 id={headingId} className="font-semibold text-gray-900">Tutor: question {question.number}</h3>
          <p className="text-xs text-gray-600">
            {tutorMode === 'answer_after_tries'
              ? `Hints first. After ${revealAfter} honest ${revealAfter === 1 ? 'try' : 'tries'} at fixing it, the tutor can walk you through the answer.`
              : "Hints only: the tutor helps you think it through but won't hand you the answer."}
          </p>
        </div>
      </div>

      {question.can_reveal && question.status === 'needs_fix' && (
        <p className="mx-4 mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <Lightbulb className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
          <span>You've given this {question.tries} honest {question.tries === 1 ? 'try' : 'tries'}. The tutor can now walk you through it step by step. Just ask.</span>
        </p>
      )}

      <div
        ref={logRef}
        role="log"
        aria-live="polite"
        aria-label={`Conversation with the tutor about question ${question.number}`}
        className="max-h-80 min-h-[8rem] overflow-y-auto px-4 py-3 space-y-3"
      >
        <div className="mr-8 rounded-2xl rounded-tl-sm border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-800">{intro}</div>
        {loading && <Spinner label="Loading your messages…" className="text-xs text-gray-500" />}
        {loadError && <p className="text-xs text-gray-500">{loadError}</p>}
        {messages.map((m, i) =>
          isStudentMessage(m) ? (
            <div key={i} className="ml-8 rounded-2xl rounded-tr-sm bg-[#ba3638]/10 px-3 py-2 text-sm text-gray-900 whitespace-pre-wrap break-words">
              <span className="sr-only">You: </span>{m.content}
            </div>
          ) : (
            <div key={i} className="mr-8 rounded-2xl rounded-tl-sm border border-gray-200 bg-white px-3 py-2 text-sm text-gray-800 whitespace-pre-wrap break-words">
              <span className="sr-only">Tutor: </span>{m.content}
            </div>
          ),
        )}
        {sending && (
          <p className="flex items-center gap-1 text-xs text-gray-500">
            Tutor is thinking
            <span className="inline-flex gap-0.5" aria-hidden="true">
              <span className="motion-safe:animate-bounce [animation-delay:0ms]">.</span>
              <span className="motion-safe:animate-bounce [animation-delay:120ms]">.</span>
              <span className="motion-safe:animate-bounce [animation-delay:240ms]">.</span>
            </span>
          </p>
        )}
      </div>

      {canChat ? (
        <form
          className="border-t border-gray-100 px-4 py-3 space-y-2"
          onSubmit={(e) => { e.preventDefault(); void send(); }}
        >
          <label htmlFor={inputId} className="sr-only">Message the tutor</label>
          <div className="flex gap-2">
            <textarea
              id={inputId}
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(); }
              }}
              placeholder="Ask for a hint, or say what you're thinking…"
              className={`${textInput} resize-none min-w-0 flex-1`}
              maxLength={2000}
            />
            <button type="submit" disabled={sending || !input.trim()} className={`${primaryBtn} self-end px-3`} aria-label="Send message">
              <Send className="w-4 h-4" aria-hidden="true" />
            </button>
          </div>
          {sendError && <p role="alert" className="text-sm text-red-700">{sendError}</p>}
        </form>
      ) : (
        !readOnly && (
          <p className="border-t border-gray-100 px-4 py-3 text-xs text-gray-500">This question is done, so the tutor chat is closed.</p>
        )
      )}
    </section>
  );
};

export default TutorPanel;
