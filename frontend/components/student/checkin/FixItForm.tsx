import React, { useId, useState } from 'react';
import { CircleAlert, Wrench } from 'lucide-react';
import type { CheckinQuestion } from '../../../services/checkinApi';
import { Spinner, primaryBtn, textInput } from './ui';

interface Props {
  question: CheckinQuestion;
  busy: boolean;
  /** Inline error, e.g. a 422 "not an honest try" reason from the server. */
  error: string;
  onSubmit: (body: { option_id?: number; explanation: string }) => void;
}

/**
 * Fixing a missed question takes the right answer plus a short explanation in the student's
 * own words (choice), or a rewritten explanation (explain). The tutor's judge checks it.
 */
const FixItForm: React.FC<Props> = ({ question, busy, error, onSubmit }) => {
  const [option, setOption] = useState<number | null>(null);
  const [text, setText] = useState('');
  const baseId = useId();
  const textId = `${baseId}-text`;
  const helpId = `${baseId}-help`;
  const errId = `${baseId}-err`;
  const isChoice = question.kind === 'choice';
  const ready = text.trim().length > 0 && (!isChoice || option !== null);

  return (
    <form
      className="rounded-2xl border-2 border-dashed border-[#ba3638]/40 bg-white p-4 sm:p-5 space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready || busy) return;
        onSubmit(isChoice ? { option_id: option as number, explanation: text.trim() } : { explanation: text.trim() });
      }}
      aria-labelledby={`${baseId}-title`}
    >
      <div>
        <h4 id={`${baseId}-title`} className="flex items-center gap-2 font-semibold text-gray-900">
          <Wrench className="w-4 h-4 text-[#ba3638]" aria-hidden="true" /> Fix it
        </h4>
        <p className="text-sm text-gray-600 mt-1">
          {isChoice
            ? 'Pick the answer you think is right now, then say why in a sentence or two.'
            : 'Rewrite your explanation using what you worked out.'}
        </p>
      </div>

      {question.last_feedback && (
        <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <strong>Not there yet:</strong> {question.last_feedback}
        </p>
      )}

      {isChoice && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-gray-800 mb-2">Your answer</legend>
          {(question.options ?? []).map((o) => {
            const checked = option === o.option_id;
            return (
              <label
                key={o.option_id}
                className={`flex items-start gap-3 rounded-xl border-2 px-3 py-2.5 text-sm cursor-pointer transition-colors focus-within:ring-4 focus-within:ring-[#ba3638]/20 ${
                  checked ? 'border-[#ba3638] bg-[#ba3638]/5' : 'border-gray-200 hover:border-gray-400'
                }`}
              >
                <input
                  type="radio"
                  name={`${baseId}-option`}
                  className="mt-0.5 accent-[#ba3638]"
                  checked={checked}
                  onChange={() => setOption(o.option_id)}
                  disabled={busy}
                />
                <span className="break-words min-w-0">{o.text}</span>
              </label>
            );
          })}
        </fieldset>
      )}

      <div>
        <label htmlFor={textId} className="block text-sm font-medium text-gray-800">
          {isChoice ? 'Why is that the answer?' : 'Your new explanation'}
        </label>
        <p id={helpId} className="text-xs text-gray-500 mb-1.5">
          {isChoice ? 'One or two sentences, in your own words.' : 'In your own words. A few clear sentences is plenty.'}
        </p>
        <textarea
          id={textId}
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={isChoice ? 3 : 4}
          maxLength={2000}
          disabled={busy}
          aria-describedby={`${helpId}${error ? ` ${errId}` : ''}`}
          aria-invalid={!!error}
          className={textInput}
        />
      </div>

      {error && (
        <p id={errId} role="alert" className="flex items-start gap-2 text-sm text-red-700">
          <CircleAlert className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" /> {error}
        </p>
      )}

      <button type="submit" disabled={!ready || busy} className={`${primaryBtn} w-full sm:w-auto`}>
        {busy ? <Spinner label="Checking your fix…" /> : 'Check my fix'}
      </button>
    </form>
  );
};

export default FixItForm;
