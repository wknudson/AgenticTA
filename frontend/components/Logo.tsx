import React from 'react';
import { COLORS } from '../constants';

/** The AgenticTA logo: the brain-and-cap mark plus the wordmark as live text (sharp at any size). */
interface LogoProps {
  size?: 'sm' | 'md' | 'lg';
  /** Mark above the name, for login screens. */
  stacked?: boolean;
  className?: string;
}

const SIZES = {
  sm: { mark: 'h-8 sm:h-9', text: 'text-xl sm:text-2xl', gap: 'gap-2' },
  md: { mark: 'h-9 sm:h-11', text: 'text-2xl sm:text-[28px]', gap: 'gap-2.5' },
  lg: { mark: 'h-20', text: 'text-4xl', gap: 'gap-2' },
};

const Logo: React.FC<LogoProps> = ({ size = 'md', stacked = false, className = '' }) => {
  const s = SIZES[size];
  return (
    <span
      className={`inline-flex items-center ${stacked ? 'flex-col' : ''} ${s.gap} ${className}`}
      role="img"
      aria-label="AgenticTA"
    >
      <img src="/img/agenticta-mark.png" alt="" className={`${s.mark} w-auto object-contain`} />
      <span className={`${s.text} font-extrabold tracking-tight leading-none whitespace-nowrap`} aria-hidden="true">
        <span style={{ color: COLORS.primary }}>Agentic</span>
        <span className="text-slate-900">TA</span>
      </span>
    </span>
  );
};

export default Logo;
