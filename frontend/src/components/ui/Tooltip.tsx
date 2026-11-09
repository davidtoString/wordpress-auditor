import React from 'react'

interface TooltipProps {
  /** Rich content shown on hover or keyboard focus. */
  content: React.ReactNode
  children: React.ReactNode
  /** Where the card opens relative to the trigger. */
  side?: 'top' | 'bottom'
  align?: 'start' | 'end' | 'center'
  className?: string
}

/** Hover/focus tooltip card. Pure CSS (group-hover) so it works without extra state. */
export const Tooltip: React.FC<TooltipProps> = ({ content, children, side = 'bottom', align = 'end', className = '' }) => {
  const pos = side === 'top' ? 'bottom-full mb-2' : 'top-full mt-2'
  const horiz = align === 'start' ? 'left-0' : align === 'center' ? 'left-1/2 -translate-x-1/2' : 'right-0'
  return (
    <span className={`relative inline-flex group/tip ${className}`}>
      {children}
      <span
        role="tooltip"
        className={`pointer-events-none absolute z-30 ${pos} ${horiz} w-72 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-3 text-left text-xs leading-relaxed text-slate-600 dark:text-slate-300 shadow-xl opacity-0 translate-y-1 transition-all duration-150 group-hover/tip:opacity-100 group-hover/tip:translate-y-0 group-focus-within/tip:opacity-100 group-focus-within/tip:translate-y-0`}
      >
        {content}
      </span>
    </span>
  )
}

export default Tooltip
