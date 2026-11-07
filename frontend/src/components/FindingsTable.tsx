import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, ListChecks, Loader2 } from 'lucide-react'
import { sites as sitesApi } from '../lib/api'
import type { Finding } from '../lib/types'
import { cn, formatDate, formatRelative } from '../lib/utils'
import { SeverityPill } from './BriefPanel'

const shortUrl = (url?: string | null) => {
  if (!url) return null
  try {
    const u = new URL(url)
    return u.pathname + u.search || '/'
  } catch {
    return url
  }
}

export const FindingsTable: React.FC<{ siteId: string }> = ({ siteId }) => {
  const [status, setStatus] = useState<'open' | 'resolved'>('open')
  const [section, setSection] = useState<'all' | 'urgent' | 'improve'>('all')
  const { data = [], isLoading } = useQuery<Finding[]>({
    queryKey: ['site-findings', siteId, status],
    queryFn: () => sitesApi.getFindings(siteId, status),
  })
  const rows = data.filter((f) => section === 'all' || f.section === section)

  const Tab: React.FC<{ active: boolean; onClick: () => void; children: React.ReactNode }> = ({ active, onClick, children }) => (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'px-2.5 py-1 text-xs font-semibold rounded-lg transition-colors',
        active
          ? 'bg-white dark:bg-slate-700 text-brand-600 dark:text-brand-400 shadow-sm'
          : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
      )}
    >
      {children}
    </button>
  )

  return (
    <div id="findings" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <ListChecks className="w-5 h-5 text-brand-500" />
            Findings
          </h3>
          <p className="text-xs text-slate-500">
            Every concrete problem found, tracked from the run that first saw it until the run that no longer did.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-900/60">
            <Tab active={status === 'open'} onClick={() => setStatus('open')}>Open</Tab>
            <Tab active={status === 'resolved'} onClick={() => setStatus('resolved')}>Resolved</Tab>
          </div>
          <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-900/60">
            <Tab active={section === 'all'} onClick={() => setSection('all')}>All</Tab>
            <Tab active={section === 'urgent'} onClick={() => setSection('urgent')}>Urgent</Tab>
            <Tab active={section === 'improve'} onClick={() => setSection('improve')}>Improve</Tab>
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-800/90 rounded-xl border border-slate-200 dark:border-slate-700/80 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="p-8 flex items-center justify-center text-slate-500 text-sm gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading findings…
          </div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            {status === 'open' ? 'No open findings in this category.' : 'Nothing resolved yet.'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700/80 bg-slate-50/75 dark:bg-slate-900/40 text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  <th className="py-2.5 px-4">Severity</th>
                  <th className="py-2.5 px-4">Finding</th>
                  <th className="py-2.5 px-4">Module</th>
                  <th className="py-2.5 px-4">First seen</th>
                  <th className="py-2.5 px-4">{status === 'open' ? 'Last seen' : 'Resolved'}</th>
                  <th className="py-2.5 px-4 text-right">Runs</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
                {rows.map((f) => (
                  <tr key={f.id} className="hover:bg-slate-50/60 dark:hover:bg-slate-700/30">
                    <td className="py-2.5 px-4"><SeverityPill severity={f.severity} /></td>
                    <td className="py-2.5 px-4">
                      <div className="text-slate-800 dark:text-slate-100 leading-snug">{f.title}</div>
                      {f.url && (
                        <a
                          href={f.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[11px] font-mono text-slate-500 hover:text-brand-600 inline-flex items-center gap-1 max-w-[420px] truncate"
                          title={f.url}
                        >
                          {shortUrl(f.url)}
                          <ExternalLink className="w-3 h-3 shrink-0" />
                        </a>
                      )}
                    </td>
                    <td className="py-2.5 px-4 text-xs text-slate-500 dark:text-slate-400 whitespace-nowrap">{f.module.replace(/_/g, ' ')}</td>
                    <td className="py-2.5 px-4 text-xs text-slate-600 dark:text-slate-300 whitespace-nowrap" title={formatDate(f.first_seen_at)}>
                      {formatRelative(f.first_seen_at)}
                    </td>
                    <td className="py-2.5 px-4 text-xs text-slate-600 dark:text-slate-300 whitespace-nowrap">
                      {status === 'open' ? formatRelative(f.last_seen_at) : f.resolved_at ? formatRelative(f.resolved_at) : '—'}
                    </td>
                    <td className="py-2.5 px-4 text-xs text-right font-mono text-slate-500">{f.times_seen}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default FindingsTable
