import React, { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BellOff, Check, Clock, ExternalLink, ListChecks, Loader2, RotateCcw, ShieldCheck, Undo2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { sites as sitesApi } from '../lib/api'
import type { Finding, MuteKind } from '../lib/types'
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

const MUTE_LABEL: Record<MuteKind, string> = {
  acknowledged: 'Acknowledged',
  snoozed: 'Snoozed',
  accepted: 'Accepted risk',
}

export const MuteBadge: React.FC<{ kind?: MuteKind | null; until?: string | null; note?: string | null }> = ({ kind, until, note }) => {
  if (!kind) return null
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300"
      title={[note, until ? `until ${formatDate(until).slice(0, 12)}` : ''].filter(Boolean).join(' · ')}
    >
      <BellOff className="w-3 h-3" />
      {MUTE_LABEL[kind]}
      {kind === 'snoozed' && until ? ` until ${formatDate(until).slice(0, 12)}` : ''}
    </span>
  )
}

export const FindingsTable: React.FC<{ siteId: string }> = ({ siteId }) => {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<'open' | 'muted' | 'resolved'>('open')
  const [section, setSection] = useState<'all' | 'urgent' | 'improve'>('all')
  const [busyId, setBusyId] = useState<string | null>(null)
  const { data = [], isLoading } = useQuery<Finding[]>({
    queryKey: ['site-findings', siteId, status],
    queryFn: () => sitesApi.getFindings(siteId, status),
  })
  const rows = data.filter((f) => section === 'all' || f.section === section)

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['site-findings', siteId] })
    queryClient.invalidateQueries({ queryKey: ['sites'] })
    queryClient.invalidateQueries({ queryKey: ['site', siteId] })
  }

  const muteMutation = useMutation({
    mutationFn: ({ id, kind, days }: { id: string; kind: MuteKind; days?: number }) => {
      let note: string | null = null
      if (kind === 'accepted') note = window.prompt('Why is this risk accepted? (optional, shown with the finding)') ?? ''
      return sitesApi.muteFinding(siteId, id, kind, days, note || undefined)
    },
    onMutate: ({ id }) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (_f, { kind }) => {
      toast.success(kind === 'snoozed' ? 'Snoozed for 30 days' : kind === 'accepted' ? 'Marked as accepted risk' : 'Acknowledged')
      refresh()
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Could not update finding'),
  })
  const unmuteMutation = useMutation({
    mutationFn: (id: string) => sitesApi.unmuteFinding(siteId, id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: () => {
      toast.success('Back on the list')
      refresh()
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Could not update finding'),
  })
  const verifyMutation = useMutation({
    mutationFn: (id: string) => sitesApi.verifyFinding(siteId, id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (res) => {
      toast.success(res.message || 'Re-check queued')
      queryClient.invalidateQueries({ queryKey: ['site-history', siteId] })
      queryClient.invalidateQueries({ queryKey: ['audits'] })
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Could not queue the re-check'),
  })

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

  const ActionBtn: React.FC<{ title: string; onClick: () => void; disabled?: boolean; children: React.ReactNode; tone?: string }> = ({
    title,
    onClick,
    disabled,
    children,
    tone,
  }) => (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold border transition-colors disabled:opacity-50',
        tone || 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/60'
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
            Every concrete problem found, tracked from the run that first saw it until the run that no longer did. Acknowledge, snooze or
            accept an item to keep it tracked without alerts; verify re-runs just its module.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-900/60">
            <Tab active={status === 'open'} onClick={() => setStatus('open')}>Open</Tab>
            <Tab active={status === 'muted'} onClick={() => setStatus('muted')}>Muted</Tab>
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
            {status === 'open' ? 'No open findings in this category.' : status === 'muted' ? 'Nothing muted.' : 'Nothing resolved yet.'}
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
                  <th className="py-2.5 px-4">{status === 'resolved' ? 'Resolved' : 'Last seen'}</th>
                  {status !== 'resolved' && <th className="py-2.5 px-4 text-right">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-700/50">
                {rows.map((f) => {
                  const busy = busyId === f.id
                  return (
                    <tr key={f.id} className="hover:bg-slate-50/60 dark:hover:bg-slate-700/30">
                      <td className="py-2.5 px-4"><SeverityPill severity={f.severity} /></td>
                      <td className="py-2.5 px-4">
                        <div className="text-slate-800 dark:text-slate-100 leading-snug">{f.title}</div>
                        <div className="flex flex-wrap items-center gap-2 mt-0.5">
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
                          {f.is_muted && <MuteBadge kind={f.mute_kind} until={f.mute_until} note={f.mute_note} />}
                          {f.is_muted && f.mute_note && <span className="text-[11px] text-slate-500 italic">“{f.mute_note}”</span>}
                        </div>
                      </td>
                      <td className="py-2.5 px-4 text-xs text-slate-500 dark:text-slate-400 whitespace-nowrap">{f.module.replace(/_/g, ' ')}</td>
                      <td className="py-2.5 px-4 text-xs text-slate-600 dark:text-slate-300 whitespace-nowrap" title={formatDate(f.first_seen_at)}>
                        {formatRelative(f.first_seen_at)}
                      </td>
                      <td className="py-2.5 px-4 text-xs text-slate-600 dark:text-slate-300 whitespace-nowrap">
                        {status === 'resolved' ? (f.resolved_at ? formatRelative(f.resolved_at) : '—') : formatRelative(f.last_seen_at)}
                        <span className="text-slate-400"> · {f.times_seen} run{f.times_seen === 1 ? '' : 's'}</span>
                      </td>
                      {status !== 'resolved' && (
                        <td className="py-2.5 px-4">
                          <div className="flex items-center justify-end gap-1 flex-wrap">
                            {busy ? (
                              <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
                            ) : f.is_muted ? (
                              <ActionBtn title="Put this finding back on the list and alert on it again" onClick={() => unmuteMutation.mutate(f.id)}>
                                <Undo2 className="w-3 h-3" /> Unmute
                              </ActionBtn>
                            ) : (
                              <>
                                <ActionBtn
                                  title="Re-run only this finding's module now; it resolves automatically if the problem is gone"
                                  onClick={() => verifyMutation.mutate(f.id)}
                                  tone="border-brand-200 dark:border-brand-800 text-brand-700 dark:text-brand-300 hover:bg-brand-50 dark:hover:bg-brand-950/40"
                                >
                                  <RotateCcw className="w-3 h-3" /> Verify fix
                                </ActionBtn>
                                <ActionBtn title="Seen it, working on it: keep tracking, stop alerting" onClick={() => muteMutation.mutate({ id: f.id, kind: 'acknowledged' })}>
                                  <Check className="w-3 h-3" /> Ack
                                </ActionBtn>
                                <ActionBtn title="Hide for 30 days, then it comes back if still present" onClick={() => muteMutation.mutate({ id: f.id, kind: 'snoozed', days: 30 })}>
                                  <Clock className="w-3 h-3" /> Snooze
                                </ActionBtn>
                                <ActionBtn title="Known and accepted; hide for good (clears if it resolves and returns)" onClick={() => muteMutation.mutate({ id: f.id, kind: 'accepted' })}>
                                  <ShieldCheck className="w-3 h-3" /> Accept
                                </ActionBtn>
                              </>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default FindingsTable
