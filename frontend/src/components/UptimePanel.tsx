import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, Loader2, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { sites as sitesApi } from '../lib/api'
import type { UptimeSummary } from '../lib/types'
import { cn, formatDate, formatRelative } from '../lib/utils'

const fmtDuration = (mins: number) => (mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, '0')}m`)

export const UptimePanel: React.FC<{ siteId: string }> = ({ siteId }) => {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery<UptimeSummary>({
    queryKey: ['site-uptime', siteId],
    queryFn: () => sitesApi.getUptime(siteId, 30),
    refetchInterval: 5 * 60 * 1000,
  })
  const checkNow = useMutation({
    mutationFn: () => sitesApi.checkUptimeNow(siteId),
    onSuccess: (r) => {
      if (r.ok) toast.success(`Up: HTTP ${r.status} in ${r.latency_ms} ms`)
      else toast.error(`Down: ${r.error || 'no response'}`)
      queryClient.invalidateQueries({ queryKey: ['site-uptime', siteId] })
      queryClient.invalidateQueries({ queryKey: ['site', siteId] })
      queryClient.invalidateQueries({ queryKey: ['sites'] })
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Probe failed'),
  })

  const down = data?.down_now
  const pct = data?.uptime_pct
  const recent = [...(data?.recent || [])].reverse()

  return (
    <div
      className={cn(
        'rounded-2xl border p-5 shadow-sm',
        down
          ? 'bg-rose-50 dark:bg-rose-950/30 border-rose-300 dark:border-rose-900'
          : 'bg-white dark:bg-slate-800/90 border-slate-200 dark:border-slate-700/80'
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Activity className={cn('w-4 h-4', down ? 'text-rose-600' : 'text-emerald-500')} />
          <span className={cn('font-bold text-sm', down ? 'text-rose-800 dark:text-rose-200' : 'text-slate-800 dark:text-slate-100')}>
            {down ? `DOWN since ${data?.down_since ? formatDate(data.down_since) : ''}` : 'Uptime (hourly probe)'}
          </span>
        </div>
        <button
          type="button"
          onClick={() => checkNow.mutate()}
          disabled={checkNow.isPending}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/60 disabled:opacity-60"
        >
          {checkNow.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Check now
        </button>
      </div>

      {isLoading ? (
        <div className="mt-3 text-xs text-slate-500 flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
        </div>
      ) : !data || data.checks === 0 ? (
        <p className="mt-2 text-xs text-slate-500">No probes yet. The first hourly check runs a few minutes after the backend starts.</p>
      ) : (
        <>
          <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div>
              <div className="text-slate-500">Last 30 days</div>
              <div className={cn('text-lg font-bold', pct !== null && pct !== undefined && pct < 99.5 ? 'text-amber-600' : 'text-emerald-600')}>
                {pct !== null && pct !== undefined ? `${pct.toFixed(2)}%` : '—'}
              </div>
            </div>
            <div>
              <div className="text-slate-500">Checks</div>
              <div className="text-lg font-bold text-slate-800 dark:text-slate-100">{data.checks}</div>
            </div>
            <div>
              <div className="text-slate-500">Typical response</div>
              <div className="text-lg font-bold text-slate-800 dark:text-slate-100">{data.latency_p50_ms != null ? `${data.latency_p50_ms} ms` : '—'}</div>
            </div>
            <div>
              <div className="text-slate-500">Last check</div>
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-100" title={data.last_check_at ? formatDate(data.last_check_at) : ''}>
                {data.last_check_at ? formatRelative(data.last_check_at) : '—'}
                {data.last_status ? <span className="text-slate-400 font-normal"> · HTTP {data.last_status}</span> : null}
                {data.last_note ? <span className="text-slate-400 font-normal"> · {data.last_note}</span> : null}
              </div>
            </div>
          </div>

          {recent.length > 0 && (
            <div className="mt-3 flex items-end gap-[2px] h-6" title="Last 48 hourly checks, oldest left">
              {recent.map((c, i) => (
                <span
                  key={i}
                  title={`${formatDate(c.at)} · ${c.ok ? `HTTP ${c.status} in ${c.latency_ms} ms` : c.note || 'down'}`}
                  className={cn('flex-1 rounded-sm', c.ok ? (c.note?.startsWith('blip') ? 'bg-amber-400' : 'bg-emerald-400/80') : 'bg-rose-500')}
                  style={{ height: c.ok ? `${Math.max(30, Math.min(100, 100 - (c.latency_ms || 0) / 30))}%` : '100%' }}
                />
              ))}
            </div>
          )}

          {data.incidents.length > 0 && (
            <div className="mt-3 border-t border-slate-200/70 dark:border-slate-700/60 pt-2">
              <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-1">Downtime in the last 30 days</div>
              <ul className="space-y-1 text-xs">
                {data.incidents.slice(0, 8).map((inc) => (
                  <li key={inc.id || inc.started_at} className="flex flex-wrap items-center gap-x-2 text-slate-700 dark:text-slate-300">
                    <span className={cn('font-semibold', inc.ended_at ? 'text-rose-600' : 'text-rose-700 animate-pulse')}>
                      {inc.ended_at ? fmtDuration(inc.duration_minutes) : `ongoing, ${fmtDuration(inc.duration_minutes)}`}
                    </span>
                    <span>from {formatDate(inc.started_at)}</span>
                    {inc.first_error && <span className="text-slate-500 truncate max-w-[360px]">· {inc.first_error}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default UptimePanel
