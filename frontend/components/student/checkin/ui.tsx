import React from 'react';
import { LoaderCircle } from 'lucide-react';

/**
 * The few keyframes the check-in uses (Tailwind's CDN build has no shake or pop). All of them
 * only run when the student hasn't asked for reduced motion.
 */
export const CheckinStyles: React.FC = () => (
  <style>{`
@media (prefers-reduced-motion: no-preference) {
  @keyframes cta-pop { 0% { transform: scale(.85); opacity: 0 } 60% { transform: scale(1.04); opacity: 1 } 100% { transform: scale(1) } }
  @keyframes cta-shake { 0%,100% { transform: translateX(0) } 20%,60% { transform: translateX(-5px) } 40%,80% { transform: translateX(5px) } }
  @keyframes cta-float { 0% { transform: translateY(4px); opacity: 0 } 20% { transform: translateY(0); opacity: 1 } 80% { opacity: 1 } 100% { transform: translateY(-14px); opacity: 0 } }
  @keyframes cta-confetti { 0% { transform: translateY(0) rotate(0); opacity: 1 } 100% { transform: translateY(70px) rotate(240deg); opacity: 0 } }
  .cta-pop { animation: cta-pop .35s ease-out both }
  .cta-shake { animation: cta-shake .4s ease-in-out }
  .cta-float { animation: cta-float 1.6s ease-out both }
  .cta-confetti { animation: cta-confetti 1.4s ease-in both }
}
@media (prefers-reduced-motion: reduce) {
  .cta-float { opacity: 1 }
}
`}</style>
);

export const Spinner: React.FC<{ label?: string; className?: string }> = ({ label, className = '' }) => (
  <span className={`inline-flex items-center gap-2 ${className}`}>
    <LoaderCircle className="w-4 h-4 motion-safe:animate-spin" aria-hidden="true" />
    {label && <span>{label}</span>}
  </span>
);

export const card = 'bg-white border border-gray-200 rounded-2xl';

const btnBase =
  'inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl font-semibold transition-colors ' +
  'disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-4 ';

/** Brand button (AgenticTA red, COLORS.primary). */
export const primaryBtn = btnBase + 'text-white bg-[#ba3638] hover:bg-[#a32f31] focus-visible:ring-[#ba3638]/30';

/** "Got it" / success actions. */
export const successBtn = btnBase + 'text-white bg-green-600 hover:bg-green-700 focus-visible:ring-green-600/30';

export const secondaryBtn = btnBase + 'text-gray-800 bg-white border border-gray-300 hover:bg-gray-50 focus-visible:ring-gray-300';

export const textInput =
  'w-full px-3 py-2.5 border border-gray-300 rounded-xl text-base sm:text-sm bg-white ' +
  'focus:outline-none focus:ring-2 focus:ring-[#ba3638]/30 focus:border-[#ba3638] disabled:bg-gray-50';
