import axios, { AxiosError } from 'axios'
import type {
  User,
  AuthTokens,
  Site,
  SiteCreateInput,
  SiteUpdateInput,
  Audit,
  AuditScope,
  ModuleResult,
  Settings,
  SchedulerJob,
  AuditModuleInfo,
  Finding,
  MuteKind,
  UptimeSummary,
  GoogleTestResult,
} from './types'

export const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor: add Authorization Bearer token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token')
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor: on 401, clear tokens and redirect to /login
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('user')

      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export const auth = {
  async login(email: string, password: string): Promise<AuthTokens> {
    const response = await api.post<AuthTokens>('/auth/login', { email, password })
    return response.data
  },
  async refreshToken(refreshToken: string): Promise<AuthTokens> {
    const response = await api.post<AuthTokens>('/auth/refresh', { refresh_token: refreshToken })
    return response.data
  },
  async getMe(): Promise<User> {
    const response = await api.get<User>('/auth/me')
    return response.data
  },
  async updateMe(data: Partial<User>): Promise<User> {
    const response = await api.put<User>('/auth/me', data)
    return response.data
  },
  async changePassword(currentPassword: string, newPassword: string): Promise<{ message: string }> {
    const response = await api.post<{ message: string }>('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    })
    return response.data
  },
}

export const users = {
  async list(page?: number, pageSize?: number): Promise<{ users: User[]; total?: number }> {
    const response = await api.get<{ users: User[]; total?: number } | User[]>('/users', {
      params: { page, page_size: pageSize },
    })
    if (Array.isArray(response.data)) {
      return { users: response.data, total: response.data.length }
    }
    return response.data
  },
  async create(data: { email: string; full_name: string; role: 'admin' | 'viewer'; password?: string }): Promise<User> {
    const response = await api.post<User>('/users', data)
    return response.data
  },
  async get(id: string): Promise<User> {
    const response = await api.get<User>(`/users/${id}`)
    return response.data
  },
  async update(id: string, data: Partial<User>): Promise<User> {
    const response = await api.put<User>(`/users/${id}`, data)
    return response.data
  },
  async deactivate(id: string): Promise<{ message: string; user?: User }> {
    const response = await api.post<{ message: string; user?: User }>(`/users/${id}/deactivate`)
    return response.data
  },
  async resetPassword(id: string): Promise<{ message: string }> {
    const response = await api.post<{ message: string }>(`/users/${id}/reset-password`)
    return response.data
  },
}

export const sites = {
  async list(): Promise<Site[]> {
    const response = await api.get<Site[]>('/sites')
    return response.data
  },
  async create(data: SiteCreateInput): Promise<Site> {
    const response = await api.post<Site>('/sites', data)
    return response.data
  },
  async get(id: string): Promise<Site> {
    const response = await api.get<Site>(`/sites/${id}`)
    return response.data
  },
  async update(id: string, data: SiteUpdateInput): Promise<Site> {
    const response = await api.put<Site>(`/sites/${id}`, data)
    return response.data
  },
  async delete(id: string): Promise<{ message: string }> {
    const response = await api.delete<{ message: string }>(`/sites/${id}`)
    return response.data
  },
  async testWpConnection(id: string): Promise<{ success: boolean; message: string }> {
    const response = await api.post<{ success: boolean; message: string }>(
      `/sites/${id}/test-wp-connection`
    )
    return response.data
  },
  async triggerAudit(
    id: string,
    scope: AuditScope = 'quick',
    modules: string[] | null = null,
    includeVisual: boolean = true
  ): Promise<Audit> {
    // `modules` null/empty = run every module; otherwise a subset of names from audits.listModules().
    // includeVisual=false runs a complete audit without the visual inspection (what the weekly schedule does).
    const response = await api.post<Audit>(`/sites/${id}/audit`, {
      scope,
      modules: modules && modules.length > 0 ? modules : null,
      include_visual: includeVisual,
    })
    return response.data
  },
  async getFindings(id: string, status: 'open' | 'resolved' | 'all' | 'muted' = 'open'): Promise<Finding[]> {
    const response = await api.get<Finding[]>(`/sites/${id}/findings`, { params: { status } })
    return response.data
  },
  async muteFinding(siteId: string, findingId: string, kind: MuteKind, days?: number, note?: string): Promise<Finding> {
    const response = await api.post<Finding>(`/sites/${siteId}/findings/${findingId}/mute`, { kind, days, note })
    return response.data
  },
  async unmuteFinding(siteId: string, findingId: string): Promise<Finding> {
    const response = await api.delete<Finding>(`/sites/${siteId}/findings/${findingId}/mute`)
    return response.data
  },
  async verifyFinding(siteId: string, findingId: string): Promise<{ audit_run_id: string; modules: string[]; message: string }> {
    const response = await api.post(`/sites/${siteId}/findings/${findingId}/verify`)
    return response.data
  },
  async getUptime(id: string, days = 30): Promise<UptimeSummary> {
    const response = await api.get<UptimeSummary>(`/sites/${id}/uptime`, { params: { days } })
    return response.data
  },
  async checkUptimeNow(id: string): Promise<{ ok: boolean | null; status?: number; latency_ms?: number | null; error?: string | null; transition?: string | null }> {
    const response = await api.post(`/sites/${id}/uptime/check`)
    return response.data
  },
  async getHistory(id: string, page?: number): Promise<{ audits: Audit[]; total?: number }> {
    const response = await api.get<{ audits: Audit[]; total?: number } | Audit[]>(`/sites/${id}/history`, {
      params: { page },
    })
    if (Array.isArray(response.data)) {
      return { audits: response.data, total: response.data.length }
    }
    return response.data
  },
}

export const audits = {
  async listModules(): Promise<AuditModuleInfo[]> {
    const response = await api.get<AuditModuleInfo[]>('/audits/modules')
    return response.data
  },
  async list(page?: number, pageSize?: number): Promise<{ audits: Audit[]; total?: number }> {
    const response = await api.get<{ audits: Audit[]; total?: number } | Audit[]>('/audits', {
      params: { page, page_size: pageSize },
    })
    if (Array.isArray(response.data)) {
      return { audits: response.data, total: response.data.length }
    }
    return response.data
  },
  async get(id: string): Promise<Audit> {
    const response = await api.get<Audit>(`/audits/${id}`)
    return response.data
  },
  async cancel(id: string): Promise<{ message: string }> {
    const response = await api.post<{ message: string }>(`/audits/${id}/cancel`)
    return response.data
  },
  async getResults(id: string): Promise<Record<string, ModuleResult> | ModuleResult[]> {
    const response = await api.get<Record<string, ModuleResult> | ModuleResult[]>(`/audits/${id}/results`)
    return response.data
  },
  async exportReport(id: string, format: 'markdown' | 'json'): Promise<{ blob: Blob; filename: string }> {
    const response = await api.get(`/audits/${id}/export`, {
      params: { format },
      responseType: 'blob',
    })
    const disposition: string = response.headers['content-disposition'] || ''
    const match = disposition.match(/filename="?([^"]+)"?/)
    const fallbackExt = format === 'json' ? 'json' : 'md'
    const filename = match ? match[1] : `audit-${id.slice(0, 8)}.${fallbackExt}`
    return { blob: response.data, filename }
  },
  async getLatest(siteId: string): Promise<Audit | null> {
    try {
      const response = await api.get<Audit>(`/sites/${siteId}/latest-audit`)
      return response.data
    } catch (err: any) {
      if (err.response?.status === 404) return null
      // try fallback
      const response2 = await api.get<Audit>(`/audits/latest/${siteId}`)
      return response2.data
    }
  },
}

export const settings = {
  async get(): Promise<Settings> {
    const response = await api.get<Settings>('/settings')
    return response.data
  },
  async update(data: Partial<Settings>): Promise<Settings> {
    const response = await api.put<Settings>('/settings', data)
    return response.data
  },
  async testEmail(): Promise<{ message: string; success: boolean }> {
    const response = await api.post<{ message: string; success: boolean }>('/settings/test-email')
    return response.data
  },
  async getSchedulerJobs(): Promise<SchedulerJob[]> {
    const response = await api.get<SchedulerJob[]>('/settings/scheduler/jobs')
    return response.data
  },
  async runAll(visual = false): Promise<{ message: string; count?: number; kind?: string }> {
    const response = await api.post<{ message: string; count?: number; kind?: string }>('/settings/scheduler/run-all', null, {
      params: { visual },
    })
    return response.data
  },
  async testGoogle(): Promise<GoogleTestResult> {
    const response = await api.post<GoogleTestResult>('/settings/test-google')
    return response.data
  },
  async runUptimeNow(): Promise<{ checked: number; down: string[] }> {
    const response = await api.post<{ checked: number; down: string[] }>('/settings/uptime/run-now')
    return response.data
  },
}

export default api
