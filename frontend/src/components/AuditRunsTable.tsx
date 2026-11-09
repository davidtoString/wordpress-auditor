import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ExternalLink,
  Clock,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Calendar,
  Zap,
  XCircle,
} from 'lucide-react'
import type { Audit } from '../lib/types'
import { formatRelative, formatDate, moduleDisplayName } from '../lib/utils'
import { describeRunKind, RUN_KIND_CLASSES, SCOPE_LABELS } from '../lib/auditKinds'
import ScoreBadge from './ScoreBadge'

interface AuditRunsTableProps {
  audits: Audit[]
  isLoading?: boolean
  showSiteName?: boolean
  emptyMessage?: string
}

export const AuditRunsTable: React.FC<AuditRunsTableProps> = ({
  audits,
  isLoading = false,
  showSiteName = true,
  emptyMessage = 'No audit runs recorded yet.',
}) => {
  const navigate = useNavigate()

  const formatDuration = (seconds?: number | null) => {
    if (seconds === null || seconds === undefined) return '—'
    if (seconds < 60) return `${Math.round(seconds)}s`
    const mins = Math.floor(seconds / 60)
    const secs = Math.round(seconds % 60)
    return `${mins}m ${secs}s`
  }

  const renderStatus = (status: string) => {
    switch (status?.toLowerCase()) {
      case 'completed':
        return (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 className="w-3.5 h-3.5" />
            Completed
          </span>
        )
      case 'running':
        return (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 dark:text-blue-400">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Running...
          </span>
        )
      case 'pending':
        return (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 dark:text-slate-400">
            <Clock className="w-3.5 h-3.5" />
            Queued
          </span>
        )
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-rose-600 dark:text-rose-400">
            <AlertCircle className="w-3.5 h-3.5" />
            Failed
          </span>
        )
      case 'cancelled':
        return (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 dark:text-slate-400">
            <XCircle className="w-3.5 h-3.5" />
            Cancelled
          </span>
        )
      default:
        return (
          <span className="text-xs font-medium text-slate-500 capitalize">
            {status || 'Unknown'}
          </span>
        )
    }
  }

  const renderTriggeredBy = (triggered: string) => {
    const isCron = triggered?.toLowerCase().includes('schedule') || triggered?.toLowerCase().includes('cron')
    return (
      <span className="inline-flex items-center gap-1 text-xs text-slate-600 dark:text-slate-300">
        {isCron ? (
          <Calendar className="w-3 h-3 text-slate-400" />
        ) : (
          <Zap className="w-3 h-3 text-amber-500" />
        )}
        <span className="truncate max-w-[120px]">{triggered || 'System'}</span>
      </span>
    )
  }

  if (isLoading) {
    return (
      <div className="w-full bg-white dark:bg-slate-800/90 rounded-xl border border-slate-200 dark:border-slate-700/80 p-8 flex flex-col items-center justify-center">
        <Loader2 className="w-8 h-8 text-brand-600 animate-spin mb-3" />
        <p className="text-sm text-slate-500 dark:text-slate-400">Loading audit records...</p>
      </div>
    )
  }

  if (!audits || audits.length === 0) {
    return (
      <div className="w-full bg-white dark:bg-slate-800/90 rounded-xl border border-slate-200 dark:border-slate-700/80 p-12 text-center">
        <div className="w-12 h-12 rounded-full bg-slate-100 dark:bg-slate-700/50 flex items-center justify-center mx-auto mb-3 text-slate-400">
          <Clock className="w-6 h-6" />
        </div>
        <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-1">
          {emptyMessage}
        </h4>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Audit runs will automatically appear here once scheduled or manually triggered.
        </p>
      </div>
    )
  }

  return (
    <div className="w-full bg-white dark:bg-slate-800/90 rounded-xl border border-slate-200 dark:border-slate-700/80 shadow-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-700/80 bg-slate-50/75 dark:bg-slate-900/40 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              {showSiteName && <th className="py-3 px-4">Site</th>}
              <th className="py-3 px-4">Score</th>
              <th className="py-3 px-4">Status</th>
              <th className="py-3 px-4">Triggered By</th>
              <th className="py-3 px-4">Started</th>
              <th className="py-3 px-4">Duration</th>
              <th className="py-3 px-4 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
            {audits.map((audit) => (
              <tr
                key={audit.id}
                className="hover:bg-slate-50/60 dark:hover:bg-slate-700/30 transition-colors cursor-pointer group"
                onClick={() => navigate(`/audits/${audit.id}`)}
              >
                {showSiteName && (
                  <td className="py-3.5 px-4 font-medium text-slate-900 dark:text-slate-100">
                    <Link
                      to={`/sites/${audit.site_id}`}
                      onClick={(e) => e.stopPropagation()}
                      className="text-brand-600 dark:text-brand-400 hover:underline flex items-center gap-1 max-w-[200px] truncate"
                    >
                      {audit.site_name || `Site #${audit.site_id}`}
                    </Link>
                    {audit.site_url && (
                      <span className="text-[11px] text-slate-400 block truncate max-w-[200px]">
                        {audit.site_url}
                      </span>
                    )}
                  </td>
                )}
                <td className="py-3.5 px-4">
                  <div className="flex flex-col gap-1">
                    <ScoreBadge score={audit.score} size="sm" showLabel />
                    {audit.brief_stats && (
                      <div className="flex flex-wrap gap-1">
                        {audit.brief_stats.urgent > 0 && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300" title="Open urgent findings">
                            {audit.brief_stats.urgent} urgent{audit.brief_stats.urgent_new ? ` (${audit.brief_stats.urgent_new} new)` : ''}
                          </span>
                        )}
                        {audit.brief_stats.changes_notable > 0 && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300" title="Notable changes since the previous run">
                            {audit.brief_stats.changes_notable} changed
                          </span>
                        )}
                        {audit.brief_stats.resolved > 0 && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
                            {audit.brief_stats.resolved} resolved
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </td>
                <td className="py-3.5 px-4">
                  <div className="flex flex-col gap-0.5">
                    {renderStatus(audit.status)}
                    {(() => {
                      const kind = describeRunKind(audit)
                      if (kind.tone === 'partial') return null
                      return (
                        <span
                          className={`inline-flex w-fit items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${RUN_KIND_CLASSES[kind.tone]}`}
                          title={`${SCOPE_LABELS[audit.scope] || audit.scope}${kind.tone === 'visual' ? ' · with screenshots and vision review' : ' · no screenshots'}`}
                        >
                          {kind.label}
                        </span>
                      )
                    })()}
                    {audit.modules && audit.modules.length > 0 && (
                      <span
                        className="inline-flex w-fit items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-violet-50 dark:bg-violet-950/40 text-violet-700 dark:text-violet-300"
                        title={audit.modules.map((m) => moduleDisplayName(m)).join(', ')}
                      >
                        Partial · {audit.modules.length === 1 ? moduleDisplayName(audit.modules[0]) : `${audit.modules.length} modules`}
                      </span>
                    )}
                  </div>
                </td>
                <td className="py-3.5 px-4">{renderTriggeredBy(audit.triggered_by)}</td>
                <td className="py-3.5 px-4">
                  <span
                    className="text-slate-700 dark:text-slate-300 text-xs"
                    title={formatDate(audit.started_at)}
                  >
                    {formatRelative(audit.started_at)}
                  </span>
                </td>
                <td className="py-3.5 px-4 text-xs font-mono text-slate-600 dark:text-slate-400">
                  {formatDuration(audit.duration_seconds)}
                </td>
                <td className="py-3.5 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                  <Link
                    to={`/audits/${audit.id}`}
                    className="inline-flex items-center gap-1 px-3 py-1 text-xs font-medium text-brand-600 dark:text-brand-400 bg-brand-50 dark:bg-brand-950/50 hover:bg-brand-100 dark:hover:bg-brand-900/60 rounded-md transition-colors"
                  >
                    View
                    <ExternalLink className="w-3 h-3" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default AuditRunsTable
