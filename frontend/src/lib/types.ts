export type UserRole = 'admin' | 'viewer'

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  created_at: string
  last_login?: string | null
}

export interface AuthTokens {
  access_token: string
  refresh_token?: string
  token_type?: string
  user?: User
}

export interface Site {
  id: string
  name: string
  url: string
  cron_schedule: string
  notify_email?: string | null
  wp_username?: string | null
  wp_app_password?: string | null
  wp_app_password_configured?: boolean
  nap_name?: string | null
  nap_address?: string | null
  nap_phone?: string | null
  /** Search Console property override ("sc-domain:example.com" or "https://www.example.com/"); null = auto-match. */
  search_console_property?: string | null
  is_active: boolean
  last_audit_at?: string | null
  last_score?: number | null
  created_at: string
  updated_at?: string
  url_redirect_warning?: string | null
  /** Monitoring state from open findings and the latest full run's brief. */
  open_urgent?: number
  open_improve?: number
  new_last_run?: number
  changes_last_run?: number
  state?: 'down' | 'broken' | 'attention' | 'ok' | null
  /** Hourly uptime probe. */
  down_now?: boolean
  down_since?: string | null
  uptime_30d?: number | null
  last_check_at?: string | null
}

export interface UptimeIncident {
  id?: string
  started_at: string
  ended_at?: string | null
  duration_minutes: number
  first_error?: string | null
  status_code?: number | null
  checks_failed?: number
}

export interface UptimeSummary {
  days: number
  checks: number
  uptime_pct: number | null
  down_now: boolean
  down_since?: string | null
  last_check_at?: string | null
  last_status?: number | null
  last_latency_ms?: number | null
  last_note?: string | null
  latency_p50_ms?: number | null
  incidents: UptimeIncident[]
  recent: { at: string; ok: boolean; status?: number | null; latency_ms?: number | null; note?: string | null }[]
}

export interface SiteCreateInput {
  name: string
  url: string
  cron_schedule?: string
  notify_email?: string | null
  wp_username?: string | null
  wp_app_password?: string | null
  nap_name?: string | null
  nap_address?: string | null
  nap_phone?: string | null
  search_console_property?: string | null
  is_active?: boolean
}

export interface SiteUpdateInput extends Partial<SiteCreateInput> {}

export type AuditStatus = 'running' | 'completed' | 'failed' | 'pending' | 'cancelled'

export type AuditScope = 'quick' | 'with_posts' | 'full'

export interface ModuleResult {
  module: string
  /** null = not measured this run (excluded from the overall score). */
  score: number | null
  status: 'pass' | 'warn' | 'fail' | 'error'
  summary: string
  details?: Record<string, any> | Array<any> | string
  metrics?: Record<string, any>
  issues?: string[]
}

export interface Audit {
  id: string
  site_id: string
  site_name?: string
  site_url?: string
  status: AuditStatus
  score: number | null
  triggered_by: string
  scope: AuditScope
  /** Module subset this run was limited to; null/undefined = full run. */
  modules?: string[] | null
  started_at: string
  completed_at?: string | null
  duration_seconds?: number | null
  ai_recommendations?: string | null
  /** Narrative written from the brief by the configured AI provider. */
  ai_summary?: string | null
  brief?: AuditBrief | null
  brief_stats?: BriefStats | null
  results?: Record<string, ModuleResult> | ModuleResult[]
}

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info'

export interface BriefItem {
  type: string
  severity: Severity
  title: string
  module: string
  section: 'urgent' | 'improve'
  url?: string | null
  detail?: Record<string, any>
  fingerprint: string
  is_new?: boolean
  first_seen_at?: string
  times_seen?: number
  muted?: boolean
  mute_kind?: MuteKind | null
  mute_until?: string | null
  mute_note?: string | null
}

export type MuteKind = 'acknowledged' | 'snoozed' | 'accepted'

export interface BriefChange {
  kind: string
  severity: Severity
  title: string
  detail?: Record<string, any>
}

export interface BriefStats {
  urgent: number
  urgent_new: number
  improve: number
  improve_new: number
  changes: number
  changes_notable: number
  resolved: number
  modules_not_measured: number
  muted?: number
  unconfirmed?: number
  downtime?: number
}

export interface AuditBrief {
  version: number
  generated_at: string
  compared_to_run_id?: string | null
  compared_to_at?: string | null
  first_run: boolean
  partial?: boolean
  urgent: BriefItem[]
  changes: BriefChange[]
  improve: BriefItem[]
  resolved: { type: string; severity: Severity; title: string; url?: string | null; module: string; first_seen_at: string; was_muted?: boolean }[]
  /** Open findings a person acknowledged, snoozed or accepted: tracked, not alerting. */
  muted?: BriefItem[]
  /** Urgent findings seen once this run and not reproduced on re-check (dropped). */
  unconfirmed?: { type: string; title: string; url?: string | null; severity: Severity }[]
  downtime?: { started_at: string; ended_at?: string | null; duration_minutes: number; first_error?: string | null; ongoing: boolean }[]
  notes: string[]
  stats: BriefStats
}

export interface Finding {
  id: string
  type: string
  module: string
  severity: Severity
  section: 'urgent' | 'improve'
  title: string
  url?: string | null
  detail?: Record<string, any> | null
  status: 'open' | 'resolved'
  first_seen_at: string
  last_seen_at: string
  resolved_at?: string | null
  times_seen: number
  first_seen_run_id?: string | null
  last_seen_run_id?: string | null
  mute_kind?: MuteKind | null
  mute_until?: string | null
  mute_note?: string | null
  muted_at?: string | null
  muted_by?: string | null
  is_muted?: boolean
}

export interface GoogleTestResult {
  service_account_email: string
  properties: { site_url: string; permission: string }[]
  sites: { site_id: string; site: string; url: string; property: string | null; permission: string | null; override?: string | null }[]
  matched: number
  unmatched: string[]
}

export interface Settings {
  // These match the backend's actual field names exactly (uppercase, like the .env vars they
  // mirror) — GET returns the current value already masked (e.g. "sk-1...bcd3") when configured,
  // or "" when not. Never pre-fill an editable input from these; use the *_configured flags to
  // show a "currently saved" indicator instead, and only send a field on save if the admin
  // actually typed a new value — otherwise omit it so the saved one isn't overwritten with blank.
  OPENAI_API_KEY?: string
  GEMINI_API_KEY?: string
  AI_PROVIDER?: 'openai' | 'gemini'
  GOOGLE_PAGESPEED_API_KEY?: string
  /** Full service-account JSON key; GET never returns it, only the *_configured flags and e-mail. */
  GOOGLE_SERVICE_ACCOUNT_JSON?: string
  RESEND_API_KEY?: string
  RESEND_FROM_EMAIL?: string
  RESEND_FROM_NAME?: string
  ALERT_EMAIL?: string
  FRONTEND_URL?: string
  DEBUG?: boolean
  openai_configured?: boolean
  gemini_configured?: boolean
  resend_configured?: boolean
  pagespeed_configured?: boolean
  google_sc_configured?: boolean
  google_sc_invalid?: boolean
  google_service_account_email?: string | null
  URGENT_CONFIRM_DELAY_SECONDS?: number
  UPTIME_PROBE_MINUTES?: number
}

export interface SchedulerJob {
  id: string
  name: string
  site_id?: string
  site_name?: string
  cron_expression: string
  scope?: string | null
  next_run_time?: string | null
  is_paused?: boolean
}

export interface DashboardStats {
  total_sites: number
  active_sites: number
  audits_today: number
  avg_score: number
  critical_sites: Site[]
  recent_audits: Audit[]
  score_distribution: {
    range: string
    count: number
    color: string
  }[]
}

export interface AuditModuleInfo {
  name: string
  label: string
  /** Share of the overall score (0 = tracked only, not scored). */
  weight: number
  /** Whether the module reads the sitemap crawl / shared page fetch. */
  needs_pages: boolean
}
