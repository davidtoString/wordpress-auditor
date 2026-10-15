import React from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Globe,
  CheckCircle,
  Clock,
  Award,
  Plus,
  Play,
  AlertTriangle,
  ExternalLink,
  Loader2,
  RefreshCw,
  TrendingUp,
} from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { sites as sitesApi, audits as auditsApi, settings as settingsApi } from '../lib/api'
import { useAuth } from '../lib/auth'
import ScoreBadge from '../components/ScoreBadge'
import AuditRunsTable from '../components/AuditRunsTable'
import { formatRelative, getAppDateString, parseDateSafe, scoreToColor } from '../lib/utils'
import toast from 'react-hot-toast'

export const DashboardPage: React.FC = () => {
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()

  // Fetch Sites
  const {
    data: siteList = [],
    isLoading: sitesLoading,
    refetch: refetchSites,
  } = useQuery({
    queryKey: ['sites'],
    queryFn: () => sitesApi.list(),
  })

  // Fetch Recent Audits
  const {
    data: auditsData,
    isLoading: auditsLoading,
    refetch: refetchAudits,
  } = useQuery({
    queryKey: ['audits', 'recent'],
    queryFn: () => auditsApi.list(1, 10),
  })

  // Mutation for Triggering Single Audit
  const triggerAuditMutation = useMutation({
    mutationFn: (siteId: string) => sitesApi.triggerAudit(siteId),
    onSuccess: () => {
      toast.success('Audit successfully triggered!')
      queryClient.invalidateQueries({ queryKey: ['sites'] })
      queryClient.invalidateQueries({ queryKey: ['audits'] })
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to trigger audit')
    },
  })

  // Mutation for Run All Audits
  const runAllMutation = useMutation({
    mutationFn: () => settingsApi.runAll(),
    onSuccess: (data) => {
      toast.success(data.message || 'Audits triggered for all sites')
      queryClient.invalidateQueries({ queryKey: ['sites'] })
      queryClient.invalidateQueries({ queryKey: ['audits'] })
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to trigger batch audit')
    },
  })

  const recentAudits = auditsData?.audits || []

  // Stats calculations
  const totalSites = siteList.length
  const activeSites = siteList.filter((s) => s.is_active !== false).length

  const todayStr = getAppDateString()
  const auditsToday = recentAudits.filter((a) => {
    const started = parseDateSafe(a.started_at)
    return started ? getAppDateString(started) === todayStr : false
  }).length

  const scoredSites = siteList.filter((s) => s.last_score !== null && s.last_score !== undefined)
  const avgScore =
    scoredSites.length > 0
      ? Math.round(
          scoredSites.reduce((acc, curr) => acc + (curr.last_score || 0), 0) / scoredSites.length
        )
      : 0

  // Critical sites (score < 50)
  const criticalSites = siteList.filter(
    (s) => s.last_score !== null && s.last_score !== undefined && s.last_score < 50
  )

  // Score distribution data for recharts
  const distributionMap = {
    'Excellent (90-100)': { count: 0, color: '#10b981' },
    'Good (70-89)': { count: 0, color: '#f59e0b' },
    'Needs Work (50-69)': { count: 0, color: '#f97316' },
    'Critical (<50)': { count: 0, color: '#ef4444' },
    'Not Audited': { count: 0, color: '#94a3b8' },
  }

  siteList.forEach((s) => {
    if (s.last_score === null || s.last_score === undefined) {
      distributionMap['Not Audited'].count += 1
    } else if (s.last_score >= 90) {
      distributionMap['Excellent (90-100)'].count += 1
    } else if (s.last_score >= 70) {
      distributionMap['Good (70-89)'].count += 1
    } else if (s.last_score >= 50) {
      distributionMap['Needs Work (50-69)'].count += 1
    } else {
      distributionMap['Critical (<50)'].count += 1
    }
  })

  const chartData = Object.entries(distributionMap).map(([range, info]) => ({
    name: range,
    count: info.count,
    color: info.color,
  }))

  const isLoading = sitesLoading || auditsLoading

  return (
    <div className="space-y-8 pb-10">
      {/* Page Header & Quick Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
            System Overview
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
            Real-time health, performance, security, and audit metrics across your portfolio.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => {
              refetchSites()
              refetchAudits()
            }}
            className="p-2 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-850 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400 transition-colors shadow-sm"
            title="Refresh dashboard"
          >
            <RefreshCw className="w-4 h-4" />
          </button>

          {isAdmin && (
            <>
              <button
                type="button"
                onClick={() => runAllMutation.mutate()}
                disabled={runAllMutation.isPending}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-semibold rounded-lg text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/50 shadow-sm transition-all"
              >
                {runAllMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin text-brand-500" />
                ) : (
                  <Play className="w-4 h-4 text-emerald-500" />
                )}
                Run All Audits
              </button>

              <Link
                to="/sites/new"
                className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg text-white bg-brand-600 hover:bg-brand-700 shadow-sm hover:shadow transition-all"
              >
                <Plus className="w-4 h-4" />
                Add Site
              </Link>
            </>
          )}
        </div>
      </div>

      {/* Top 4 Stats Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Sites */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Total Sites
            </span>
            <div className="p-2 rounded-xl bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400">
              <Globe className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold font-mono text-slate-900 dark:text-slate-100">
              {totalSites}
            </span>
            <span className="text-xs text-slate-400">monitored</span>
          </div>
        </div>

        {/* Active Sites */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Active Sites
            </span>
            <div className="p-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400">
              <CheckCircle className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold font-mono text-emerald-600 dark:text-emerald-400">
              {activeSites}
            </span>
            <span className="text-xs text-slate-400">enabled</span>
          </div>
        </div>

        {/* Audits Today */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Audits Today
            </span>
            <div className="p-2 rounded-xl bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400">
              <Clock className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold font-mono text-slate-900 dark:text-slate-100">
              {auditsToday}
            </span>
            <span className="text-xs text-slate-400">executions</span>
          </div>
        </div>

        {/* Average Score */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Avg Portfolio Score
            </span>
            <div className="p-2 rounded-xl bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400">
              <Award className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span
              className={`text-3xl font-extrabold font-mono ${scoreToColor(
                scoredSites.length ? avgScore : null
              )}`}
            >
              {scoredSites.length ? avgScore : '—'}
            </span>
            <span className="text-xs text-slate-400">/ 100</span>
          </div>
        </div>
      </div>

      {/* Critical Issues Section (if any sites < 50) */}
      {criticalSites.length > 0 && (
        <div className="bg-rose-50/70 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/60 rounded-2xl p-5 shadow-sm">
          <div className="flex items-center gap-2 mb-3 text-rose-800 dark:text-rose-300 font-bold text-sm">
            <AlertTriangle className="w-5 h-5 text-rose-600 dark:text-rose-400" />
            <span>Critical Issues Attention Needed ({criticalSites.length} Sites With Score &lt; 50)</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {criticalSites.map((site) => (
              <div
                key={site.id}
                className="bg-white dark:bg-slate-900 p-3.5 rounded-xl border border-rose-200/80 dark:border-rose-900/60 flex items-center justify-between shadow-sm"
              >
                <div className="min-w-0 pr-3">
                  <Link
                    to={`/sites/${site.id}`}
                    className="font-semibold text-sm text-slate-900 dark:text-slate-100 hover:text-brand-600 truncate block"
                  >
                    {site.name}
                  </Link>
                  <span className="text-xs text-slate-400 truncate block">{site.url}</span>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <ScoreBadge score={site.last_score} size="sm" />
                  <Link
                    to={`/sites/${site.id}`}
                    className="p-1 text-slate-400 hover:text-brand-600 transition-colors"
                  >
                    <ExternalLink className="w-4 h-4" />
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Middle Grid: Score Distribution Chart + Sites Health Overview */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Score Distribution Chart */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-5 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-brand-500" />
                Score Distribution
              </h3>
              <span className="text-xs text-slate-400">{siteList.length} total sites</span>
            </div>
            <div className="h-56 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 25 }}>
                  <XAxis
                    dataKey="name"
                    tick={{ fontSize: 10 }}
                    interval={0}
                    angle={-25}
                    textAnchor="end"
                  />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1e293b',
                      borderRadius: '8px',
                      color: '#f8fafc',
                      fontSize: '12px',
                    }}
                  />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {chartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="pt-3 border-t border-slate-100 dark:border-slate-700/60 flex flex-wrap justify-center gap-3 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" /> 90-100
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-500" /> 70-89
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-orange-500" /> 50-69
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-500" /> &lt;50
            </span>
          </div>
        </div>

        {/* Sites Health Overview (Grid cards) */}
        <div className="lg:col-span-2 bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-5 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                  Sites Health Quick Glance
                </h3>
                <p className="text-xs text-slate-400">Current score and schedule status</p>
              </div>
              <Link
                to="/sites"
                className="text-xs font-semibold text-brand-600 dark:text-brand-400 hover:underline"
              >
                View All Sites &rarr;
              </Link>
            </div>

            {siteList.length === 0 ? (
              <div className="py-12 text-center text-slate-400 text-xs">
                No sites configured yet.{' '}
                {isAdmin && (
                  <Link to="/sites/new" className="text-brand-600 underline">
                    Add your first WordPress site
                  </Link>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-[300px] overflow-y-auto pr-1">
                {siteList.slice(0, 6).map((site) => (
                  <div
                    key={site.id}
                    className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-700/80 bg-slate-50/60 dark:bg-slate-900/40 hover:bg-white dark:hover:bg-slate-850 transition-all flex flex-col justify-between"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <Link
                          to={`/sites/${site.id}`}
                          className="font-semibold text-sm text-slate-900 dark:text-slate-100 hover:text-brand-600 truncate block"
                        >
                          {site.name}
                        </Link>
                        <span className="text-[11px] text-slate-400 truncate block">
                          {site.url}
                        </span>
                      </div>
                      <ScoreBadge score={site.last_score} size="sm" />
                    </div>

                    <div className="mt-3 pt-2 border-t border-slate-200/60 dark:border-slate-800 flex items-center justify-between text-[11px] text-slate-500">
                      <span>Last: {formatRelative(site.last_audit_at)}</span>
                      <button
                        type="button"
                        onClick={() => triggerAuditMutation.mutate(site.id)}
                        disabled={triggerAuditMutation.isPending}
                        className="text-brand-600 dark:text-brand-400 hover:underline font-medium inline-flex items-center gap-1"
                      >
                        <Play className="w-3 h-3 fill-current" />
                        Audit
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Recent Audit Runs Table */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">
              Recent Audit Executions
            </h3>
            <p className="text-xs text-slate-500">Last 10 completed or in-progress audit runs</p>
          </div>
          <Link
            to="/audits"
            className="text-xs font-semibold text-brand-600 dark:text-brand-400 hover:underline"
          >
            Full Audit Logs &rarr;
          </Link>
        </div>

        <AuditRunsTable audits={recentAudits} isLoading={isLoading} />
      </div>
    </div>
  )
}

export default DashboardPage
