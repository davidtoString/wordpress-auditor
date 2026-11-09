import React, { useState } from 'react'
import { Clock } from 'lucide-react'
import { DEFAULT_SCHEDULE, WEEKDAYS, buildCron, describeCron, parseCron, type SimpleSchedule } from '../lib/cron'
import type { ScheduleScope } from '../lib/types'
import { SCOPE_HINTS, SCOPE_LABELS } from '../lib/auditKinds'

interface SchedulePickerProps {
  title: string
  description: string
  /** Five-field cron, or '' when the schedule is off. */
  cron: string
  onCronChange: (cron: string) => void
  /** Whether this schedule is on. Off keeps the last cron so turning it back on restores it. */
  enabled: boolean
  onEnabledChange: (enabled: boolean) => void
  scope: ScheduleScope
  onScopeChange: (scope: ScheduleScope) => void
  /** Preset used when the picker has no cron yet (e.g. the schedule was off). */
  fallback: SimpleSchedule
  scopeNote?: string
}

const SCOPES: { value: ScheduleScope; label: string; hint: string }[] = [
  { value: 'with_posts', label: SCOPE_LABELS.with_posts, hint: SCOPE_HINTS.with_posts },
  { value: 'full', label: SCOPE_LABELS.full, hint: SCOPE_HINTS.full },
]

export const SchedulePicker: React.FC<SchedulePickerProps> = ({
  title, description, cron, onCronChange, enabled, onEnabledChange, scope, onScopeChange, fallback, scopeNote,
}) => {
  const [showRaw, setShowRaw] = useState(false)
  const simple = parseCron(cron)
  const base: SimpleSchedule = simple ?? fallback ?? DEFAULT_SCHEDULE
  const set = (patch: Partial<SimpleSchedule>) => {
    onCronChange(buildCron({ ...base, ...patch }))
    onEnabledChange(true)
  }
  const isKind = (kind: SimpleSchedule['kind'], dow?: number) =>
    enabled && !!simple && simple.kind === kind && (dow === undefined || simple.dow === dow)
  const chip = (active: boolean) =>
    `text-xs px-2.5 py-1 rounded-lg border transition-colors ${
      active
        ? 'bg-brand-50 dark:bg-brand-950/60 border-brand-500 text-brand-600 dark:text-brand-400 font-semibold'
        : 'border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400'
    }`
  const selectClass =
    'px-2.5 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50'

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700/80 p-4 space-y-3">
      <div>
        <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</div>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{description}</p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => set({ kind: 'daily' })} className={chip(isKind('daily'))}>
          Every day
        </button>
        {WEEKDAYS.map((w) => (
          <button
            key={w.value}
            type="button"
            onClick={() => set({ kind: 'weekly', dow: w.value })}
            className={chip(isKind('weekly', w.value))}
            title={`Every ${w.label}`}
          >
            {w.short}
          </button>
        ))}
        <button type="button" onClick={() => set({ kind: 'weekdays' })} className={chip(isKind('weekdays'))}>
          Weekdays
        </button>
        <button type="button" onClick={() => set({ kind: 'monthly', dom: base.dom || 1 })} className={chip(isKind('monthly'))}>
          Monthly
        </button>
        <button
          type="button"
          onClick={() => onEnabledChange(false)}
          className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
            !enabled
              ? 'bg-slate-200 dark:bg-slate-700 border-slate-400 dark:border-slate-500 text-slate-700 dark:text-slate-200 font-semibold'
              : 'border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400'
          }`}
        >
          Manual only
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-slate-400" />
          {isKind('monthly') && (
            <>
              <span className="text-xs text-slate-500">on the</span>
              <select value={base.dom} disabled={!enabled} onChange={(e) => set({ dom: Number(e.target.value) })} className={selectClass}>
                {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </>
          )}
          <span className="text-xs text-slate-500">at</span>
          <select value={base.hour} disabled={!enabled || !simple} onChange={(e) => set({ hour: Number(e.target.value) })} className={selectClass}>
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>
                {h % 12 === 0 ? 12 : h % 12} {h < 12 ? 'AM' : 'PM'}
              </option>
            ))}
          </select>
          <select value={base.minute} disabled={!enabled || !simple} onChange={(e) => set({ minute: Number(e.target.value) })} className={selectClass}>
            {[0, 15, 30, 45].map((m) => (
              <option key={m} value={m}>:{String(m).padStart(2, '0')}</option>
            ))}
          </select>
        </div>
        <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
          {enabled ? describeCron(cron) : 'Manual only'}
        </span>
        <button
          type="button"
          onClick={() => setShowRaw((v) => !v)}
          className="ml-auto text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 underline-offset-2 hover:underline"
        >
          {showRaw ? 'Hide cron expression' : 'Edit cron expression'}
        </button>
      </div>

      {(showRaw || (enabled && !simple)) && (
        <div>
          <input
            type="text"
            required={enabled}
            disabled={!enabled}
            value={cron}
            onChange={(e) => onCronChange(e.target.value)}
            placeholder="0 6 * * 1"
            className="w-full px-3.5 py-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50 disabled:cursor-not-allowed"
          />
          <p className="text-xs text-slate-400 mt-1">
            Five fields: minute hour day-of-month month day-of-week (0 = Sunday). Expressions outside the presets are kept as typed.
          </p>
        </div>
      )}

      <div>
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-1.5">Pages to audit</div>
        <div className="flex flex-wrap gap-2">
          {SCOPES.map((s) => (
            <button
              key={s.value}
              type="button"
              onClick={() => onScopeChange(s.value)}
              title={s.hint}
              className={chip(scope === s.value)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-slate-400 mt-1.5">
          {SCOPES.find((s) => s.value === scope)?.hint}
          {scopeNote ? ` ${scopeNote}` : ''}
        </p>
      </div>
    </div>
  )
}

export default SchedulePicker
