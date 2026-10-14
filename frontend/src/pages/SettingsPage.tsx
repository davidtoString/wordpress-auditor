import React, { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Mail,
  Calendar,
  Eye,
  EyeOff,
  Save,
  Send,
  Play,
  Loader2,
  CheckCircle2,
  Sparkles,
  Gauge,
} from 'lucide-react'
import { settings as settingsApi } from '../lib/api'
import type { Settings } from '../lib/types'
import { formatDate } from '../lib/utils'
import toast from 'react-hot-toast'

export const SettingsPage: React.FC = () => {
  const queryClient = useQueryClient()

  // Queries
  const { data: settingsData, isLoading: settingsLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsApi.get(),
  })

  const { data: jobsList = [], isLoading: jobsLoading } = useQuery({
    queryKey: ['scheduler-jobs'],
    queryFn: () => settingsApi.getSchedulerJobs(),
  })

  // State for form
  const [openaiKey, setOpenaiKey] = useState('')
  const [geminiKey, setGeminiKey] = useState('')
  const [aiProvider, setAiProvider] = useState<'openai' | 'gemini'>('openai')
  const [pagespeedKey, setPagespeedKey] = useState('')
  const [resendKey, setResendKey] = useState('')
  const [resendFromEmail, setResendFromEmail] = useState('')
  const [alertEmail, setAlertEmail] = useState('')

  // Eye toggles for masked fields
  const [showOpenai, setShowOpenai] = useState(false)
  const [showGemini, setShowGemini] = useState(false)
  const [showPagespeed, setShowPagespeed] = useState(false)
  const [showResend, setShowResend] = useState(false)

  // Populate from query
  useEffect(() => {
    if (settingsData) {
      setOpenaiKey(settingsData.openai_api_key || '')
      setGeminiKey(settingsData.gemini_api_key || '')
      setAiProvider(settingsData.ai_provider || 'openai')
      setPagespeedKey(settingsData.google_pagespeed_api_key || '')
      setResendKey(settingsData.resend_api_key || '')
      setResendFromEmail(settingsData.resend_from_email || '')
      setAlertEmail(settingsData.alert_email || '')
    }
  }, [settingsData])

  // Save Settings Mutation
  const saveMutation = useMutation({
    mutationFn: (data: Partial<Settings>) => settingsApi.update(data),
    onSuccess: () => {
      toast.success('Configuration settings saved successfully')
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to save settings')
    },
  })

  // Send Test Email Mutation
  const testEmailMutation = useMutation({
    mutationFn: () => settingsApi.testEmail(),
    onSuccess: (res) => {
      toast.success(res.message || 'Test email dispatched successfully!')
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to send test email')
    },
  })

  // Run All Audits Mutation
  const runAllMutation = useMutation({
    mutationFn: () => settingsApi.runAll(),
    onSuccess: (data) => {
      toast.success(data.message || 'Audits triggered for all sites')
      queryClient.invalidateQueries({ queryKey: ['sites'] })
      queryClient.invalidateQueries({ queryKey: ['audits'] })
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Batch audit execution failed')
    },
  })

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    saveMutation.mutate({
      openai_api_key: openaiKey.trim(),
      gemini_api_key: geminiKey.trim(),
      ai_provider: aiProvider,
      google_pagespeed_api_key: pagespeedKey.trim(),
      resend_api_key: resendKey.trim(),
      resend_from_email: resendFromEmail.trim(),
      alert_email: alertEmail.trim(),
    })
  }

  if (settingsLoading) {
    return (
      <div className="py-24 flex flex-col items-center justify-center">
        <Loader2 className="w-8 h-8 text-brand-600 animate-spin mb-3" />
        <p className="text-sm text-slate-500">Loading system settings...</p>
      </div>
    )
  }

  return (
    <div className="space-y-8 pb-12 max-w-4xl">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          Global Settings & Integrations
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          Configure third-party API credentials, AI recommendation engines, email delivery, and scheduler jobs.
        </p>
      </div>

      <form onSubmit={handleSave} className="space-y-8">
        {/* Section 1: AI Provider & Keys */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm space-y-5">
          <div className="flex items-center gap-2.5 pb-2 border-b border-slate-100 dark:border-slate-700/60">
            <div className="p-2 rounded-lg bg-purple-50 dark:bg-purple-950/60 text-purple-600">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                AI Recommendation Engine
              </h3>
              <p className="text-xs text-slate-400">
                Select and configure the LLM provider for automated audit remediation action plans.
              </p>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
              Active AI Provider
            </label>
            <div className="grid grid-cols-2 gap-3 max-w-md">
              <button
                type="button"
                onClick={() => setAiProvider('openai')}
                className={`p-3 rounded-xl border text-left transition-all ${
                  aiProvider === 'openai'
                    ? 'border-brand-500 bg-brand-50/60 dark:bg-brand-950/40 text-brand-700 dark:text-brand-300 ring-2 ring-brand-500/20'
                    : 'border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300'
                }`}
              >
                <div className="font-semibold text-sm">OpenAI</div>
                <div className="text-xs opacity-75">GPT-4o Reasoning</div>
              </button>

              <button
                type="button"
                onClick={() => setAiProvider('gemini')}
                className={`p-3 rounded-xl border text-left transition-all ${
                  aiProvider === 'gemini'
                    ? 'border-brand-500 bg-brand-50/60 dark:bg-brand-950/40 text-brand-700 dark:text-brand-300 ring-2 ring-brand-500/20'
                    : 'border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300'
                }`}
              >
                <div className="font-semibold text-sm">Google Gemini</div>
                <div className="text-xs opacity-75">Gemini 1.5 Flash / Pro</div>
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
            {/* OpenAI API Key */}
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
                OpenAI API Key
              </label>
              <div className="relative">
                <input
                  type={showOpenai ? 'text' : 'password'}
                  value={openaiKey}
                  onChange={(e) => setOpenaiKey(e.target.value)}
                  placeholder="sk-..."
                  className="w-full pl-3.5 pr-10 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
                <button
                  type="button"
                  onClick={() => setShowOpenai(!showOpenai)}
                  className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                  {showOpenai ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Gemini API Key */}
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
                Google Gemini API Key
              </label>
              <div className="relative">
                <input
                  type={showGemini ? 'text' : 'password'}
                  value={geminiKey}
                  onChange={(e) => setGeminiKey(e.target.value)}
                  placeholder="AIza..."
                  className="w-full pl-3.5 pr-10 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
                <button
                  type="button"
                  onClick={() => setShowGemini(!showGemini)}
                  className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                >
                  {showGemini ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Section 2: Google PageSpeed Insights Key */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-2.5 pb-2 border-b border-slate-100 dark:border-slate-700/60">
            <div className="p-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600">
              <Gauge className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                Google PageSpeed API Key
              </h3>
              <p className="text-xs text-slate-400">
                Free Google Insights key for Core Web Vitals (LCP, CLS, FCP, TTFB, and Speed Index).
              </p>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
              PageSpeed API Key
            </label>
            <div className="relative">
              <input
                type={showPagespeed ? 'text' : 'password'}
                value={pagespeedKey}
                onChange={(e) => setPagespeedKey(e.target.value)}
                placeholder="AIza..."
                className="w-full pl-3.5 pr-10 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
              <button
                type="button"
                onClick={() => setShowPagespeed(!showPagespeed)}
                className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                {showPagespeed ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>

        {/* Section 3: Resend Email Configuration */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-100 dark:border-slate-700/60">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-lg bg-blue-50 dark:bg-blue-950/60 text-blue-600">
                <Mail className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                  Transactional Email (Resend)
                </h3>
                <p className="text-xs text-slate-400">
                  Dispatches new user credentials and score drop alert notifications.
                </p>
              </div>
            </div>

            {/* Send Test Email button */}
            <button
              type="button"
              onClick={() => testEmailMutation.mutate()}
              disabled={testEmailMutation.isPending}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-300 transition-colors disabled:opacity-60"
            >
              {testEmailMutation.isPending ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Send className="w-3.5 h-3.5" />
              )}
              Send Test Email
            </button>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
              Resend API Key
            </label>
            <div className="relative">
              <input
                type={showResend ? 'text' : 'password'}
                value={resendKey}
                onChange={(e) => setResendKey(e.target.value)}
                placeholder="re_..."
                className="w-full pl-3.5 pr-10 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
              <button
                type="button"
                onClick={() => setShowResend(!showResend)}
                className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                {showResend ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
                Resend From Email
              </label>
              <input
                type="email"
                value={resendFromEmail}
                onChange={(e) => setResendFromEmail(e.target.value)}
                placeholder="audits@yourdomain.com"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
                Global Alert Recipient Email
              </label>
              <input
                type="email"
                value={alertEmail}
                onChange={(e) => setAlertEmail(e.target.value)}
                placeholder="alerts@yourdomain.com"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
          </div>
        </div>

        {/* Save Button for Settings */}
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={saveMutation.isPending}
            className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold text-white bg-brand-600 hover:bg-brand-700 shadow-md shadow-brand-500/20 disabled:opacity-60 transition-all"
          >
            {saveMutation.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Saving Configuration...
              </>
            ) : (
              <>
                <Save className="w-4 h-4" />
                Save Settings
              </>
            )}
          </button>
        </div>
      </form>

      {/* Section 4: APScheduler Cron Jobs & Batch Run */}
      <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-slate-100 dark:border-slate-700/60">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-amber-50 dark:bg-amber-950/60 text-amber-600">
              <Calendar className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                Automated Cron Scheduler Jobs
              </h3>
              <p className="text-xs text-slate-400">
                Background APScheduler recurring jobs scheduled across your WordPress sites.
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => runAllMutation.mutate()}
            disabled={runAllMutation.isPending}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-xl text-white bg-emerald-600 hover:bg-emerald-700 shadow-sm transition-all disabled:opacity-60 self-start sm:self-auto"
          >
            {runAllMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5 fill-current" />
            )}
            Run All Audits Now
          </button>
        </div>

        {jobsLoading ? (
          <div className="py-8 flex items-center justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-brand-500" />
          </div>
        ) : jobsList.length === 0 ? (
          <div className="py-8 text-center text-xs text-slate-400">
            No active scheduler jobs registered. Adding sites with cron expressions will populate this scheduler queue.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700 text-slate-400 font-semibold uppercase">
                  <th className="py-2.5 px-3">Job Name</th>
                  <th className="py-2.5 px-3">Site Target</th>
                  <th className="py-2.5 px-3">Cron Schedule</th>
                  <th className="py-2.5 px-3">Next Execution</th>
                  <th className="py-2.5 px-3 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {jobsList.map((job) => (
                  <tr key={job.id} className="hover:bg-slate-50 dark:hover:bg-slate-750">
                    <td className="py-3 px-3 font-semibold text-slate-800 dark:text-slate-200">
                      {job.name || job.id}
                    </td>
                    <td className="py-3 px-3 text-slate-600 dark:text-slate-400">
                      {job.site_name || job.site_id || 'System Job'}
                    </td>
                    <td className="py-3 px-3 font-mono text-brand-600 dark:text-brand-400">
                      {job.cron_expression}
                    </td>
                    <td className="py-3 px-3 font-mono text-slate-500">
                      {job.next_run_time ? formatDate(job.next_run_time) : 'Pending next cycle'}
                    </td>
                    <td className="py-3 px-3 text-right">
                      {job.is_paused ? (
                        <span className="text-amber-500 font-medium">Paused</span>
                      ) : (
                        <span className="text-emerald-500 font-medium flex items-center justify-end gap-1">
                          <CheckCircle2 className="w-3 h-3" /> Active
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default SettingsPage
