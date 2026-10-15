import React, { useState } from 'react'
import {
  ChevronDown,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  ExternalLink,
  Search,
} from 'lucide-react'
import type { ModuleResult } from '../lib/types'
import {
  cn,
  moduleDisplayName,
  moduleIcon,
  scoreToColor,
  scoreToProgressColor,
} from '../lib/utils'
import Modal from './ui/Modal'

interface ModuleCardProps {
  moduleKey?: string
  result: ModuleResult
}

// Short, static "what this checks / how to act on it" context per module — shown at the top of
// the detail popup. The raw findings below answer "what did it find"; this answers "why does
// that matter and what do I do about it", which the raw data alone doesn't convey.
const MODULE_HELP: Record<string, { what: string; howToFix: string }> = {
  unlighthouse: {
    what: 'Runs Google Lighthouse against each scanned page: performance, accessibility, best practices, and on-page SEO.',
    howToFix: 'Check the per-page scores below for the weakest pages first. The full interactive Lighthouse report (link below, if available) lists every individual audit with specific fix guidance.',
  },
  advertools: {
    what: 'Technical SEO fundamentals: robots.txt rules, XML sitemap health, and homepage title/meta description length for search snippets.',
    howToFix: 'A missing or misconfigured sitemap/robots.txt should be fixed in your SEO plugin (Yoast, RankMath, or WP core). Title/description length issues are edited directly on the page.',
  },
  pagespeed: {
    what: 'Real-world page load timing (falls back to a basic HTTP timing measurement if no Google PageSpeed API key is configured in Settings).',
    howToFix: 'Slow scores usually trace back to unoptimized images, too many plugins, or no caching/CDN. Add a Google PageSpeed API key in Settings for full Core Web Vitals data instead of the basic timing fallback.',
  },
  seo: {
    what: 'On-page SEO signals per scanned page: title tag, meta description, Open Graph tags, canonical URL, robots meta, and heading structure.',
    howToFix: 'Most findings here are fixed directly in the WordPress editor or your SEO plugin — title/description length, missing H1s, or a noindex tag left on accidentally.',
  },
  security: {
    what: 'HTTPS enforcement, standard security response headers, mixed content, XML-RPC exposure, and WordPress version disclosure.',
    howToFix: 'Missing security headers are usually added via a security plugin (Wordfence, Sucuri) or server/CDN config (e.g. Cloudflare Transform Rules). Mixed content means some assets are still loaded over http:// and need updating to https://.',
  },
  links: {
    what: 'Crawls internal and external links for broken (4xx/5xx) responses and long redirect chains, plus (on quick/with_posts/full scope) interlinking structure across every scanned page: orphan pages with no internal links pointing to them, and pages that barely link out to anything else. Links blocked by a WAF/rate-limiter during the scan are reported separately as "inconclusive", not broken.',
    howToFix: 'Fix or remove genuinely broken links. For long redirect chains, update the link to point directly at the final destination. For orphan pages, add internal links to them from relevant content/nav; for weakly-linked pages, add a few contextual links out to other relevant pages on the site.',
  },
  schema: {
    what: 'Structured data (JSON-LD) coverage across scanned pages — LocalBusiness, Organization, Article, etc. — and whether it validates.',
    howToFix: 'Add missing schema via your SEO plugin\'s schema settings, or a dedicated schema plugin. Validation errors (missing required fields) should be fixed in whatever generated that JSON-LD block.',
  },
  cookies: {
    what: 'Whether a cookie consent banner is present and functioning, and which cookies are set before consent is given.',
    howToFix: 'If tracking cookies are set before consent, configure your consent plugin (CookieYes, Complianz, etc.) to block them until the visitor accepts.',
  },
  images: {
    what: 'Image optimization across scanned pages: missing alt text, legacy formats (JPG/PNG vs WebP/AVIF), oversized files, and missing lazy-loading.',
    howToFix: 'Add alt text for accessibility/SEO. Use an image optimization plugin (ShortPixel, Imagify, EWWW) to convert to modern formats and compress oversized files.',
  },
  nap: {
    what: 'Name/Address/Phone consistency — compares the business info configured for this site against what\'s actually published on the page, important for local SEO.',
    howToFix: 'Update either the site\'s NAP configuration (in the Edit Site form) or the actual page content so they match exactly, including formatting.',
  },
  wp_health: {
    what: 'Core WordPress hardening: version disclosure, user enumeration, debug/error output exposed publicly, wp-login.php protection, and installed plugins — with a full plugin list and a flag when the site is running an unusually large number of active plugins.',
    howToFix: 'Hide version info and block user enumeration via a security plugin. PHP debug output appearing publicly means WP_DEBUG_DISPLAY is on in production — turn it off in wp-config.php. For a high plugin count, audit the list below and remove or consolidate ones that aren\'t earning their keep — each one adds load time, attack surface, and update/compatibility risk.',
  },
  redirects: {
    what: 'HTTP-to-HTTPS redirect behavior and response headers on key URLs.',
    howToFix: 'Ensure your host or a redirect plugin forces HTTPS site-wide with a single 301 redirect, not a chain of multiple hops.',
  },
  contact_forms: {
    what: 'Checks that a real, correctly-built contact form exists on the homepage and the Contact page, and (if a Postmark server token is configured) whether the site has sent any transactional email recently — without ever submitting a test message itself.',
    howToFix: 'A missing form means adding one with your form builder (Elementor, Contact Form 7, WPForms, etc.) to that page. No recent Postmark activity is inconclusive on its own — configure a Postmark server token in Edit Site to get a real signal, and verify a real submission arrives in your inbox at least once.',
  },
  tracking_scripts: {
    what: 'Inventories every analytics, advertising pixel, call-tracking, heatmap, and chat-widget script loaded on the site — Google Analytics/Tag Manager, Meta Pixel, Google Ads, CallRail, Hotjar, etc. — and flags missing tracking, deprecated Universal Analytics, likely duplicate installs, and tracking present on some scanned pages but not others.',
    howToFix: 'Add or fix tracking via whichever plugin manages it (Site Kit, GTM4WP, MonsterInsights, etc. — see "Likely Source" below) or the theme/Elementor custom-code area it was hardcoded into. Remove duplicate or legacy (Universal Analytics) installs rather than leaving them running alongside the replacement.',
  },
}

const prettifyKey = (key: string) =>
  key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

/**
 * Generic, readable fallback for any module's `details` payload that doesn't have a bespoke
 * view below (links, security, cookies, images, nap, wp_health, seo, pagespeed, redirects,
 * schema). Replaces a raw `JSON.stringify` dump with labeled key/value rendering, a compact
 * row layout for arrays of per-item findings (anything with a `url` key — broken/blocked
 * links, flagged images, redirect chains, etc.), and bullet lists for plain arrays.
 */
const DataView: React.FC<{ value: unknown; depth?: number }> = ({ value, depth = 0 }) => {
  if (value === null || value === undefined || value === '') {
    return <span className="text-slate-400 dark:text-slate-500 italic">—</span>
  }

  if (typeof value === 'boolean') {
    return (
      <span className={value ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-500 dark:text-slate-400'}>
        {value ? 'Yes' : 'No'}
      </span>
    )
  }

  if (typeof value !== 'object') {
    return <span className="break-words">{String(value)}</span>
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-slate-400 dark:text-slate-500 italic">None</span>
    }

    // Array of simple values -> bullet list
    if (!value.some(isPlainObject)) {
      return (
        <ul className="space-y-0.5 list-disc list-inside">
          {value.map((item, idx) => (
            <li key={idx} className="break-words">{String(item)}</li>
          ))}
        </ul>
      )
    }

    // Array of per-item findings sharing a "url" key (links, images, redirects, ...) ->
    // compact single-line rows instead of a full key/value dump per item
    if (value.every((item) => isPlainObject(item) && 'url' in item)) {
      return (
        <div className="space-y-1 max-h-56 overflow-y-auto pr-1">
          {value.map((item, idx) => {
            const obj = item as Record<string, unknown>
            const { url, ...rest } = obj
            const badgeEntries = Object.entries(rest).filter(
              ([, v]) => v !== null && v !== undefined && v !== '' && v !== false && typeof v !== 'object'
            )
            return (
              <div
                key={idx}
                className="flex items-center justify-between gap-2 text-[11px] bg-white dark:bg-slate-800/80 px-2.5 py-1.5 rounded border border-slate-200/50 dark:border-slate-700/50"
              >
                <span className="font-mono text-slate-700 dark:text-slate-300 truncate">{String(url)}</span>
                <div className="flex items-center gap-1.5 shrink-0">
                  {badgeEntries.map(([k, v]) => (
                    <span
                      key={k}
                      className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 text-[10px] font-medium whitespace-nowrap"
                      title={prettifyKey(k)}
                    >
                      {String(v)}
                    </span>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )
    }

    // Array of other objects -> stacked mini cards, each rendering recursively
    return (
      <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
        {value.map((item, idx) => (
          <div
            key={idx}
            className="bg-white dark:bg-slate-800/80 px-2.5 py-1.5 rounded border border-slate-200/50 dark:border-slate-700/50"
          >
            <DataView value={item} depth={depth + 1} />
          </div>
        ))}
      </div>
    )
  }

  // Plain object -> labeled key/value grid, recursing into nested values
  const entries = Object.entries(value as Record<string, unknown>)
  if (entries.length === 0) {
    return <span className="text-slate-400 dark:text-slate-500 italic">None</span>
  }

  return (
    <div className={cn('grid gap-2', depth === 0 ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1')}>
      {entries.map(([key, val]) => (
        <div key={key} className="min-w-0">
          <span className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400 block font-medium">
            {prettifyKey(key)}
          </span>
          <div className="text-slate-800 dark:text-slate-200 text-xs leading-relaxed">
            <DataView value={val} depth={depth + 1} />
          </div>
        </div>
      ))}
    </div>
  )
}

export const ModuleCard: React.FC<ModuleCardProps> = ({ moduleKey, result }) => {
  const [isModalOpen, setIsModalOpen] = useState(false)

  const modKey = moduleKey || result.module || 'unknown'
  const displayName = moduleDisplayName(modKey)
  const Icon = moduleIcon(modKey)
  const help = MODULE_HELP[modKey.toLowerCase()]
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

        {/* Generic per-page breakdown for any module that scanned more than one page (seo,
            security, schema, images, wp_health). Unlighthouse has its own richer block above
            (with Lighthouse category sub-scores), so this is skipped when site_averages already
            rendered one to avoid showing the same page list twice. */}
        {result.details &&
          typeof result.details === 'object' &&
          !(result.details as any).site_averages &&
          Array.isArray((result.details as any).pages) &&
          (result.details as any).pages.length > 1 && (
            <div className="space-y-2 bg-slate-50 dark:bg-slate-900/60 p-3 rounded-lg border border-slate-200/70 dark:border-slate-800">
              <span className="font-semibold text-slate-800 dark:text-slate-200 block text-xs">
                Pages Scanned ({(result.details as any).pages.length}):
              </span>
              <div className="max-h-40 overflow-y-auto space-y-1">
                {((result.details as any).pages as any[]).map((p, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between gap-2 text-[11px] bg-white dark:bg-slate-800/80 px-2.5 py-1.5 rounded border border-slate-200/50 dark:border-slate-700/50"
                  >
                    <span className="font-mono text-slate-700 dark:text-slate-300 truncate">{p.url}</span>
                    {typeof p.score === 'number' && (
                      <span className="font-bold text-slate-900 dark:text-slate-100 shrink-0">{p.score}%</span>
                    )}
                  </div>
                ))}
              </div>
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
              <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center">
                <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">Sub-Sitemaps</span>
                <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{((result.details as any).sitemap?.sub_sitemaps?.length || 0)}</span>
              </div>
              <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center col-span-2 sm:col-span-1">
                <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">Title/Meta Checked</span>
                <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{((result.details as any).serp?.total_pages_checked || 1)} pages</span>
              </div>
            </div>

            {/* Duplicate titles/descriptions across pages */}
            {(Object.keys((result.details as any).serp?.duplicate_titles || {}).length > 0 ||
              Object.keys((result.details as any).serp?.duplicate_descriptions || {}).length > 0) && (
              <div className="space-y-2">
                <span className="text-[11px] font-medium text-amber-600 dark:text-amber-400 block">
                  Duplicate Titles / Meta Descriptions Across Pages:
                </span>
                <div className="space-y-1.5 max-h-40 overflow-y-auto">
                  {Object.entries((result.details as any).serp?.duplicate_titles || {}).map(([text, urls], idx) => (
                    <div key={`t-${idx}`} className="text-[10px] bg-white dark:bg-slate-800/80 p-2 rounded border border-slate-200/50 dark:border-slate-700/50">
                      <span className="font-semibold text-slate-700 dark:text-slate-300">Title:</span>{' '}
                      <span className="font-mono text-slate-600 dark:text-slate-400">"{text}"</span>
                      <div className="text-slate-500 dark:text-slate-500 mt-0.5">{(urls as string[]).join(', ')}</div>
                    </div>
                  ))}
                  {Object.entries((result.details as any).serp?.duplicate_descriptions || {}).map(([text, urls], idx) => (
                    <div key={`d-${idx}`} className="text-[10px] bg-white dark:bg-slate-800/80 p-2 rounded border border-slate-200/50 dark:border-slate-700/50">
                      <span className="font-semibold text-slate-700 dark:text-slate-300">Meta Description:</span>{' '}
                      <span className="font-mono text-slate-600 dark:text-slate-400">"{(text as string).slice(0, 80)}..."</span>
                      <div className="text-slate-500 dark:text-slate-500 mt-0.5">{(urls as string[]).join(', ')}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

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
            <span className="font-semibold text-slate-700 dark:text-slate-300 block mb-1.5">
              Audit Data & Diagnostics:
            </span>
            {typeof result.details === 'string' ? (
              <p className="text-slate-600 dark:text-slate-300 leading-relaxed bg-slate-50 dark:bg-slate-900/60 p-2.5 rounded border border-slate-200/60 dark:border-slate-800">
                {result.details}
              </p>
            ) : (
              <div className="bg-slate-50 dark:bg-slate-900/60 p-2.5 rounded-lg border border-slate-200/60 dark:border-slate-800">
                <DataView
                  value={
                    Array.isArray((result.details as any)?.pages) && (result.details as any).pages.length > 1
                      ? Object.fromEntries(Object.entries(result.details as any).filter(([k]) => k !== 'pages'))
                      : result.details
                  }
                />
              </div>
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
        <button
          type="button"
          onClick={() => setIsModalOpen(true)}
          className="w-full flex items-center justify-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 transition-colors py-1.5 rounded hover:bg-slate-50 dark:hover:bg-slate-700/40"
        >
          View Full Report <ChevronDown className="w-3.5 h-3.5 -rotate-90" />
        </button>
      </div>

      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title={displayName}
        description={result.summary || 'Audit completed without summary remarks.'}
        maxWidth="2xl"
      >
        <div className="space-y-4">
          {/* Score + status header */}
          <div className="flex items-center gap-4 pb-4 border-b border-slate-100 dark:border-slate-700/60">
            <div className="relative flex items-center justify-center shrink-0">
              <svg className="w-16 h-16 -rotate-90" viewBox="0 0 52 52">
                <circle cx="26" cy="26" r={radius} className="text-slate-100 dark:text-slate-700 stroke-current" strokeWidth="4" fill="transparent" />
                <circle
                  cx="26" cy="26" r={radius}
                  className={cn('transition-all duration-700 stroke-current', scoreToColor(score))}
                  strokeWidth="4" strokeDasharray={circumference} strokeDashoffset={strokeDashoffset}
                  strokeLinecap="round" fill="transparent"
                />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className={cn('text-sm font-bold font-mono', scoreToColor(score))}>{score}</span>
              </div>
            </div>
            <div className="min-w-0">
              {getStatusBadge()}
              <div className="w-full bg-slate-100 dark:bg-slate-700/60 h-1.5 rounded-full overflow-hidden mt-2 max-w-xs">
                <div className={cn('h-full transition-all duration-500', scoreToProgressColor(score))} style={{ width: `${score}%` }} />
              </div>
            </div>
          </div>

          {/* What this checks / how to act on it */}
          {help && (
            <div className="bg-brand-50/60 dark:bg-brand-950/30 border border-brand-200/70 dark:border-brand-900/50 rounded-xl p-4 space-y-2">
              <div className="flex items-start gap-2">
                <Search className="w-4 h-4 text-brand-600 dark:text-brand-400 shrink-0 mt-0.5" />
                <div>
                  <span className="text-xs font-semibold text-brand-900 dark:text-brand-300 block">What this checks</span>
                  <p className="text-xs text-slate-700 dark:text-slate-300 mt-0.5 leading-relaxed">{help.what}</p>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <HelpCircle className="w-4 h-4 text-brand-600 dark:text-brand-400 shrink-0 mt-0.5" />
                <div>
                  <span className="text-xs font-semibold text-brand-900 dark:text-brand-300 block">How to act on it</span>
                  <p className="text-xs text-slate-700 dark:text-slate-300 mt-0.5 leading-relaxed">{help.howToFix}</p>
                </div>
              </div>
            </div>
          )}

          {renderDetails()}
        </div>
      </Modal>
    </div>
  )
}

export default ModuleCard
