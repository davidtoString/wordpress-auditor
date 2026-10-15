import React, { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Download,
  Share2,
  Calendar,
  Zap,
  Clock,
  Sparkles,
  ArrowLeft,
  Loader2,
  Check,
  Globe,
  LayoutGrid,
  XCircle,
  FileText,
  FileJson,
  ChevronDown,
} from 'lucide-react'
import { audits as auditsApi } from '../lib/api'
import type { ModuleResult } from '../lib/types'
import ScoreBadge from '../components/ScoreBadge'
import ModuleCard from '../components/ModuleCard'
import { formatDate, formatRelative } from '../lib/utils'
import toast from 'react-hot-toast'

export const AuditDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const [copied, setCopied] = useState(false)
  const [exportMenuOpen, setExportMenuOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const queryClient = useQueryClient()

  const cancelMutation = useMutation({
    mutationFn: () => auditsApi.cancel(id!),
    onSuccess: () => {
      toast.success('Audit cancelled.')
      queryClient.invalidateQueries({ queryKey: ['audit', id] })
      queryClient.invalidateQueries({ queryKey: ['audits'] })
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to cancel audit')
    },
  })

  const {
    data: audit,
    isLoading: auditLoading,
    isError,
  } = useQuery({
    queryKey: ['audit', id],
    queryFn: () => auditsApi.get(id!),
    enabled: !!id,
    // Poll while the audit is still running so the page updates on its own instead of
    // requiring a manual refresh — important now that "full" scope audits can take a while.
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' || status === 'pending' ? 7000 : false
    },
  })

  // Also query results if separate
  const { data: resultsData } = useQuery({
    queryKey: ['audit-results', id],
    queryFn: () => auditsApi.getResults(id!),
    enabled: !!id && !audit?.results,
  })

  const handleShare = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      toast.success('Direct audit report link copied to clipboard!')
      setTimeout(() => setCopied(false), 2500)
    } catch {
      toast.error('Failed to copy link')
    }
  }

  const handleExportReport = async (format: 'markdown' | 'json') => {
    if (!id) return
    setExportMenuOpen(false)
    setExporting(true)
    try {
      const { blob, filename } = await auditsApi.exportReport(id, format)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
      toast.success(
        format === 'markdown'
          ? 'Markdown report downloaded — ready to hand to an AI agent for fixes'
          : 'JSON report downloaded'
      )
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to export report')
    } finally {
      setExporting(false)
    }
  }

  if (auditLoading) {
    return (
      <div className="py-24 flex flex-col items-center justify-center">
        <Loader2 className="w-8 h-8 text-brand-600 animate-spin mb-3" />
        <p className="text-sm text-slate-500">Loading audit execution data...</p>
      </div>
    )
  }

  if (isError || !audit) {
    return (
      <div className="max-w-md mx-auto text-center py-20">
        <h3 className="text-lg font-bold text-slate-800 dark:text-slate-200">Audit Not Found</h3>
        <p className="text-xs text-slate-500 mt-1 mb-4">
          The requested audit record cannot be located.
        </p>
        <Link
          to="/audits"
          className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-semibold"
        >
          Back to Audits List
        </Link>
      </div>
    )
  }

  // Parse modules
  const rawResults = audit.results || resultsData || []
  let moduleList: ModuleResult[] = []
  if (Array.isArray(rawResults)) {
    moduleList = rawResults
  } else if (typeof rawResults === 'object') {
    moduleList = Object.entries(rawResults).map(([key, val]) => ({
      ...(val as ModuleResult),
      module: (val as ModuleResult).module || key,
    }))
  }

  const isInProgress = audit.status === 'running' || audit.status === 'pending'

  const formatDuration = (seconds?: number | null) => {
    if (seconds === null || seconds === undefined) return '—'
    if (seconds < 60) return `${Math.round(seconds)}s`
    const mins = Math.floor(seconds / 60)
    const secs = Math.round(seconds % 60)
    return `${mins}m ${secs}s`
  }

  return (
    <div className="space-y-8 pb-12">
      {/* Back button */}
      <div>
        <Link
          to={audit.site_id ? `/sites/${audit.site_id}` : '/audits'}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          {audit.site_id ? `Back to ${audit.site_name || 'Site'}` : 'Back to Audits'}
        </Link>
      </div>

      {/* Audit Header Banner */}
      <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
              Audit Report: {audit.site_name || `Site #${audit.site_id}`}
            </h2>
            <ScoreBadge score={audit.score} size="xl" showLabel />
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
            {audit.site_url && (
              <a
                href={audit.site_url}
                target="_blank"
                rel="noreferrer"
                className="hover:text-brand-600 inline-flex items-center gap-1 font-mono text-slate-600 dark:text-slate-300"
              >
                <Globe className="w-3.5 h-3.5" />
                {audit.site_url}
              </a>
            )}
            <span>&bull;</span>
            <span className="flex items-center gap-1">
              <Calendar className="w-3.5 h-3.5 text-slate-400" />
              {formatDate(audit.started_at)} ({formatRelative(audit.started_at)})
            </span>
            <span>&bull;</span>
            <span className="flex items-center gap-1">
              <Zap className="w-3.5 h-3.5 text-amber-500" />
              Triggered by: {audit.triggered_by || 'Manual'}
            </span>
            <span>&bull;</span>
            <span className="flex items-center gap-1">
              <Clock className="w-3.5 h-3.5 text-slate-400" />
              Duration: {formatDuration(audit.duration_seconds)}
            </span>
            {audit.scope && (
              <>
                <span>&bull;</span>
                <span className="flex items-center gap-1">
                  <LayoutGrid className="w-3.5 h-3.5 text-slate-400" />
                  Scope: {audit.scope === 'quick' ? 'Quick (Pages)' : audit.scope === 'with_posts' ? '+ Blog Posts' : 'Full Site'}
                </span>
              </>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2.5 shrink-0">
          {isInProgress && (
            <button
              type="button"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs sm:text-sm font-semibold rounded-xl text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 transition-colors shadow-sm disabled:opacity-60"
            >
              {cancelMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <XCircle className="w-4 h-4" />
              )}
              Cancel Audit
            </button>
          )}

          <button
            type="button"
            onClick={handleShare}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs sm:text-sm font-semibold rounded-xl text-slate-700 dark:text-slate-200 bg-slate-100 dark:bg-slate-700/60 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors shadow-sm"
          >
            {copied ? (
              <>
                <Check className="w-4 h-4 text-emerald-500" />
                Copied!
              </>
            ) : (
              <>
                <Share2 className="w-4 h-4" />
                Share Link
              </>
            )}
          </button>

          <div className="relative">
            <button
              type="button"
              onClick={() => setExportMenuOpen((v) => !v)}
              disabled={exporting}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs sm:text-sm font-semibold rounded-xl text-white bg-brand-600 hover:bg-brand-700 shadow-md shadow-brand-500/20 transition-all disabled:opacity-60"
            >
              {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
              Export Report
              <ChevronDown className="w-3.5 h-3.5" />
            </button>

            {exportMenuOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setExportMenuOpen(false)} />
                <div className="absolute right-0 mt-2 w-64 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-lg z-20 overflow-hidden">
                  <button
                    type="button"
                    onClick={() => handleExportReport('markdown')}
                    className="w-full flex items-start gap-2.5 px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-700/60 transition-colors"
                  >
                    <FileText className="w-4 h-4 mt-0.5 text-brand-600 shrink-0" />
                    <span>
                      <span className="block text-sm font-semibold text-slate-800 dark:text-slate-100">Markdown (.md)</span>
                      <span className="block text-xs text-slate-500 dark:text-slate-400">For handing to an AI agent to apply fixes</span>
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleExportReport('json')}
                    className="w-full flex items-start gap-2.5 px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-700/60 transition-colors border-t border-slate-100 dark:border-slate-700"
                  >
                    <FileJson className="w-4 h-4 mt-0.5 text-brand-600 shrink-0" />
                    <span>
                      <span className="block text-sm font-semibold text-slate-800 dark:text-slate-100">JSON (.json)</span>
                      <span className="block text-xs text-slate-500 dark:text-slate-400">Structured data for scripts/integrations</span>
                    </span>
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* AI Recommendations (Full text) */}
      {audit.ai_recommendations ? (
        <div className="bg-gradient-to-br from-purple-500/10 via-brand-500/5 to-transparent rounded-2xl border border-purple-200 dark:border-purple-900/60 p-6 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-purple-900 dark:text-purple-300 font-bold text-base">
              <div className="p-1.5 rounded-lg bg-purple-600 text-white shadow-sm">
                <Sparkles className="w-4 h-4" />
              </div>
              <span>AI Remediation Plan & Intelligent Recommendations</span>
            </div>
          </div>

          <div className="p-5 rounded-xl bg-white/80 dark:bg-slate-900/80 backdrop-blur border border-purple-100 dark:border-purple-900/40 text-xs font-mono leading-relaxed text-slate-800 dark:text-slate-200 whitespace-pre-wrap">
            {audit.ai_recommendations}
          </div>
        </div>
      ) : (
        <div className="p-4 rounded-xl bg-slate-100 dark:bg-slate-800/60 text-xs text-slate-500 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-slate-400" />
          <span>
            AI Recommendations were not generated for this specific run. Configure OpenAI or Gemini keys in Settings to enable automated action plans.
          </span>
        </div>
      )}

      {/* 12 Module Results in Cards */}
      <div className="space-y-4">
        <div>
          <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <LayoutGrid className="w-5 h-5 text-brand-500" />
            Audit Module Findings & Diagnostics
          </h3>
          <p className="text-xs text-slate-500">
            Detailed scores and diagnostic logs recorded across all audit modules during this execution
          </p>
        </div>

        {isInProgress ? (
          <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-12 text-center">
            <Loader2 className="w-8 h-8 text-brand-600 animate-spin mx-auto mb-3" />
            <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              Audit in progress…
            </h4>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1">
              {audit.scope === 'full'
                ? 'Full site audits scan every page and can take a long time. This page will update on its own — feel free to check back later.'
                : 'This page will update automatically once the audit completes.'}
            </p>
            <button
              type="button"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              className="inline-flex items-center gap-1.5 mt-4 px-4 py-2 text-xs font-semibold rounded-lg text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 disabled:opacity-60"
            >
              <XCircle className="w-3.5 h-3.5" />
              Cancel Audit
            </button>
          </div>
        ) : moduleList.length === 0 ? (
          <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-12 text-center">
            <LayoutGrid className="w-8 h-8 text-slate-400 mx-auto mb-2" />
            <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
              {audit.status === 'failed' ? 'Audit failed' : 'No module results recorded'}
            </h4>
            <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1">
              {audit.status === 'failed'
                ? 'This run did not complete successfully — no module data was recorded.'
                : 'This audit run has no module results.'}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {moduleList.map((result, idx) => (
              <ModuleCard key={idx} moduleKey={result.module} result={result} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default AuditDetailPage
