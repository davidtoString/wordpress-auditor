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
  is_active: boolean
  last_audit_at?: string | null
  last_score?: number | null
  created_at: string
  updated_at?: string
  url_redirect_warning?: string | null
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
  is_active?: boolean
}

export interface SiteUpdateInput extends Partial<SiteCreateInput> {}

export type AuditStatus = 'running' | 'completed' | 'failed' | 'pending' | 'cancelled'

export type AuditScope = 'quick' | 'with_posts' | 'full'

export interface ModuleResult {
  module: string
  score: number
  status: 'pass' | 'warn' | 'fail'
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
  started_at: string
  completed_at?: string | null
  duration_seconds?: number | null
  ai_recommendations?: string | null
  results?: Record<string, ModuleResult> | ModuleResult[]
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
}

export interface SchedulerJob {
  id: string
  name: string
  site_id?: string
  site_name?: string
  cron_expression: string
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
