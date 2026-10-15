import React, { useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ExternalLink,
  Play,
  Pencil,
  Loader2,
  Calendar,
  Sparkles,
  History,
  LayoutGrid,
  ChevronLeft,
  ChevronRight,
  TrendingUp,
  PauseCircle,
  PlayCircle,
  Trash2,
  AlertCircle,
} from 'lucide-react'
import Modal from '../components/ui/Modal'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { sites as sitesApi, audits as auditsApi } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { ModuleResult, AuditScope } from '../lib/types'
import ScoreBadge from '../components/ScoreBadge'
import ModuleCard from '../components/ModuleCard'
import AuditRunsTable from '../components/AuditRunsTable'
import { formatDate, formatRelative } from '../lib/utils'
import toast from 'react-hot-toast'

export const SiteDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [historyPage, setHistoryPage] = useState(1)
  const [auditScope, setAuditScope] = useState<AuditScope>('quick')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  // 1. Fetch Site Info
  const {
    data: site,
    isLoading: siteLoading,
    isError: siteError,
  } = useQuery({
    queryKey: ['site', id],
    queryFn: () => sitesApi.get(id!),
    enabled: !!id,
  })

  // 2. Fetch Audit History
  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['site-history', id, historyPage],
    queryFn: () => sitesApi.getHistory(id!, historyPage),
    enabled: !!id,
  })

  // 3. Fetch Latest Audit Run
  const { data: latestAudit } = useQuery({
    queryKey: ['site-latest-audit', id],
    queryFn: () => auditsApi.getLatest(id!),
    enabled: !!id,
  })

  // 4. Trigger Audit Mutation
  const triggerMutation = useMutation({
    mutationFn: (scope: AuditScope) => sitesApi.triggerAudit(id!, scope),
    onSuccess: (_data, scope) => {
      toast.success(
        scope === 'full'
          ? 'Full site audit started — this can take a while, feel free to check back later.'
          : 'Audit execution initiated!'
      )
      queryClient.invalidateQueries({ queryKey: ['site', id] })
      queryClient.invalidateQueries({ queryKey: ['site-history', id] })
      queryClient.invalidateQueries({ queryKey: ['site-latest-audit', id] })
      queryClient.invalidateQueries({ queryKey: ['audits'] })
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to trigger audit')
    },
  })

  // 5. Toggle automated scheduled audits on/off
  const toggleActiveMutation = useMutation({
    mutationFn: (nextActive: boolean) => sitesApi.update(id!, { is_active: nextActive }),
    onSuccess: (updatedSite) => {
      toast.success(
        updatedSite.is_active
          ? 'Automated audits resumed for this site.'
          : 'Automated audits paused — no scheduled audits will run until re-enabled.'
      )
      queryClient.invalidateQueries({ queryKey: ['site', id] })
      queryClient.invalidateQueries({ queryKey: ['sites'] })
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to update site')
    },
  })

  // 6. Delete site
  const deleteMutation = useMutation({
    mutationFn: () => sitesApi.delete(id!),
    onSuccess: () => {
      toast.success('Site deleted.')
      queryClient.invalidateQueries({ queryKey: ['sites'] })
      navigate('/sites')
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to delete site')
      setShowDeleteConfirm(false)
    },
  })

  const scopeOptions: { value: AuditScope; label: string }[] = [
    { value: 'quick', label: 'Quick (Pages)' },
    { value: 'with_posts', label: '+ Blog Posts' },
    { value: 'full', label: 'Full Site (slow)' },
  ]

  if (siteLoading) {
    return (
      <div className="py-24 flex flex-col items-center justify-center">
        <Loader2 className="w-8 h-8 text-brand-600 animate-spin mb-3" />
        <p className="text-sm text-slate-500">Loading site details & history...</p>
      </div>
    )
  }

  if (siteError || !site) {
    return (
      <div className="max-w-md mx-auto text-center py-20">
        <h3 className="text-lg font-bold text-slate-800 dark:text-slate-200">Site Not Found</h3>
        <p className="text-xs text-slate-500 mt-1 mb-4">
          The requested site could not be retrieved.
        </p>
        <Link
          to="/sites"
          className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-semibold"
        >
          Back to Sites
        </Link>
      </div>
    )
  }

  const audits = historyData?.audits || []
  const totalAudits = historyData?.total || audits.length

  // Build Chronological chart data (last 30 runs, chronological order)
  const chartRuns = [...audits]
    .slice(0, 30)
    .reverse()
    .map((run, idx) => ({
      index: idx + 1,
      date: run.started_at ? formatDate(run.started_at).slice(0, 12) : `Run ${idx + 1}`,
      score: run.score !== null && run.score !== undefined ? run.score : 0,
      status: run.status,
    }))

  // Extract module results safely
  let moduleResultsList: ModuleResult[] = []
  if (latestAudit?.results) {
    if (Array.isArray(latestAudit.results)) {
      moduleResultsList = latestAudit.results
    } else {
      moduleResultsList = Object.entries(latestAudit.results).map(([key, val]) => ({
        ...(val as ModuleResult),
        module: (val as ModuleResult).module || key,
      }))
    }
  }

  return (
    <div className="space-y-8 pb-12">
      {/* Site Header Card */}
      <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
              {site.name}
            </h2>
            <ScoreBadge score={site.last_score} size="lg" showLabel />
            {site.is_active === false && (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-600">
                <PauseCircle className="w-3.5 h-3.5" />
                Automated audits paused
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
            <a
              href={site.url}
              target="_blank"
              rel="noreferrer"
              className="hover:text-brand-600 inline-flex items-center gap-1 font-mono text-slate-600 dark:text-slate-300"
            >
              {site.url}
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
            <span>&bull;</span>
            <span className="flex items-center gap-1">
              <Calendar className="w-3.5 h-3.5 text-slate-400" />
              Cron: <code className="font-mono">{site.cron_schedule}</code>
            </span>
            <span>&bull;</span>
            <span>Last Audit: {formatRelative(site.last_audit_at)}</span>
          </div>
        </div>

        <div className="flex flex-col items-end gap-2 shrink-0">
          <div className="flex items-center gap-3">
            {isAdmin && (
              <button
                type="button"
                onClick={() => toggleActiveMutation.mutate(site.is_active === false)}
                disabled={toggleActiveMutation.isPending}
                title={
                  site.is_active === false
                    ? 'Resume automated scheduled audits'
                    : 'Pause automated scheduled audits (manual audits still work)'
                }
                className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-semibold rounded-xl text-slate-700 dark:text-slate-200 bg-slate-100 dark:bg-slate-700/70 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors disabled:opacity-60"
              >
                {toggleActiveMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : site.is_active === false ? (
                  <PlayCircle className="w-4 h-4" />
                ) : (
                  <PauseCircle className="w-4 h-4" />
                )}
                {site.is_active === false ? 'Resume Audits' : 'Pause Audits'}
              </button>
            )}

            {isAdmin && (
              <button
                type="button"
                onClick={() => setShowDeleteConfirm(true)}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-semibold rounded-xl text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 transition-colors"
              >
                <Trash2 className="w-4 h-4" />
                Delete Site
              </button>
            )}

            {isAdmin && (
              <Link
                to={`/sites/${id}/edit`}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-semibold rounded-xl text-slate-700 dark:text-slate-200 bg-slate-100 dark:bg-slate-700/70 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
              >
                <Pencil className="w-4 h-4" />
                Edit Site
              </Link>
            )}

            <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-900/60">
              {scopeOptions.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setAuditScope(opt.value)}
                  className={`px-2.5 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                    auditScope === opt.value
                      ? 'bg-white dark:bg-slate-700 text-brand-600 dark:text-brand-400 shadow-sm'
                      : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={() => triggerMutation.mutate(auditScope)}
              disabled={triggerMutation.isPending}
              className="inline-flex items-center gap-2 px-5 py-2 text-sm font-semibold rounded-xl text-white bg-brand-600 hover:bg-brand-700 shadow-md shadow-brand-500/20 disabled:opacity-60 transition-all"
            >
              {triggerMutation.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Auditing...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-current" />
                  Audit Now
                </>
              )}
            </button>
          </div>
          {auditScope === 'full' && (
            <p className="text-xs text-amber-600 dark:text-amber-400 max-w-xs text-right">
              Scans every page and can take a long time — check back later.
            </p>
          )}
        </div>
      </div>

      {/* Score History Chart (Last 30 runs) */}
      <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-brand-500" />
              Audit Score Trajectory
            </h3>
            <p className="text-xs text-slate-400">
              Historical score trend across up to the last 30 executions
            </p>
          </div>
          {chartRuns.length > 0 && (
            <span className="text-xs font-mono text-slate-500">
              {chartRuns.length} recorded points
            </span>
          )}
        </div>

        {chartRuns.length === 0 ? (
          <div className="h-44 flex flex-col items-center justify-center text-slate-400 text-xs border border-dashed border-slate-200 dark:border-slate-800 rounded-xl">
            No audit runs completed yet. Click &ldquo;Audit Now&rdquo; above to run the initial assessment.
          </div>
        ) : (
          <div className="h-60 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartRuns} margin={{ top: 10, right: 20, left: -20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1e293b',
                    borderRadius: '8px',
                    color: '#f8fafc',
                    fontSize: '12px',
                  }}
                  formatter={(value: any) => [`${value} / 100`, 'Health Score']}
                />
                <Line
                  type="monotone"
                  dataKey="score"
                  stroke="#3b82f6"
                  strokeWidth={3}
                  dot={{ r: 4, fill: '#3b82f6', strokeWidth: 2, stroke: '#fff' }}
                  activeDot={{ r: 6 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* AI Recommendations Section */}
      {latestAudit?.ai_recommendations && (
        <div className="bg-gradient-to-br from-purple-500/10 via-brand-500/5 to-transparent rounded-2xl border border-purple-200 dark:border-purple-900/60 p-6 shadow-sm">
          <div className="flex items-center gap-2 text-purple-900 dark:text-purple-300 font-bold text-base mb-3">
            <div className="p-1.5 rounded-lg bg-purple-600 text-white">
              <Sparkles className="w-4 h-4" />
            </div>
            <span>AI Automated Action Plan & Recommendations</span>
          </div>

          <div className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed whitespace-pre-line bg-white/70 dark:bg-slate-900/70 backdrop-blur p-5 rounded-xl border border-purple-100 dark:border-purple-900/40 font-mono text-xs max-h-96 overflow-y-auto">
            {latestAudit.ai_recommendations}
          </div>
        </div>
      )}

      {/* 12 Audit Modules Grid */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <LayoutGrid className="w-5 h-5 text-brand-500" />
              Audit Modules Breakdown
            </h3>
            <p className="text-xs text-slate-500">
              Detailed metrics across Core Web Vitals, SEO, Security, Links, and Compliance
            </p>
          </div>

          {latestAudit && (
            <Link
              to={`/audits/${latestAudit.id}`}
              className="text-xs font-semibold text-brand-600 dark:text-brand-400 hover:underline"
            >
              View Full Run Report &rarr;
            </Link>
          )}
        </div>

        {moduleResultsList.length === 0 ? (
          <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-12 text-center">
            <LayoutGrid className="w-8 h-8 text-slate-400 mx-auto mb-2" />
            <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              No audit module results yet
            </h4>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1 mb-4">
              Trigger a manual audit or wait for the cron schedule to execute to inspect the 12 audit modules.
            </p>
            <button
              onClick={() => triggerMutation.mutate(auditScope)}
              disabled={triggerMutation.isPending}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-lg text-white bg-brand-600 hover:bg-brand-700"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              Trigger First Audit
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {moduleResultsList.map((mod, idx) => (
              <ModuleCard key={idx} moduleKey={mod.module} result={mod} />
            ))}
          </div>
        )}
      </div>

      {/* Audit History Table (Paginated) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <History className="w-5 h-5 text-slate-500" />
              Historical Audit Log
            </h3>
            <p className="text-xs text-slate-500">
              Audit executions and test runs logged for this site
            </p>
          </div>
        </div>

        <AuditRunsTable
          audits={audits}
          isLoading={historyLoading}
          showSiteName={false}
          emptyMessage="No audit logs for this site yet."
        />

        {/* Pagination controls */}
        {totalAudits > 10 && (
          <div className="flex items-center justify-between pt-2">
            <span className="text-xs text-slate-500">
              Showing page {historyPage} (total records: {totalAudits})
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setHistoryPage((p) => Math.max(1, p - 1))}
                disabled={historyPage === 1}
                className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={() => setHistoryPage((p) => p + 1)}
                disabled={audits.length < 10}
                className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      <Modal
        isOpen={showDeleteConfirm}
        onClose={() => setShowDeleteConfirm(false)}
        title="Confirm Delete Site"
        description="This action cannot be undone. All audit histories for this site will be permanently removed."
      >
        <div className="space-y-4">
          <div className="p-3.5 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs text-rose-800 dark:text-rose-300 flex items-start gap-2.5">
            <AlertCircle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
            <div>
              Are you sure you want to delete{' '}
              <strong className="font-semibold text-rose-900 dark:text-rose-200">{site.name}</strong>{' '}
              ({site.url})?
            </div>
          </div>

          <div className="flex justify-end gap-2.5 pt-2">
            <button
              type="button"
              onClick={() => setShowDeleteConfirm(false)}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => deleteMutation.mutate()}
              disabled={deleteMutation.isPending}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 shadow-sm transition-colors flex items-center gap-1.5 disabled:opacity-60"
            >
              {deleteMutation.isPending ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Trash2 className="w-3.5 h-3.5" />
              )}
              Confirm Delete
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default SiteDetailPage
