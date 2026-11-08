import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertOctagon,
  ArrowLeftRight,
  BellOff,
  EyeOff,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  Info,
  Sparkles,
  Wrench,
} from 'lucide-react'
import type { AuditBrief, BriefItem, BriefChange } from '../lib/types'
import { cn, formatDate } from '../lib/utils'

const SEV_CLASS: Record<string, string> = {
  critical: 'bg-rose-200 text-rose-900 dark:bg-rose-950/70 dark:text-rose-200',
  high: 'bg-rose-100 text-rose-800 dark:bg-rose-950/50 dark:text-rose-300',
  medium: 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300',
  low: 'bg-sky-100 text-sky-800 dark:bg-sky-950/50 dark:text-sky-300',
  info: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
}

export const SeverityPill: React.FC<{ severity: string; className?: string }> = ({ severity, className }) => (
  <span
    className={cn(
      'shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide',
      SEV_CLASS[severity] || SEV_CLASS.info,
      className
    )}
  >
    {severity}
  </span>
)

const shortUrl = (url?: string | null) => {
  if (!url) return null
  try {
    const u = new URL(url)
    return u.pathname + u.search || '/'
  } catch {
    return url
  }
}

const ItemRow: React.FC<{ item: BriefItem }> = ({ item }) => {
  const [open, setOpen] = useState(false)
  const hasDetail = item.detail && Object.keys(item.detail).length > 0
  return (
    <li className="py-2 border-b border-slate-100 dark:border-slate-700/60 last:border-0">
      <div className="flex items-start gap-2">
        <SeverityPill severity={item.severity} className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="text-sm text-slate-800 dark:text-slate-100 leading-snug">{item.title}</span>
            {item.is_new && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
                NEW
              </span>
            )}
            {!item.is_new && item.first_seen_at && (
              <span className="text-[11px] text-slate-400">since {formatDate(item.first_seen_at).slice(0, 12)}</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-x-3 text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
            <span className="uppercase tracking-wide text-[10px]">{item.module.replace(/_/g, ' ')}</span>
            {item.url && (
              <a
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="font-mono truncate max-w-[360px] hover:text-brand-600 inline-flex items-center gap-1"
                title={item.url}
              >
                {shortUrl(item.url)}
                <ExternalLink className="w-3 h-3" />
              </a>
            )}
            {hasDetail && (
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="inline-flex items-center gap-0.5 text-brand-600 dark:text-brand-400 hover:underline"
              >
                details
                <ChevronDown className={cn('w-3 h-3 transition-transform', open && 'rotate-180')} />
              </button>
            )}
          </div>
          {open && hasDetail && (
            <pre className="mt-1.5 text-[10px] leading-relaxed bg-slate-50 dark:bg-slate-900/60 border border-slate-200/70 dark:border-slate-800 rounded p-2 overflow-x-auto max-h-56 text-slate-700 dark:text-slate-300 whitespace-pre-wrap break-words">
              {JSON.stringify(item.detail, null, 2)}
            </pre>
          )}
        </div>
      </div>
    </li>
  )
}

const ChangeRow: React.FC<{ change: BriefChange }> = ({ change }) => {
  const d = change.detail || {}
  const beforeAfter =
    d.before !== undefined && d.after !== undefined ? (
      <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400 break-all">
        {String(d.before)} → {String(d.after)}
      </span>
    ) : null
  return (
    <li className="py-2 border-b border-slate-100 dark:border-slate-700/60 last:border-0 flex items-start gap-2">
      <SeverityPill severity={change.severity} className="mt-0.5" />
      <div className="min-w-0">
        <span className="text-sm text-slate-800 dark:text-slate-100 leading-snug">{change.title}</span>
        {beforeAfter && <div>{beforeAfter}</div>}
        {d.url && (
          <a href={String(d.url)} target="_blank" rel="noreferrer" className="block text-[11px] font-mono text-slate-500 hover:text-brand-600 truncate max-w-[420px]">
            {shortUrl(String(d.url))}
          </a>
        )}
      </div>
    </li>
  )
}

interface BriefPanelProps {
  brief: AuditBrief
  narrative?: string | null
  siteId?: string
  compact?: boolean
}

export const BriefPanel: React.FC<BriefPanelProps> = ({ brief, narrative, siteId, compact = false }) => {
  const [showAllImprove, setShowAllImprove] = useState(false)
  const urgent = brief.urgent || []
  const changes = brief.changes || []
  const improve = brief.improve || []
  const resolved = brief.resolved || []
  const muted = brief.muted || []
  const unconfirmed = brief.unconfirmed || []
  const notes = brief.notes || []
  const [showMuted, setShowMuted] = useState(false)
  const improveShown = showAllImprove ? improve : improve.slice(0, compact ? 6 : 12)

  const Section: React.FC<{
    icon: React.ReactNode
    title: string
    count?: number
    tone: string
    children: React.ReactNode
  }> = ({ icon, title, count, tone, children }) => (
    <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 shadow-sm p-5">
      <div className={cn('flex items-center gap-2 font-bold text-sm mb-1', tone)}>
        {icon}
        <span>{title}</span>
        {typeof count === 'number' && (
          <span className="ml-auto text-xs font-semibold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
            {count}
          </span>
        )}
      </div>
      {children}
    </div>
  )

  return (
    <div className="space-y-4">
      {narrative && (
        <div className="bg-gradient-to-br from-brand-500/10 via-purple-500/5 to-transparent rounded-2xl border border-brand-200 dark:border-brand-900/60 p-5 shadow-sm">
          <div className="flex items-center gap-2 text-brand-900 dark:text-brand-200 font-bold text-sm mb-2">
            <Sparkles className="w-4 h-4" />
            What needs your attention
          </div>
          <p className="text-sm leading-relaxed text-slate-700 dark:text-slate-200 whitespace-pre-line">{narrative}</p>
        </div>
      )}

      <div className={cn('grid gap-4', compact ? 'grid-cols-1' : 'grid-cols-1 lg:grid-cols-2')}>
        <Section
          icon={<AlertOctagon className="w-4 h-4" />}
          title="Broken or urgent now"
          count={urgent.length}
          tone="text-rose-700 dark:text-rose-300"
        >
          {urgent.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-slate-400 flex items-center gap-1.5 mt-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-500" /> Nothing urgent.
            </p>
          ) : (
            <ul>{urgent.map((i) => <ItemRow key={i.fingerprint} item={i} />)}</ul>
          )}
        </Section>

        <Section
          icon={<ArrowLeftRight className="w-4 h-4" />}
          title={`Changed since last run${brief.compared_to_at ? ` (${formatDate(brief.compared_to_at).slice(0, 12)})` : ''}`}
          count={changes.length}
          tone="text-amber-700 dark:text-amber-300"
        >
          {changes.length === 0 ? (
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-2">
              {brief.first_run ? 'First run: nothing to compare against yet.' : 'No changes detected.'}
            </p>
          ) : (
            <ul>{changes.map((c, idx) => <ChangeRow key={idx} change={c} />)}</ul>
          )}
          {resolved.length > 0 && (
            <div className="mt-3 pt-2 border-t border-emerald-100 dark:border-emerald-900/50">
              <div className="text-xs font-bold text-emerald-700 dark:text-emerald-300 mb-1 flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5" /> Resolved ({resolved.length})
              </div>
              <ul className="space-y-0.5">
                {resolved.slice(0, 10).map((r, idx) => (
                  <li key={idx} className="text-xs text-slate-600 dark:text-slate-300 line-through decoration-emerald-400/70">
                    {r.title}
                  </li>
                ))}
                {resolved.length > 10 && <li className="text-[11px] text-slate-400">and {resolved.length - 10} more</li>}
              </ul>
            </div>
          )}
        </Section>
      </div>

      <Section
        icon={<Wrench className="w-4 h-4" />}
        title="Improve"
        count={improve.length}
        tone="text-sky-700 dark:text-sky-300"
      >
        {improve.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-2">Nothing outstanding.</p>
        ) : (
          <>
            <ul>{improveShown.map((i) => <ItemRow key={i.fingerprint} item={i} />)}</ul>
            {improve.length > improveShown.length && (
              <button
                type="button"
                onClick={() => setShowAllImprove(true)}
                className="mt-2 text-xs font-semibold text-brand-600 dark:text-brand-400 hover:underline"
              >
                Show all {improve.length}
              </button>
            )}
            {siteId && (
              <Link to={`/sites/${siteId}#findings`} className="ml-3 text-xs text-slate-500 hover:text-brand-600">
                Open findings history
              </Link>
            )}
          </>
        )}
      </Section>

      {muted.length > 0 && (
        <div className="text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800 rounded-xl px-4 py-3">
          <button type="button" onClick={() => setShowMuted((v) => !v)} className="flex items-center gap-2 font-semibold hover:text-slate-700 dark:hover:text-slate-200">
            <BellOff className="w-4 h-4" />
            {muted.length} acknowledged, snoozed or accepted (tracked, not alerting)
            <ChevronDown className={cn('w-3 h-3 transition-transform', showMuted && 'rotate-180')} />
          </button>
          {showMuted && (
            <ul className="mt-2 space-y-1">
              {muted.map((i) => (
                <li key={i.fingerprint} className="flex items-center gap-2">
                  <SeverityPill severity={i.severity} />
                  <span className="text-slate-600 dark:text-slate-300">{i.title}</span>
                  <span className="text-[10px] uppercase tracking-wide text-slate-400">{i.mute_kind}{i.mute_until ? ` until ${formatDate(i.mute_until).slice(0, 12)}` : ''}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {unconfirmed.length > 0 && (
        <div className="flex items-start gap-2 text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800 rounded-xl px-4 py-3">
          <EyeOff className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold">Seen once, not reproduced on re-check (not reported):</span>{' '}
            {unconfirmed.map((u, i) => (
              <span key={i}>
                {u.title}
                {i < unconfirmed.length - 1 ? ' · ' : ''}
              </span>
            ))}
          </div>
        </div>
      )}

      {notes.length > 0 && (
        <div className="flex items-start gap-2 text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800 rounded-xl px-4 py-3">
          <Info className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold">Not measured this run:</span>{' '}
            {notes.map((n, i) => (
              <span key={i}>
                {n}
                {i < notes.length - 1 ? ' · ' : ''}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default BriefPanel
