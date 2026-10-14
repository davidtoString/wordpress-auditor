import React, { useState } from 'react'
import {
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  ExternalLink,
} from 'lucide-react'
import type { ModuleResult } from '../lib/types'
import {
  cn,
  moduleDisplayName,
  moduleIcon,
  scoreToColor,
  scoreToProgressColor,
} from '../lib/utils'

interface ModuleCardProps {
  moduleKey?: string
  result: ModuleResult
}

export const ModuleCard: React.FC<ModuleCardProps> = ({ moduleKey, result }) => {
  const [isExpanded, setIsExpanded] = useState(false)

  const modKey = moduleKey || result.module || 'unknown'
  const displayName = moduleDisplayName(modKey)
  const Icon = moduleIcon(modKey)
  const score = Math.max(0, Math.min(100, Math.round(result.score || 0)))

  // SVG Circular progress params
  const radius = 22
  const circumference = 2 * Math.PI * radius
  const strokeDashoffset = circumference - (score / 100) * circumference

  const getStatusBadge = () => {
    const s = (result.status || 'unknown').toLowerCase()
    if (s === 'pass' || s === 'ok' || s === 'healthy') {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
          Pass
        </span>
      )
    }
    if (s === 'warn' || s === 'warning') {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
          Warning
        </span>
      )
    }
    if (s === 'fail' || s === 'failed' || s === 'critical' || s === 'error') {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-100 dark:bg-rose-950/60 text-rose-800 dark:text-rose-300 border border-rose-200 dark:border-rose-800">
          <XCircle className="w-3.5 h-3.5 text-rose-600 dark:text-rose-400" />
          Fail
        </span>
      )
    }
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
        <HelpCircle className="w-3.5 h-3.5 text-slate-500" />
        Info
      </span>
    )
  }

  // Helper to render details safely
  const renderDetails = () => {
    if (!result.details && !result.issues && !result.metrics) {
      return (
        <p className="text-xs text-slate-500 dark:text-slate-400 italic">
          No additional granular logs recorded for this module run.
        </p>
      )
    }

    return (
      <div className="space-y-3 pt-3 border-t border-slate-200/80 dark:border-slate-700/80 text-xs">
        {/* Issues list if available */}
        {result.issues && result.issues.length > 0 && (
          <div>
            <span className="font-semibold text-rose-600 dark:text-rose-400 block mb-1">
              Detected Issues ({result.issues.length}):
            </span>
            <ul className="space-y-1 list-disc list-inside text-slate-700 dark:text-slate-300">
              {result.issues.map((issue, idx) => (
                <li key={idx} className="leading-relaxed">
                  {issue}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Metrics key-values */}
        {result.metrics && Object.keys(result.metrics).length > 0 && (
          <div>
            <span className="font-semibold text-slate-700 dark:text-slate-300 block mb-1.5">
              Key Metrics:
            </span>
            <div className="grid grid-cols-2 gap-2 bg-slate-50 dark:bg-slate-900/60 p-2.5 rounded-md border border-slate-200/60 dark:border-slate-800">
              {Object.entries(result.metrics).map(([key, val]) => (
                <div key={key} className="truncate">
                  <span className="text-slate-500 dark:text-slate-400 uppercase tracking-wider text-[10px] block">
                    {key.replace(/_/g, ' ')}
                  </span>
                  <span className="font-mono text-slate-800 dark:text-slate-200 font-medium">
                    {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Unlighthouse custom multi-page view if available */}
        {result.details && typeof result.details === 'object' && (result.details as any).site_averages && (
          <div className="space-y-3 bg-slate-50 dark:bg-slate-900/60 p-3 rounded-lg border border-slate-200/70 dark:border-slate-800">
            <span className="font-semibold text-slate-800 dark:text-slate-200 block text-xs">
              Site-Wide Multi-Page Breakdown ({((result.details as any).total_routes_scanned || 0)} pages audited):
            </span>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center">
                <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">Performance</span>
                <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{((result.details as any).site_averages.performance || 0)}%</span>
              </div>
              <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center">
                <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">Accessibility</span>
                <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{((result.details as any).site_averages.accessibility || 0)}%</span>
              </div>
              <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center">
                <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">Best Practices</span>
                <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{((result.details as any).site_averages.best_practices || 0)}%</span>
              </div>
              <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center">
                <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">SEO</span>
                <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{((result.details as any).site_averages.seo || 0)}%</span>
              </div>
            </div>

            {/* Routes List */}
            {Array.isArray((result.details as any).routes) && (result.details as any).routes.length > 0 && (
              <div className="mt-2">
                <span className="text-[11px] font-medium text-slate-600 dark:text-slate-400 block mb-1">Crawled Routes:</span>
                <div className="max-h-36 overflow-y-auto space-y-1">
                  {((result.details as any).routes as any[]).map((r, idx) => (
                    <div key={idx} className="flex items-center justify-between text-[11px] bg-white dark:bg-slate-800/80 px-2.5 py-1.5 rounded border border-slate-200/50 dark:border-slate-700/50">
                      <span className="font-mono text-slate-700 dark:text-slate-300 truncate max-w-[200px]">{r.path}</span>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="text-slate-500 text-[10px]">Perf: {r.performance}%</span>
                        <span className="font-bold text-slate-900 dark:text-slate-100">{r.score}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {(result.details as any).report_url && (
              <a
                href={(result.details as any).report_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-brand-600 hover:bg-brand-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors mt-2"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                View Full Interactive Lighthouse Report
              </a>
            )}
          </div>
        )}

        {/* Advertools custom technical SEO view if available */}
        {result.details && typeof result.details === 'object' && (result.details as any).robots_txt && (result.details as any).sitemap && (
          <div className="space-y-3 bg-slate-50 dark:bg-slate-900/60 p-3 rounded-lg border border-slate-200/70 dark:border-slate-800">
            <span className="font-semibold text-slate-800 dark:text-slate-200 block text-xs">
              Advertools Technical Crawl Summary:
            </span>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center">
                <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">Sitemap URLs</span>
                <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{((result.details as any).sitemap?.total_urls || 0)}</span>
              </div>
              <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center">
                <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">Robots.txt</span>
                <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{((result.details as any).robots_txt?.status === 'ok' ? 'Valid' : 'Issues')}</span>
              </div>
              <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center col-span-2 sm:col-span-1">
                <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">Sub-Sitemaps</span>
                <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{((result.details as any).sitemap?.sub_sitemaps?.length || 0)}</span>
              </div>
            </div>

            {/* Findings & Warnings */}
            {Array.isArray((result.details as any).warnings) && (result.details as any).warnings.length > 0 && (
              <div className="space-y-1">
                <span className="text-[11px] font-medium text-amber-600 dark:text-amber-400 block">Technical Warnings:</span>
                <ul className="list-disc list-inside space-y-0.5 text-[11px] text-slate-700 dark:text-slate-300">
                  {((result.details as any).warnings as string[]).map((w, idx) => (
                    <li key={idx}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            {Array.isArray((result.details as any).sitemap?.sample_urls) && (result.details as any).sitemap.sample_urls.length > 0 && (
              <div>
                <span className="text-[11px] font-medium text-slate-600 dark:text-slate-400 block mb-1">Indexed Sitemap Sample:</span>
                <div className="max-h-28 overflow-y-auto space-y-1">
                  {((result.details as any).sitemap.sample_urls as string[]).map((url, idx) => (
                    <div key={idx} className="text-[10px] font-mono bg-white dark:bg-slate-800/80 px-2 py-1 rounded border border-slate-200/50 dark:border-slate-700/50 truncate text-slate-700 dark:text-slate-300">
                      {url}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Generic details object/string (if not custom views) */}
        {result.details && !(result.details as any)?.site_averages && !((result.details as any)?.robots_txt && (result.details as any)?.sitemap) && (
          <div>
            <span className="font-semibold text-slate-700 dark:text-slate-300 block mb-1">
              Audit Data & Diagnostics:
            </span>
            {typeof result.details === 'string' ? (
              <p className="text-slate-600 dark:text-slate-300 leading-relaxed bg-slate-50 dark:bg-slate-900/60 p-2.5 rounded border border-slate-200/60 dark:border-slate-800">
                {result.details}
              </p>
            ) : Array.isArray(result.details) ? (
              <ul className="space-y-1 list-disc list-inside text-slate-600 dark:text-slate-300 bg-slate-50 dark:bg-slate-900/60 p-2.5 rounded border border-slate-200/60 dark:border-slate-800">
                {result.details.map((item, idx) => (
                  <li key={idx}>
                    {typeof item === 'object' ? JSON.stringify(item) : String(item)}
                  </li>
                ))}
              </ul>
            ) : (
              <pre className="text-[11px] font-mono bg-slate-900 text-slate-100 p-2.5 rounded-md overflow-x-auto max-h-48">
                {JSON.stringify(result.details, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-slate-800/90 rounded-xl border border-slate-200 dark:border-slate-700/80 shadow-sm hover:shadow-md transition-shadow p-5 flex flex-col justify-between">
      <div>
        {/* Top Header */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-700/70 text-brand-600 dark:text-brand-400 shrink-0">
              <Icon className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate">
                {displayName}
              </h3>
              <div className="mt-0.5">{getStatusBadge()}</div>
            </div>
          </div>

          {/* Circular Score Gauge */}
          <div className="relative flex items-center justify-center shrink-0">
            <svg className="w-14 h-14 -rotate-90" viewBox="0 0 52 52">
              <circle
                cx="26"
                cy="26"
                r={radius}
                className="text-slate-100 dark:text-slate-700 stroke-current"
                strokeWidth="4"
                fill="transparent"
              />
              <circle
                cx="26"
                cy="26"
                r={radius}
                className={cn('transition-all duration-700 stroke-current', scoreToColor(score))}
                strokeWidth="4"
                strokeDasharray={circumference}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                fill="transparent"
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className={cn('text-xs font-bold font-mono', scoreToColor(score))}>
                {score}
              </span>
            </div>
          </div>
        </div>

        {/* Progress Bar fallback / indicator */}
        <div className="w-full bg-slate-100 dark:bg-slate-700/60 h-1.5 rounded-full overflow-hidden mb-3">
          <div
            className={cn('h-full transition-all duration-500', scoreToProgressColor(score))}
            style={{ width: `${score}%` }}
          />
        </div>

        {/* Summary text */}
        <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed min-h-[36px]">
          {result.summary || 'Audit completed without summary remarks.'}
        </p>
      </div>

      {/* Details Toggle */}
      <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-700/60">
        {isExpanded && renderDetails()}

        <button
          type="button"
          onClick={() => setIsExpanded(!isExpanded)}
          className="mt-2.5 w-full flex items-center justify-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 transition-colors py-1 rounded hover:bg-slate-50 dark:hover:bg-slate-700/40"
        >
          {isExpanded ? (
            <>
              Hide Diagnostics <ChevronUp className="w-3.5 h-3.5" />
            </>
          ) : (
            <>
              View Findings & Details <ChevronDown className="w-3.5 h-3.5" />
            </>
          )}
        </button>
      </div>
    </div>
  )
}

export default ModuleCard
