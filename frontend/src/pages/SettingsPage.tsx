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
  Search,
  Activity,
  AlertTriangle,
} from 'lucide-react'
import { settings as settingsApi } from '../lib/api'
import type { Settings, GoogleTestResult } from '../lib/types'
import { formatDate } from '../lib/utils'
import { describeCron } from '../lib/cron'
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

  // Secret fields: always start blank. The GET response only ever returns a masked preview
  // (e.g. "sk-1...bcd3") or "" — never the real key — so pre-filling the input from it would
  // just show garbage, and re-saving that garbage would corrupt the real stored key. Blank means
  // "leave the saved key alone"; only a field the admin actually types into gets sent on save.
  const [openaiKey, setOpenaiKey] = useState('')
  const [geminiKey, setGeminiKey] = useState('')
  const [aiProvider, setAiProvider] = useState<'openai' | 'gemini'>('openai')
  const [visionModel, setVisionModel] = useState('')
  const [pagespeedKey, setPagespeedKey] = useState('')
  const [resendKey, setResendKey] = useState('')
  const [googleJson, setGoogleJson] = useState('')
  const [googleTest, setGoogleTest] = useState<GoogleTestResult | null>(null)
  const [resendFromEmail, setResendFromEmail] = useState('')
  const [resendFromName, setResendFromName] = useState('')
  const [alertEmail, setAlertEmail] = useState('')

  // Eye toggles for masked fields
  const [showOpenai, setShowOpenai] = useState(false)
  const [showGemini, setShowGemini] = useState(false)
  const [showPagespeed, setShowPagespeed] = useState(false)
  const [showResend, setShowResend] = useState(false)

  // Populate only the non-secret fields from the fetched data (these aren't masked, so showing
  // and re-saving the real value is fine). AI_PROVIDER has a real default even when unset.
  useEffect(() => {
    if (settingsData) {
      setAiProvider(settingsData.AI_PROVIDER || 'openai')
      setVisionModel(settingsData.VISION_MODEL || '')
      setResendFromEmail(settingsData.RESEND_FROM_EMAIL || '')
      setResendFromName(settingsData.RESEND_FROM_NAME || '')
      setAlertEmail(settingsData.ALERT_EMAIL || '')
    }
  }, [settingsData])

  // Save Settings Mutation
  const saveMutation = useMutation({
    mutationFn: (data: Partial<Settings>) => settingsApi.update(data),
    onSuccess: () => {
      toast.success('Configuration settings saved successfully')
      // Clear the secret inputs so the UI doesn't look like they're still sitting there
      // unsaved — the "Currently saved" badge (driven by the refetched *_configured flags)
      // is what actually confirms the save now.
      setOpenaiKey('')
      setGeminiKey('')
      setPagespeedKey('')
      setResendKey('')
      setGoogleJson('')
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

  const testGoogleMutation = useMutation({
    mutationFn: () => settingsApi.testGoogle(),
    onSuccess: (res) => {
      setGoogleTest(res)
      toast.success(`Google OK: ${res.properties.length} properties visible, ${res.matched} of ${res.sites.length} sites matched`)
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Google connection failed'),
  })

  const uptimeNowMutation = useMutation({
    mutationFn: () => settingsApi.runUptimeNow(),
    onSuccess: (res) => {
      if (res.down.length) toast.error(`${res.down.length} site(s) down: ${res.down.join(', ')}`)
      else toast.success(`All ${res.checked} sites answered`)
      queryClient.invalidateQueries({ queryKey: ['sites'] })
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || 'Probe failed'),
  })

  // Run All Audits Mutation
  const runAllMutation = useMutation({
    mutationFn: (visual: boolean) => settingsApi.runAll(visual),
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
    const payload: Partial<Settings> = {
      AI_PROVIDER: aiProvider,
      VISION_MODEL: visionModel.trim(),
      RESEND_FROM_EMAIL: resendFromEmail.trim(),
      RESEND_FROM_NAME: resendFromName.trim(),
      ALERT_EMAIL: alertEmail.trim(),
    }
    // Secrets: only include ones the admin actually typed a new value into, so leaving a field
    // blank keeps whatever was already saved instead of overwriting it with an empty string.
    if (openaiKey.trim()) payload.OPENAI_API_KEY = openaiKey.trim()
    if (geminiKey.trim()) payload.GEMINI_API_KEY = geminiKey.trim()
    if (pagespeedKey.trim()) payload.GOOGLE_PAGESPEED_API_KEY = pagespeedKey.trim()
    if (resendKey.trim()) payload.RESEND_API_KEY = resendKey.trim()
    if (googleJson.trim()) payload.GOOGLE_SERVICE_ACCOUNT_JSON = googleJson.trim()

    saveMutation.mutate(payload)
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
                <div className="text-xs opacity-75">GPT-4o / GPT-4o mini</div>
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
                <div className="text-xs opacity-75">Gemini 3.5 Flash / Flash-Lite</div>
              </button>
            </div>
            <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">
              Used for the written brief narrative. The visual inspection picks its own model below.
            </p>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
              Visual inspection model
            </label>
            <div className="flex flex-wrap items-center gap-3 max-w-xl">
              <select
                value={(settingsData?.VISION_MODEL_OPTIONS || []).some((o) => o.id === visionModel) ? visionModel : '__custom'}
                onChange={(e) => setVisionModel(e.target.value === '__custom' ? '' : e.target.value)}
                className="px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-100"
              >
                {(settingsData?.VISION_MODEL_OPTIONS || []).map((o) => (
                  <option key={o.id} value={o.id}>{o.label}</option>
                ))}
                <option value="__custom">Other model id…</option>
              </select>
              {!(settingsData?.VISION_MODEL_OPTIONS || []).some((o) => o.id === visionModel) && (
                <input
                  type="text"
                  value={visionModel}
                  onChange={(e) => setVisionModel(e.target.value)}
                  placeholder="e.g. gemini-3.5-flash-lite"
                  className="px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-100 w-64"
                />
              )}
            </div>
            <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">
              Judges every screenshot section for broken layouts. A Gemini model needs the Gemini key, others the OpenAI key; if that key
              is missing the other provider is used automatically. Gemini 3.5 Flash-Lite found the same defects as GPT-4o in testing at about a fifth of the cost.
              {visionModel.startsWith('gemini') && settingsData && !settingsData.gemini_configured && (
                <span className="text-amber-600 dark:text-amber-400"> No Gemini key is saved, so GPT-4o will be used until one is added.</span>
              )}
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
            {/* OpenAI API Key */}
            <div>
              <label className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
                <span>OpenAI API Key</span>
                {settingsData?.openai_configured && (
                  <span className="inline-flex items-center gap-1 normal-case font-medium text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 className="w-3 h-3" />
                    Currently saved
                  </span>
                )}
              </label>
              <div className="relative">
                <input
                  type={showOpenai ? 'text' : 'password'}
                  value={openaiKey}
                  onChange={(e) => setOpenaiKey(e.target.value)}
                  placeholder={settingsData?.openai_configured ? 'Leave blank to keep the saved key' : 'sk-...'}
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
              <label className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
                <span>Google Gemini API Key</span>
                {settingsData?.gemini_configured && (
                  <span className="inline-flex items-center gap-1 normal-case font-medium text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 className="w-3 h-3" />
                    Currently saved
                  </span>
                )}
              </label>
              <div className="relative">
                <input
                  type={showGemini ? 'text' : 'password'}
                  value={geminiKey}
                  onChange={(e) => setGeminiKey(e.target.value)}
                  placeholder={settingsData?.gemini_configured ? 'Leave blank to keep the saved key' : 'AIza...'}
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
            <label className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
              <span>PageSpeed API Key</span>
              {settingsData?.pagespeed_configured && (
                <span className="inline-flex items-center gap-1 normal-case font-medium text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="w-3 h-3" />
                  Currently saved
                </span>
              )}
            </label>
            <div className="relative">
              <input
                type={showPagespeed ? 'text' : 'password'}
                value={pagespeedKey}
                onChange={(e) => setPagespeedKey(e.target.value)}
                placeholder={settingsData?.pagespeed_configured ? 'Leave blank to keep the saved key' : 'AIza...'}
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

        {/* Section 2b: Google Search Console (service account) */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-100 dark:border-slate-700/60">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-lg bg-sky-50 dark:bg-sky-950/60 text-sky-600">
                <Search className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">Google Search Console</h3>
                <p className="text-xs text-slate-400">
                  Index status of key pages, search clicks trend, sitemap errors, Google's chosen canonical. One service account for every site.
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => testGoogleMutation.mutate()}
              disabled={testGoogleMutation.isPending || !settingsData?.google_sc_configured}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-300 transition-colors disabled:opacity-60"
            >
              {testGoogleMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
              Test connection
            </button>
          </div>

          <div className="p-3 rounded-xl bg-sky-50/70 dark:bg-sky-950/30 border border-sky-200 dark:border-sky-900/50 text-xs text-sky-900 dark:text-sky-200 space-y-1">
            <p className="font-semibold">Setup (once):</p>
            <ol className="list-decimal ml-4 space-y-0.5">
              <li>Google Cloud Console → a project → <strong>APIs &amp; Services → Enable</strong> the <em>Google Search Console API</em>.</li>
              <li><strong>IAM &amp; Admin → Service Accounts → Create</strong>; then <strong>Keys → Add key → JSON</strong>. Paste the downloaded file below.</li>
              <li>
                In Search Console, open each property → <strong>Settings → Users and permissions → Add user</strong> with the service account
                e-mail{settingsData?.google_service_account_email ? <> (<code className="font-mono">{settingsData.google_service_account_email}</code>)</> : ''}, permission
                <em> Full</em> (URL inspection needs Full or Owner).
              </li>
            </ol>
            <p className="text-sky-800/80 dark:text-sky-300/80">
              The API does not expose the Manual actions or Security issues reports; those stay in the Search Console UI.
            </p>
          </div>

          <div>
            <label className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
              <span>Service account key (JSON)</span>
              {settingsData?.google_sc_configured && (
                <span className="inline-flex items-center gap-1 normal-case font-medium text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="w-3 h-3" />
                  Saved: {settingsData.google_service_account_email}
                </span>
              )}
              {settingsData?.google_sc_invalid && (
                <span className="inline-flex items-center gap-1 normal-case font-medium text-rose-600">
                  <AlertTriangle className="w-3 h-3" />
                  Saved value is not a valid key
                </span>
              )}
            </label>
            <textarea
              value={googleJson}
              onChange={(e) => setGoogleJson(e.target.value)}
              rows={4}
              spellCheck={false}
              placeholder={settingsData?.google_sc_configured ? 'Leave blank to keep the saved key; paste a new JSON file to replace it' : '{ "type": "service_account", "project_id": "...", "private_key": "-----BEGIN PRIVATE KEY-----...", "client_email": "...@....iam.gserviceaccount.com", ... }'}
              className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>

          {googleTest && (
            <div className="text-xs space-y-2">
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {googleTest.properties.length} propert{googleTest.properties.length === 1 ? 'y' : 'ies'} visible to {googleTest.service_account_email}
              </div>
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="text-slate-400 uppercase border-b border-slate-200 dark:border-slate-700">
                    <th className="py-1.5 pr-3">Site</th>
                    <th className="py-1.5 pr-3">Matched property</th>
                    <th className="py-1.5">Permission</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {googleTest.sites.map((m) => (
                    <tr key={m.site_id}>
                      <td className="py-1.5 pr-3 text-slate-700 dark:text-slate-200">{m.site}</td>
                      <td className="py-1.5 pr-3 font-mono">
                        {m.property ? <span className="text-emerald-700 dark:text-emerald-400">{m.property}</span> : <span className="text-rose-600">no access — add the service account to this property</span>}
                      </td>
                      <td className="py-1.5 text-slate-500">{m.permission || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {googleTest.properties.length > 0 && (
                <details className="text-slate-500">
                  <summary className="cursor-pointer">All visible properties</summary>
                  <ul className="mt-1 font-mono space-y-0.5">
                    {googleTest.properties.map((p) => (
                      <li key={p.site_url}>{p.site_url} <span className="text-slate-400">({p.permission})</span></li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
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
            <label className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
              <span>Resend API Key</span>
              {settingsData?.resend_configured && (
                <span className="inline-flex items-center gap-1 normal-case font-medium text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="w-3 h-3" />
                  Currently saved
                </span>
              )}
            </label>
            <div className="relative">
              <input
                type={showResend ? 'text' : 'password'}
                value={resendKey}
                onChange={(e) => setResendKey(e.target.value)}
                placeholder={settingsData?.resend_configured ? 'Leave blank to keep the saved key' : 're_...'}
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
                Resend From Name
              </label>
              <input
                type="text"
                value={resendFromName}
                onChange={(e) => setResendFromName(e.target.value)}
                placeholder="WP Auditor"
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
                Scheduled Audits
              </h3>
              <p className="text-xs text-slate-400">
                Every scheduled run is a full audit (all sitemap URLs, Lighthouse on up to 60). Times are Mexico City.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 self-start sm:self-auto">
          <button
            type="button"
            onClick={() => uptimeNowMutation.mutate()}
            disabled={uptimeNowMutation.isPending}
            title="Probe every active site's homepage now (the job also runs hourly)"
            className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-xl border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-750 transition-all disabled:opacity-60"
          >
            {uptimeNowMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Activity className="w-3.5 h-3.5" />}
            Check uptime now
          </button>
          <button
            type="button"
            onClick={() => runAllMutation.mutate(false)}
            disabled={runAllMutation.isPending}
            title="Queue each active site's regular audit now (every module except the visual inspection, at the site's scope)"
            className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-xl text-white bg-emerald-600 hover:bg-emerald-700 shadow-sm transition-all disabled:opacity-60"
          >
            {runAllMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5 fill-current" />
            )}
            Run Regular Audits on All Sites
          </button>
          <button
            type="button"
            onClick={() => runAllMutation.mutate(true)}
            disabled={runAllMutation.isPending}
            title="Queue each active site's visual audit now (everything incl. screenshots and vision review; slow, uses vision credits)"
            className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold rounded-xl border border-emerald-600 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-50 dark:hover:bg-emerald-950/40 transition-all disabled:opacity-60"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            Run Visual Audits on All Sites
          </button>
          </div>
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
                  <th className="py-2.5 px-3">Schedule</th>
                  <th className="py-2.5 px-3">Next Execution</th>
                  <th className="py-2.5 px-3 text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {jobsList.map((job) => (
                  <tr key={job.id} className="hover:bg-slate-50 dark:hover:bg-slate-750">
                    <td className="py-3 px-3 font-semibold text-slate-800 dark:text-slate-200">
                      {job.site_id
                        ? `${job.kind === 'visual' ? 'Visual audit' : 'Regular audit'} · ${job.scope === 'full' ? 'full website' : 'pages + recent posts'}`
                        : job.name || job.id}
                    </td>
                    <td className="py-3 px-3 text-slate-600 dark:text-slate-400">
                      {job.site_name || job.site_id || 'System Job'}
                    </td>
                    <td className="py-3 px-3 text-brand-600 dark:text-brand-400" title={job.cron_expression}>
                      {job.site_id ? describeCron(job.cron_expression) : job.cron_expression}
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
