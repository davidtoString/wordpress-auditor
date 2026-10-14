import React from 'react'
import { cn, scoreToLabel } from '../lib/utils'

interface ScoreBadgeProps {
  score: number | null | undefined
  size?: 'sm' | 'md' | 'lg' | 'xl'
  showLabel?: boolean
  className?: string
}

export const ScoreBadge: React.FC<ScoreBadgeProps> = ({
  score,
  size = 'md',
  showLabel = false,
  className,
}) => {
  const getColors = (val: number | null | undefined) => {
    if (val === null || val === undefined) {
      return {
        bg: 'bg-slate-100 dark:bg-slate-800',
        text: 'text-slate-600 dark:text-slate-400',
        border: 'border-slate-200 dark:border-slate-700',
        ring: 'ring-slate-400/20',
      }
    }
    if (val >= 80) {
      return {
        bg: 'bg-emerald-50 dark:bg-emerald-950/50',
        text: 'text-emerald-700 dark:text-emerald-300',
        border: 'border-emerald-200 dark:border-emerald-800/70',
        ring: 'ring-emerald-500/20',
      }
    }
    if (val >= 60) {
      return {
        bg: 'bg-amber-50 dark:bg-amber-950/50',
        text: 'text-amber-700 dark:text-amber-300',
        border: 'border-amber-200 dark:border-amber-800/70',
        ring: 'ring-amber-500/20',
      }
    }
    if (val >= 40) {
      return {
        bg: 'bg-orange-50 dark:bg-orange-950/50',
        text: 'text-orange-700 dark:text-orange-300',
        border: 'border-orange-200 dark:border-orange-800/70',
        ring: 'ring-orange-500/20',
      }
    }
    return {
      bg: 'bg-rose-50 dark:bg-rose-950/50',
      text: 'text-rose-700 dark:text-rose-300',
      border: 'border-rose-200 dark:border-rose-800/70',
      ring: 'ring-rose-500/20',
    }
  }

  const colors = getColors(score)
  const label = scoreToLabel(score)

  const sizeStyles = {
    sm: 'text-xs px-2 py-0.5 gap-1',
    md: 'text-sm px-2.5 py-1 gap-1.5',
    lg: 'text-base px-3 py-1.5 gap-2 font-semibold',
    xl: 'text-xl px-4 py-2 gap-2.5 font-bold',
  }

  const formattedScore = score !== null && score !== undefined ? Math.round(score) : '—'

  return (
    <span
      className={cn(
        'inline-flex items-center justify-center font-medium rounded-full border transition-colors',
        colors.bg,
        colors.text,
        colors.border,
        sizeStyles[size],
        className
      )}
    >
      <span className="font-mono tabular-nums">{formattedScore}</span>
      {score !== null && score !== undefined && <span className="opacity-70 text-[0.8em]">/100</span>}
      {showLabel && (
        <span className="ml-1 text-[0.85em] font-normal opacity-90 border-l border-current/30 pl-1.5">
          {label}
        </span>
      )}
    </span>
  )
}

export default ScoreBadge
