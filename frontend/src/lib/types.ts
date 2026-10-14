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
  notification_email?: string | null
  wp_username?: string | null
  wp_app_password?: string | null
  nap_name?: string | null
  nap_address?: string | null
  nap_phone?: string | null
  is_active: boolean
  last_audit_at?: string | null
  last_score?: number | null
  created_at: string
  updated_at?: string
}

export interface SiteCreateInput {
  name: string
  url: string
  cron_schedule?: string
  notification_email?: string | null
  wp_username?: string | null
  wp_app_password?: string | null
  nap_name?: string | null
  nap_address?: string | null
  nap_phone?: string | null
  is_active?: boolean
}

export interface SiteUpdateInput extends Partial<SiteCreateInput> {}

export type AuditStatus = 'running' | 'completed' | 'failed' | 'pending'

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
  started_at: string
  completed_at?: string | null
  duration_seconds?: number | null
  ai_recommendations?: string | null
  results?: Record<string, ModuleResult> | ModuleResult[]
}

export interface Settings {
  openai_api_key?: string
  gemini_api_key?: string
  ai_provider?: 'openai' | 'gemini'
  google_pagespeed_api_key?: string
  resend_api_key?: string
  resend_from_email?: string
  resend_from_name?: string
  alert_email?: string
  score_alert_threshold?: number
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
