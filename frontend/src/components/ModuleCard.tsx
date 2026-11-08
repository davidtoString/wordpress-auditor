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
  search_console: {
    what: "What Google itself reports for this site: whether the homepage, contact page and top-traffic pages are indexed (URL inspection), which canonical Google chose, robots/noindex as Google sees them, sitemap status and errors, and search clicks for the last 28 days against the 28 before. Needs a service account in Settings with access to the property.",
    howToFix: 'A key page that is not indexed is first checked for noindex/robots, then requested via URL inspection in Search Console. A clicks drop of 35%+ with no seasonal reason usually means a ranking drop, a deindexed page or a tracking/redirect change made around the same time; compare with the "Changed" section of the brief.',
  },
  unlighthouse: {
    what: 'Runs Google Lighthouse against each scanned page. The module score is the site-wide average of the Performance category only; accessibility, best practices and SEO are shown alongside but do not count toward it.',
    howToFix: 'Start with the slowest pages in the list below; each one links to its own Lighthouse report with the individual audits and fix guidance.',
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
    what: 'On-page SEO signals per scanned page: title tag, meta description, Open Graph tags, canonical URL, robots meta, and heading structure. Plus site-wide content checks across every scanned page: duplicate page content, thin content, conflicting canonical signals (HTML tag vs HTTP Link header), heading-level skips, slow HTML responses, and noindex/canonicalized heads-ups.',
    howToFix: 'Most findings here are fixed directly in the WordPress editor or your SEO plugin — title/description length, missing H1s, or a noindex tag left on accidentally. Each site-wide content finding below carries its own explanation and fix guidance.',
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
    what: 'Checks that a real, correctly-built contact form exists on the homepage and the Contact page — without ever submitting a test message itself.',
    howToFix: 'A missing form means adding one with your form builder (Elementor, Contact Form 7, WPForms, etc.) to that page. An incomplete form (missing an email field, message field, or submit button) usually means a plugin update broke the form markup — check it by hand.',
  },
  availability: {
    what: 'Is the site up and reachable: DNS resolution, homepage response and latency, TLS certificate validity and expiry, and the domain\'s email authentication records (SPF, DMARC, DKIM) that decide whether contact-form notifications reach the inbox.',
    howToFix: 'A certificate close to expiry is renewed at the host or CDN. Missing SPF/DMARC is fixed in the domain\'s DNS; most form plugins that send through Gmail, Microsoft 365, SendGrid or Postmark document the exact records to add.',
  },
  visual: {
    what: 'Compares each page\'s full-page screenshot with the previous run and has a vision model review the homepage, the contact page and any page that changed noticeably, looking for broken layout, missing images, placeholder or error text, unstyled content or a modal covering the page.',
    howToFix: 'Open the flagged section image ("see section") and the desktop or mobile screenshot, then compare with the live site. Empty sections and cards without text usually mean a widget, shortcode or dynamic content source stopped working after an update.',
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
  const hasScore = typeof result.score === 'number' && Number.isFinite(result.score)
  const score = hasScore ? Math.max(0, Math.min(100, Math.round(result.score as number))) : 0

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

        {/* Visual check: per-page screenshot diff + vision verdict */}
        {modKey === 'visual' && result.details && typeof result.details === 'object' && Array.isArray((result.details as any).pages) && (() => {
          const pages: any[] = [...(result.details as any).pages]
          pages.sort((a, b) => Number(!!b.verdict?.broken) - Number(!!a.verdict?.broken) || (b.diff_ratio ?? -1) - (a.diff_ratio ?? -1))
          return (
            <div className="space-y-2 bg-slate-50 dark:bg-slate-900/60 p-3 rounded-lg border border-slate-200/70 dark:border-slate-800">
              <span className="font-semibold text-slate-800 dark:text-slate-200 block text-xs">
                Pages ({pages.length}); sorted broken first, then most changed
              </span>
              <div className="max-h-72 overflow-y-auto space-y-1.5">
                {pages.map((p, idx) => (
                  <div key={idx} className="flex items-start gap-2.5 text-[11px] bg-white dark:bg-slate-800/80 px-2.5 py-2 rounded border border-slate-200/50 dark:border-slate-700/50">
                    {p.screenshot_url ? (
                      <a href={p.screenshot_url} target="_blank" rel="noopener noreferrer" className="shrink-0" title="Open desktop full-page screenshot">
                        <img src={p.screenshot_url} alt="" className="w-10 h-16 object-cover object-top rounded border border-slate-200 dark:border-slate-700" loading="lazy" />
                      </a>
                    ) : (
                      <div className="w-10 h-16 rounded bg-slate-100 dark:bg-slate-700 shrink-0" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-slate-700 dark:text-slate-300 truncate">{p.path}</span>
                        <span className="shrink-0 flex items-center gap-1.5">
                          {p.verdict?.broken ? (
                            <span className="px-1.5 py-0.5 rounded bg-rose-100 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300 font-semibold">looks broken</span>
                          ) : p.verdict ? (
                            <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300 font-semibold">reviewed ok</span>
                          ) : null}
                          {typeof p.diff_ratio === 'number' ? (
                            <span className={cn('font-mono', p.changed ? 'text-amber-600 dark:text-amber-400 font-semibold' : 'text-slate-500')}>
                              {Math.round(p.diff_ratio * 100)}% changed
                            </span>
                          ) : (
                            <span className="text-slate-400">no baseline</span>
                          )}
                        </span>
                      </div>
                      {p.verdict?.summary && (
                        <p className="text-slate-600 dark:text-slate-300 leading-snug mt-0.5">{p.verdict.summary}</p>
                      )}
                      {Array.isArray(p.verdict?.issues) && p.verdict.issues.length > 0 && (
                        <ul className="mt-0.5 list-disc list-inside text-rose-700 dark:text-rose-300">
                          {p.verdict.issues.slice(0, 4).map((i: any, k: number) => (
                            <li key={k}>
                              {i.viewport ? <span className="uppercase text-[10px] font-semibold mr-1">{i.viewport}</span> : null}
                              {i.description}{i.location ? ` (${i.location})` : ''}
                              {i.tile_url ? (
                                <>
                                  {' '}
                                  <a href={i.tile_url} target="_blank" rel="noopener noreferrer" className="underline text-rose-600 dark:text-rose-300">
                                    see section
                                  </a>
                                </>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      )}
                      {(p.mobile_url || p.verdict?.sections_reviewed) && (
                        <div className="mt-0.5 text-[10px] text-slate-400 flex gap-2">
                          {p.mobile_url ? <a href={p.mobile_url} target="_blank" rel="noopener noreferrer" className="underline">mobile screenshot</a> : null}
                          {p.verdict?.sections_reviewed ? <span>{p.verdict.sections_reviewed} sections reviewed</span> : null}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )
        })()}

        {/* Search Console: totals, inspections, sitemaps */}
        {modKey === 'search_console' && result.details && typeof result.details === 'object' && (result.details as any).connected && (() => {
          const d: any = result.details
          const t = d.totals || {}
          const pv = d.prev_totals || {}
          const ins: any[] = Object.values(d.inspections || {})
          const isIdx = (i: any) => i.verdict === 'PASS' || (i.coverage_state && /indexed/i.test(i.coverage_state) && !/not indexed/i.test(i.coverage_state))
          const delta = d.clicks_delta_pct
          return (
            <div className="space-y-3 bg-slate-50 dark:bg-slate-900/60 p-3 rounded-lg border border-slate-200/70 dark:border-slate-800 text-xs">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-slate-600 dark:text-slate-300">
                <span className="font-mono text-[11px] text-slate-500">{d.property}</span>
                <span><strong className="text-slate-800 dark:text-slate-100">{t.clicks ?? '—'}</strong> clicks
                  {delta !== null && delta !== undefined && <span className={cn('ml-1 font-semibold', delta < -20 ? 'text-rose-600' : delta > 10 ? 'text-emerald-600' : 'text-slate-500')}>({delta > 0 ? '+' : ''}{delta}%)</span>}
                  <span className="text-slate-400"> vs {pv.clicks ?? '—'}</span></span>
                <span><strong className="text-slate-800 dark:text-slate-100">{t.impressions ?? '—'}</strong> impressions</span>
                <span>CTR {t.ctr ?? '—'}%</span>
                <span>avg. position {t.position ?? '—'}</span>
                <span className="text-slate-400">({d.window?.start} → {d.window?.end})</span>
              </div>
              {ins.length > 0 && (
                <div>
                  <span className="font-semibold text-slate-800 dark:text-slate-200 block mb-1">Index status of key pages</span>
                  <div className="space-y-1">
                    {ins.map((i: any, k: number) => (
                      <div key={k} className="flex flex-wrap items-center gap-x-2 bg-white dark:bg-slate-800/80 px-2.5 py-1.5 rounded border border-slate-200/50 dark:border-slate-700/50">
                        {i.error ? (
                          <span className="text-slate-400">inspection failed</span>
                        ) : (
                          <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-bold uppercase', isIdx(i) ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300' : 'bg-rose-100 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300')}>
                            {isIdx(i) ? 'indexed' : 'not indexed'}
                          </span>
                        )}
                        <a href={i.url} target="_blank" rel="noopener noreferrer" className="font-mono text-slate-700 dark:text-slate-200 hover:underline truncate max-w-[320px]">{(() => { try { return new URL(i.url).pathname } catch { return i.url } })()}</a>
                        {i.coverage_state && <span className="text-slate-500">{i.coverage_state}</span>}
                        {i.robots_state === 'DISALLOWED' && <span className="text-rose-600 font-semibold">blocked by robots.txt</span>}
                        {i.google_canonical && i.user_canonical && i.google_canonical.replace(/\/$/, '') !== i.user_canonical.replace(/\/$/, '') && (
                          <span className="text-amber-600" title={`Google: ${i.google_canonical}`}>canonical differs</span>
                        )}
                        {i.last_crawl && <span className="text-slate-400">crawled {String(i.last_crawl).slice(0, 10)}</span>}
                        {i.link && <a href={i.link} target="_blank" rel="noopener noreferrer" className="text-brand-600 hover:underline">open in GSC</a>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {Array.isArray(d.sitemaps) && (
                <div>
                  <span className="font-semibold text-slate-800 dark:text-slate-200 block mb-1">Sitemaps in Search Console ({d.sitemaps.length})</span>
                  {d.sitemaps.length === 0 ? <span className="text-slate-500">None submitted.</span> : (
                    <div className="space-y-0.5">
                      {d.sitemaps.map((sm: any, k: number) => (
                        <div key={k} className="flex flex-wrap gap-x-2 text-slate-600 dark:text-slate-300">
                          <span className="font-mono truncate max-w-[320px]">{sm.path}</span>
                          <span className={sm.errors ? 'text-rose-600 font-semibold' : 'text-slate-400'}>{sm.errors} errors</span>
                          <span className="text-slate-400">{sm.warnings} warnings</span>
                          {sm.contents?.map((c: any, j: number) => <span key={j} className="text-slate-400">{c.type}: {c.indexed}/{c.submitted} indexed</span>)}
                          {sm.last_downloaded && <span className="text-slate-400">read {String(sm.last_downloaded).slice(0, 10)}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {Array.isArray(d.top_queries) && d.top_queries.length > 0 && (
                <div>
                  <span className="font-semibold text-slate-800 dark:text-slate-200 block mb-1">Top queries</span>
                  <div className="flex flex-wrap gap-1.5">
                    {d.top_queries.map((q: any, k: number) => (
                      <span key={k} className="px-2 py-0.5 rounded bg-white dark:bg-slate-800/80 border border-slate-200/50 dark:border-slate-700/50 text-slate-700 dark:text-slate-200">
                        {q.query} <span className="text-slate-400">{q.clicks} · #{q.position}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })()}

        {/* WordPress: theme, administrators, Site Health */}
        {modKey === 'wp_health' && result.details && typeof result.details === 'object' && ((result.details as any).active_theme || (result.details as any).admin_users || (result.details as any).site_health) && (() => {
          const d: any = result.details
          const sh: Record<string, any> = d.site_health || {}
          const shEntries = Object.entries(sh)
          return (
            <div className="space-y-2 bg-slate-50 dark:bg-slate-900/60 p-3 rounded-lg border border-slate-200/70 dark:border-slate-800 text-xs">
              {d.active_theme && (
                <div className="text-slate-700 dark:text-slate-300">
                  <span className="font-semibold text-slate-800 dark:text-slate-200">Theme:</span> {d.active_theme.name}
                  {d.active_theme.version && <span className="font-mono text-slate-500"> v{d.active_theme.version}</span>}
                  {d.active_theme.parent && <span className="text-slate-500"> (child of {d.active_theme.parent})</span>}
                  {Array.isArray(d.vulnerable_themes) && d.vulnerable_themes.length > 0 && <span className="ml-2 text-rose-600 font-semibold">known vulnerability</span>}
                  {Array.isArray(d.outdated_themes) && d.outdated_themes.length > 0 && <span className="ml-2 text-amber-600">update to {d.outdated_themes[0].latest}</span>}
                </div>
              )}
              {Array.isArray(d.admin_users) && (
                <div className="text-slate-700 dark:text-slate-300">
                  <span className="font-semibold text-slate-800 dark:text-slate-200">Administrators ({d.admin_users.length}):</span>{' '}
                  {d.admin_users.map((a: any, k: number) => (
                    <span key={k} className="inline-block mr-2 font-mono" title={a.registered ? `registered ${a.registered}` : ''}>{a.username}</span>
                  ))}
                </div>
              )}
              {shEntries.length > 0 && (
                <div>
                  <span className="font-semibold text-slate-800 dark:text-slate-200 block mb-1">Site Health</span>
                  <div className="flex flex-wrap gap-1.5">
                    {shEntries.map(([test, v]: [string, any]) => (
                      <span
                        key={test}
                        title={v.description || v.error || ''}
                        className={cn('px-2 py-0.5 rounded border text-[11px]',
                          v.status === 'good' ? 'bg-emerald-50 border-emerald-200 text-emerald-700 dark:bg-emerald-950/40 dark:border-emerald-900 dark:text-emerald-300'
                          : v.status === 'critical' ? 'bg-rose-50 border-rose-200 text-rose-700 dark:bg-rose-950/40 dark:border-rose-900 dark:text-rose-300'
                          : v.status === 'recommended' ? 'bg-amber-50 border-amber-200 text-amber-700 dark:bg-amber-950/40 dark:border-amber-900 dark:text-amber-300'
                          : 'bg-slate-100 border-slate-200 text-slate-500 dark:bg-slate-800 dark:border-slate-700')}
                      >
                        {v.label || test}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })()}

        {/* WordPress: vulnerable and outdated plugins get their own block */}
        {result.details && typeof result.details === 'object' && (Array.isArray((result.details as any).vulnerable_plugins) || Array.isArray((result.details as any).outdated_plugins)) && (((result.details as any).vulnerable_plugins?.length || 0) + ((result.details as any).outdated_plugins?.length || 0) > 0) && (() => {
          const vul: any[] = (result.details as any).vulnerable_plugins || []
          const out: any[] = (result.details as any).outdated_plugins || []
          return (
            <div className="space-y-2 bg-slate-50 dark:bg-slate-900/60 p-3 rounded-lg border border-slate-200/70 dark:border-slate-800">
              {vul.length > 0 && (
                <div>
                  <span className="font-semibold text-rose-700 dark:text-rose-300 block text-xs mb-1">
                    Plugins with known vulnerabilities ({vul.length})
                  </span>
                  <div className="space-y-1">
                    {vul.map((p, idx) => (
                      <div key={idx} className="text-[11px] bg-white dark:bg-slate-800/80 px-2.5 py-1.5 rounded border border-rose-200/60 dark:border-rose-900/50">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-slate-800 dark:text-slate-100 truncate">{p.name} <span className="font-mono text-slate-500">v{p.version}</span></span>
                          <span className={cn('px-1.5 py-0.5 rounded text-[10px] font-medium', p.status === 'active' ? 'bg-rose-100 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400')}>{p.status}</span>
                        </div>
                        <ul className="mt-0.5 space-y-0.5">
                          {(p.vulnerabilities || []).slice(0, 3).map((v: any, k: number) => (
                            <li key={k} className="text-slate-600 dark:text-slate-300 truncate">
                              {v.link ? <a href={v.link} target="_blank" rel="noopener noreferrer" className="hover:underline text-brand-700 dark:text-brand-300">{v.name}</a> : v.name}
                              {v.cve ? <span className="text-slate-400"> · {v.cve}</span> : null}
                              {v.fixed_in ? <span className="text-emerald-700 dark:text-emerald-400"> · fixed in {v.fixed_in}</span> : v.unfixed ? <span className="text-rose-600"> · no fix published</span> : null}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {out.length > 0 && (
                <div>
                  <span className="font-semibold text-slate-800 dark:text-slate-200 block text-xs mb-1">
                    Updates available ({out.length})
                  </span>
                  <div className="max-h-40 overflow-y-auto space-y-1">
                    {out.map((p, idx) => (
                      <div key={idx} className="flex items-center justify-between gap-2 text-[11px] bg-white dark:bg-slate-800/80 px-2.5 py-1 rounded border border-slate-200/50 dark:border-slate-700/50">
                        <span className="text-slate-700 dark:text-slate-300 truncate">{p.name}{p.status !== 'active' ? <span className="text-slate-400"> (inactive)</span> : null}</span>
                        <span className="font-mono text-slate-500 shrink-0">{p.installed} → <span className="text-emerald-700 dark:text-emerald-400">{p.latest}</span></span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })()}

        {/* Unlighthouse custom multi-page view if available */}
        {result.details && typeof result.details === 'object' && (result.details as any).site_averages && (() => {
          const d = result.details as any
          const avg = d.site_averages
          const routes: any[] = Array.isArray(d.routes) ? [...d.routes] : []
          // Slowest pages first: that is what a performance audit needs to act on.
          routes.sort((a, b) => (a.performance ?? 0) - (b.performance ?? 0))
          const perfColor = (v: number) =>
            v >= 90 ? 'text-emerald-600 dark:text-emerald-400' : v >= 50 ? 'text-amber-600 dark:text-amber-400' : 'text-rose-600 dark:text-rose-400'
          const composite = typeof d.lighthouse_composite === 'number' ? d.lighthouse_composite : avg.overall
          return (
            <div className="space-y-3 bg-slate-50 dark:bg-slate-900/60 p-3 rounded-lg border border-slate-200/70 dark:border-slate-800">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-semibold text-slate-800 dark:text-slate-200 block text-xs">
                  Site-wide Lighthouse results ({d.total_routes_scanned || 0} pages audited)
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <div className="bg-white dark:bg-slate-800 p-2 rounded border-2 border-brand-500/70 text-center">
                  <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">Performance</span>
                  <span className={cn('text-sm font-bold', perfColor(avg.performance || 0))}>{avg.performance || 0}</span>
                  <span className="text-[9px] text-slate-500 dark:text-slate-400 block">= module score</span>
                </div>
                <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center">
                  <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">Accessibility</span>
                  <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{avg.accessibility || 0}</span>
                </div>
                <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center">
                  <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">Best Practices</span>
                  <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{avg.best_practices || 0}</span>
                </div>
                <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-200/60 dark:border-slate-700/60 text-center">
                  <span className="text-[10px] uppercase text-slate-500 dark:text-slate-400 block font-medium">SEO</span>
                  <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{avg.seo || 0}</span>
                </div>
              </div>
              <p className="text-[10px] text-slate-500 dark:text-slate-400">
                Scores are site-wide averages of each page's Lighthouse category score (0-100). The module score is the
                Performance average only. Four-category composite for reference: {composite}.
              </p>

              {/* Routes List, slowest first, each linking to its own Lighthouse report */}
              {routes.length > 0 && (
                <div className="mt-2">
                  <span className="text-[11px] font-medium text-slate-600 dark:text-slate-400 block mb-1">
                    Pages by Performance (slowest first):
                  </span>
                  <div className="max-h-48 overflow-y-auto space-y-1">
                    {routes.map((r, idx) => (
                      <div key={idx} className="flex items-center justify-between gap-2 text-[11px] bg-white dark:bg-slate-800/80 px-2.5 py-1.5 rounded border border-slate-200/50 dark:border-slate-700/50">
                        {r.report_url ? (
                          <a
                            href={r.report_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            title="Open this page's Lighthouse report"
                            className="font-mono text-brand-700 dark:text-brand-300 hover:underline truncate"
                          >
                            {r.path}
                          </a>
                        ) : (
                          <span className="font-mono text-slate-700 dark:text-slate-300 truncate">{r.path}</span>
                        )}
                        <div className="flex items-center gap-3 shrink-0">
                          <span className={cn('font-bold', perfColor(r.performance ?? 0))}>Perf {r.performance}</span>
                          <span className="text-slate-500 text-[10px]">A11y {r.accessibility} · BP {r.best_practices} · SEO {r.seo}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {d.report_url && (
                <a
                  href={d.report_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-brand-600 hover:bg-brand-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors mt-2"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  Homepage Lighthouse report
                </a>
              )}
            </div>
          )
        })()}

        {/* Site-wide content checks (seo module, ported from OpenSEO's audit engine): one
            block per issue type with severity, explanation, the affected URLs and fix guidance. */}
        {result.details &&
          typeof result.details === 'object' &&
          Array.isArray((result.details as any).site_wide?.issues) &&
          (result.details as any).site_wide.issues.length > 0 && (
            <div className="space-y-2 bg-slate-50 dark:bg-slate-900/60 p-3 rounded-lg border border-slate-200/70 dark:border-slate-800">
              <span className="font-semibold text-slate-800 dark:text-slate-200 block text-xs">
                Site-Wide Content Checks ({(result.details as any).site_wide.pages_analyzed} pages analyzed):
              </span>
              <div className="space-y-1.5">
                {((result.details as any).site_wide.issues as any[]).map((issue, idx) => {
                  const sev: string = issue.severity
                  const sevClass =
                    sev === 'critical'
                      ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                      : sev === 'warning'
                        ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
                        : 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
                  return (
                    <details
                      key={idx}
                      className="group bg-white dark:bg-slate-800/80 rounded border border-slate-200/50 dark:border-slate-700/50"
                    >
                      <summary className="cursor-pointer list-none flex items-center justify-between gap-2 px-2.5 py-1.5 text-[11px]">
                        <span className="flex items-center gap-2 min-w-0">
                          <span className={`shrink-0 px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wide ${sevClass}`}>
                            {sev}
                          </span>
                          <span className="font-semibold text-slate-800 dark:text-slate-200 truncate">{issue.title}</span>
                        </span>
                        <span className="shrink-0 text-slate-500 dark:text-slate-400">
                          {issue.count} {issue.type === 'duplicate-content' ? (issue.count === 1 ? 'group' : 'groups') : issue.count === 1 ? 'page' : 'pages'}
                        </span>
                      </summary>
                      <div className="px-2.5 pb-2 space-y-1.5 text-[11px] border-t border-slate-100 dark:border-slate-700/60 pt-1.5">
                        <p className="text-slate-600 dark:text-slate-300 leading-snug">{issue.explanation}</p>
                        <p className="text-slate-700 dark:text-slate-200 leading-snug">
                          <span className="font-semibold">How to fix:</span> {issue.how_to_fix}
                        </p>
                        <div className="max-h-32 overflow-y-auto space-y-0.5">
                          {(issue.pages as any[]).map((pg, pidx) => (
                            <div key={pidx} className="font-mono text-[10px] text-slate-600 dark:text-slate-400 truncate">
                              {Array.isArray(pg.urls)
                                ? pg.urls.join('  =  ')
                                : [
                                    pg.url,
                                    typeof pg.word_count === 'number' ? `(${pg.word_count} words)` : null,
                                    typeof pg.response_time_ms === 'number' ? `(${pg.response_time_ms} ms)` : null,
                                    pg.canonical_url ? `→ ${pg.canonical_url}` : null,
                                    pg.html_canonical && pg.header_canonical ? `html: ${pg.html_canonical} | header: ${pg.header_canonical}` : null,
                                  ]
                                    .filter(Boolean)
                                    .join(' ')}
                            </div>
                          ))}
                        </div>
                      </div>
                    </details>
                  )
                })}
              </div>
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

        {/* WordPress plugin inventory (wp_health) — its own section so the plugin list doesn't
            get lost inside the generic details dump, same treatment as the Unlighthouse/
            Advertools bespoke summaries below. */}
        {result.details &&
          typeof result.details === 'object' &&
          Array.isArray((result.details as any).installed_plugins) &&
          (result.details as any).installed_plugins.length > 0 && (
            <div className="space-y-2 bg-slate-50 dark:bg-slate-900/60 p-3 rounded-lg border border-slate-200/70 dark:border-slate-800">
              <span className="font-semibold text-slate-800 dark:text-slate-200 block text-xs">
                Installed Plugins ({(result.details as any).installed_plugins.length}
                {typeof (result.details as any).active_plugins_count === 'number'
                  ? `, ${(result.details as any).active_plugins_count} active`
                  : ''}
                ):
              </span>

              {(result.details as any).too_many_active_plugins && (
                <div className="flex items-start gap-1.5 text-[11px] text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded px-2.5 py-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>
                    {(result.details as any).too_many_active_plugins} active plugins is on the
                    high side — each one adds load time, attack surface, and
                    update/compatibility risk.
                  </span>
                </div>
              )}

              {(result.details as any).plugin_count_source === 'inferred_from_assets' && (
                <p className="text-[10px] text-slate-500 dark:text-slate-400 italic">
                  Inferred from front-end asset URLs — no WP Application Password is configured
                  for this site, so inactive plugins and any plugin with no front-end assets
                  won't appear here; treat this as a lower bound.
                </p>
              )}

              <div className="max-h-56 overflow-y-auto space-y-1">
                {((result.details as any).installed_plugins as any[]).map((p, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between gap-2 text-[11px] bg-white dark:bg-slate-800/80 px-2.5 py-1.5 rounded border border-slate-200/50 dark:border-slate-700/50"
                  >
                    <span className="text-slate-700 dark:text-slate-300 truncate">{p.name}</span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {p.version && (
                        <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 text-[10px] font-mono">
                          v{p.version}
                        </span>
                      )}
                      <span
                        className={cn(
                          'px-1.5 py-0.5 rounded text-[10px] font-medium capitalize',
                          p.status === 'active'
                            ? 'bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400'
                            : 'bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400'
                        )}
                      >
                        {p.status}
                      </span>
                    </div>
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
                  value={(() => {
                    const details = result.details as Record<string, unknown>
                    const exclude = new Set<string>()
                    if (Array.isArray(details.pages) && (details.pages as any[]).length > 1) {
                      exclude.add('pages')
                    }
                    if (details.site_wide && typeof details.site_wide === 'object') {
                      exclude.add('site_wide')
                    }
                    if (Array.isArray(details.installed_plugins) && (details.installed_plugins as any[]).length > 0) {
                      exclude.add('installed_plugins')
                      exclude.add('plugin_count_source')
                      exclude.add('authenticated_plugins_count')
                      exclude.add('active_plugins_count')
                      exclude.add('inferred_active_plugin_count')
                      exclude.add('too_many_active_plugins')
                    }
                    return exclude.size > 0
                      ? Object.fromEntries(Object.entries(details).filter(([k]) => !exclude.has(k)))
                      : result.details
                  })()}
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
                className={cn('transition-all duration-700 stroke-current', hasScore ? scoreToColor(score) : 'text-slate-300 dark:text-slate-600')}
                strokeWidth="4"
                strokeDasharray={circumference}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                fill="transparent"
              />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className={cn('text-xs font-bold font-mono', hasScore ? scoreToColor(score) : 'text-slate-400')}>
                {hasScore ? score : 'n/a'}
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
