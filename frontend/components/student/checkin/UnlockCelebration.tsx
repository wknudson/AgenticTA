import React, { useEffect, useRef } from 'react';
import { LockOpen } from 'lucide-react';
import { primaryBtn, secondaryBtn } from './ui';

interface Props {
  masteryPct: number;
  onStart: () => void;
  onClose: () => void;
}

const CONFETTI = ['#ba3638', '#f59e0b', '#16a34a', '#6366f1', '#ec4899', '#0ea5e9'];

/** The "Check-in unlocked" moment: a small dialog with a bit of confetti (none with reduced motion). */
const UnlockCelebration: React.FC<Props> = ({ masteryPct, onStart, onClose }) => {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const startRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    startRef.current?.focus();
    return () => { previous?.focus?.(); };
  }, []);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose(); return; }
    if (e.key !== 'Tab' || !dialogRef.current) return;
    const focusable = dialogRef.current.querySelectorAll('button');
    if (focusable.length === 0) return;
    const first: HTMLButtonElement = focusable[0];
    const last: HTMLButtonElement = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="unlock-title"
        aria-describedby="unlock-desc"
        onKeyDown={onKeyDown}
        onClick={(e) => e.stopPropagation()}
        className="cta-pop relative w-full max-w-sm overflow-hidden rounded-3xl bg-white p-6 text-center shadow-2xl"
      >
        <div className="pointer-events-none absolute inset-x-0 top-0 h-24 motion-reduce:hidden" aria-hidden="true">
          {Array.from({ length: 18 }, (_, i) => (
            <span
              key={i}
              className="cta-confetti absolute top-0 block h-2 w-1.5 rounded-sm"
              style={{
                left: `${(i * 53) % 100}%`,
                backgroundColor: CONFETTI[i % CONFETTI.length],
                animationDelay: `${(i % 6) * 90}ms`,
              }}
            />
          ))}
        </div>
        <span className="relative mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-100 text-green-700">
          <LockOpen className="h-8 w-8" aria-hidden="true" />
        </span>
        <h2 id="unlock-title" className="relative mt-4 text-2xl font-extrabold text-gray-900">Check-in unlocked!</h2>
        <p id="unlock-desc" className="relative mt-2 text-sm text-gray-700">
          You've mastered {masteryPct}% of the cards. Nice practicing! You're ready for the check-in, and the tutor is
          there if you get stuck.
        </p>
        <div className="relative mt-6 flex flex-col gap-2">
          <button ref={startRef} type="button" className={primaryBtn} onClick={onStart}>Start the check-in</button>
          <button type="button" className={secondaryBtn} onClick={onClose}>Keep practicing</button>
        </div>
      </div>
    </div>
  );
};

export default UnlockCelebration;
