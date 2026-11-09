import type { Audit, AuditScope } from './types'

/** The three kinds of audit a person can run, in the words the UI uses everywhere. */
export type AuditKind = 'quick' | 'full' | 'visual'

export interface AuditKindInfo {
  key: AuditKind
  label: string
  /** One line: what it covers. */
  summary: string
  /** What is checked. */
  checks: string
  /** How long it takes and what it costs. */
  effort: string
  /** When to use it. */
  when: string
  scope: AuditScope
  includeVisual: boolean
}

export const AUDIT_KINDS: AuditKindInfo[] = [
  {
    key: 'quick',
    label: 'Quick audit',
    summary: 'Homepage plus up to 20 pages. No screenshots.',
    checks: 'PageSpeed, Lighthouse, technical SEO, security, WordPress health, links, forms, redirects, schema and tracking on that sample.',
    effort: 'About 5 to 10 minutes. No AI cost.',
    when: 'Spot check after a change, or a first look at a new site.',
    scope: 'quick',
    includeVisual: false,
  },
  {
    key: 'full',
    label: 'Full audit',
    summary: 'Every page plus the 10 newest blog posts. No screenshots.',
    checks: 'Everything the quick audit checks, on the whole site, plus Search Console when connected. Updates the site score, findings and alerts.',
    effort: 'About 20 to 30 minutes. No AI cost.',
    when: 'The weekly schedule runs this. Run it by hand after a bigger change.',
    scope: 'with_posts',
    includeVisual: false,
  },
  {
    key: 'visual',
    label: 'Visual audit',
    summary: 'The full audit plus desktop and mobile screenshots of every page and the newest post, reviewed by the vision model.',
    checks: 'Finds empty sections, cut-off text, overlapping elements, broken layouts and missing images that code checks cannot see.',
    effort: '40 minutes or more. About 1 cent per page in vision calls.',
    when: 'The monthly schedule runs this. Run it by hand after a design or plugin update.',
    scope: 'with_posts',
    includeVisual: true,
  },
]

export const auditKindInfo = (key: AuditKind): AuditKindInfo => AUDIT_KINDS.find((k) => k.key === key)!

export const SCOPE_LABELS: Record<AuditScope, string> = {
  quick: 'Homepage + up to 20 pages',
  with_posts: 'All pages + 10 recent posts',
  full: 'Every URL in the sitemap',
}

export const SCOPE_HINTS: Record<AuditScope, string> = {
  quick: 'Homepage and up to 20 pages: a fast spot check.',
  with_posts: 'Every WordPress Page in the sitemap plus the 10 most recently updated blog posts.',
  full: 'Every URL in the sitemap (pages, posts, other types), up to 500. Slow on large blogs.',
}

/** Classify a recorded run the way the run buttons name them. */
export const describeRunKind = (audit: Pick<Audit, 'scope' | 'include_visual' | 'modules'>): { label: string; tone: 'quick' | 'full' | 'visual' | 'partial' } => {
  if (audit.modules && audit.modules.length > 0) return { label: 'Partial', tone: 'partial' }
  if (audit.include_visual !== false) {
    if (audit.scope === 'quick') return { label: 'Quick + visual', tone: 'visual' }
    return { label: audit.scope === 'full' ? 'Visual · every URL' : 'Visual', tone: 'visual' }
  }
  if (audit.scope === 'quick') return { label: 'Quick', tone: 'quick' }
  return { label: audit.scope === 'full' ? 'Full · every URL' : 'Full', tone: 'full' }
}

export const RUN_KIND_CLASSES: Record<'quick' | 'full' | 'visual' | 'partial', string> = {
  quick: 'bg-slate-100 dark:bg-slate-700/60 text-slate-600 dark:text-slate-300',
  full: 'bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300',
  visual: 'bg-fuchsia-50 dark:bg-fuchsia-950/40 text-fuchsia-700 dark:text-fuchsia-300',
  partial: 'bg-violet-50 dark:bg-violet-950/40 text-violet-700 dark:text-violet-300',
}
