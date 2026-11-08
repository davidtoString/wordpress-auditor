import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Globe,
  Mail,
  KeyRound,
  MapPin,
  ChevronDown,
  ChevronUp,
  Loader2,
  Info,
  Check,
  Clock,
  ShieldCheck,
  ShieldAlert,
  PlugZap,
} from 'lucide-react'
import type { Site, SiteCreateInput } from '../lib/types'
import { sites as sitesApi } from '../lib/api'
import { DEFAULT_SCHEDULE, WEEKDAYS, buildCron, describeCron, parseCron, type SimpleSchedule } from '../lib/cron'

interface SiteFormProps {
  initialValues?: Partial<Site>
  onSubmit: (values: SiteCreateInput) => Promise<void>
  isSubmitting: boolean
  title: string
  subtitle: string
}

export const SiteForm: React.FC<SiteFormProps> = ({
  initialValues,
  onSubmit,
  isSubmitting,
  title,
  subtitle,
}) => {
  const navigate = useNavigate()

  const [name, setName] = useState(initialValues?.name || '')
  const [url, setUrl] = useState(initialValues?.url || '')
  const [cronSchedule, setCronSchedule] = useState(initialValues?.cron_schedule || '0 6 * * *')
  const [notificationEmail, setNotificationEmail] = useState(initialValues?.notify_email || '')
  const [isActive, setIsActive] = useState(initialValues?.is_active !== false)

  // Collapsible sections
  const [showWpCredentials, setShowWpCredentials] = useState(
    !!initialValues?.wp_username || !!initialValues?.wp_app_password_configured
  )
  const [wpUsername, setWpUsername] = useState(initialValues?.wp_username || '')
  const [wpAppPassword, setWpAppPassword] = useState(initialValues?.wp_app_password || '')
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle')
  const [testMessage, setTestMessage] = useState('')

  const handleTestConnection = async () => {
    if (!initialValues?.id) return
    setTestStatus('testing')
    setTestMessage('')
    try {
      const result = await sitesApi.testWpConnection(initialValues.id)
      setTestStatus(result.success ? 'success' : 'error')
      setTestMessage(result.message)
    } catch (err: any) {
      setTestStatus('error')
      setTestMessage(err.response?.data?.detail || 'Connection test failed.')
    }
  }

  const [showNapConfig, setShowNapConfig] = useState(
    !!initialValues?.nap_name || !!initialValues?.nap_address || !!initialValues?.nap_phone
  )
  const [napName, setNapName] = useState(initialValues?.nap_name || '')
  const [napAddress, setNapAddress] = useState(initialValues?.nap_address || '')
  const [napPhone, setNapPhone] = useState(initialValues?.nap_phone || '')
  const [scProperty, setScProperty] = useState(initialValues?.search_console_property || '')

  const [showRawCron, setShowRawCron] = useState(false)
  const simpleSchedule = parseCron(cronSchedule)
  const scheduleBase: SimpleSchedule = simpleSchedule ?? DEFAULT_SCHEDULE
  const setSchedule = (patch: Partial<SimpleSchedule>) => {
    setCronSchedule(buildCron({ ...scheduleBase, ...patch }))
    setIsActive(true)
  }
  const chipClass = (active: boolean) =>
    `text-xs px-2.5 py-1 rounded-lg border transition-colors ${
      active
        ? 'bg-brand-50 dark:bg-brand-950/60 border-brand-500 text-brand-600 dark:text-brand-400 font-semibold'
        : 'border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400'
    }`
  const isKind = (kind: SimpleSchedule['kind'], dow?: number) =>
    isActive && !!simpleSchedule && simpleSchedule.kind === kind && (dow === undefined || simpleSchedule.dow === dow)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    let normalizedUrl = url.trim()
    if (!normalizedUrl.startsWith('http://') && !normalizedUrl.startsWith('https://')) {
      normalizedUrl = `https://${normalizedUrl}`
    }

    const payload: SiteCreateInput = {
      name: name.trim(),
      url: normalizedUrl,
      cron_schedule: cronSchedule.trim(),
      notify_email: notificationEmail.trim() || null,
      is_active: isActive,
      wp_username: wpUsername.trim() || null,
      wp_app_password: wpAppPassword.trim() || null,
      nap_name: napName.trim() || null,
      nap_address: napAddress.trim() || null,
      nap_phone: napPhone.trim() || null,
      search_console_property: scProperty.trim() || null,
    }

    await onSubmit(payload)
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6 pb-12">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          {title}
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">{subtitle}</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Core Settings Card */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm space-y-5">
          <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <Globe className="w-4 h-4 text-brand-500" />
            General Site Information
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="name"
                className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5"
              >
                Site Name <span className="text-rose-500">*</span>
              </label>
              <input
                id="name"
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Acme Corporate Blog"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>

            <div>
              <label
                htmlFor="url"
                className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5"
              >
                Website URL <span className="text-rose-500">*</span>
              </label>
              <input
                id="url"
                type="text"
                required
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://example.com"
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
          </div>

          {/* Schedule */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
              Audit Schedule{' '}
              <span className="normal-case font-normal text-slate-400">(Mexico City time)</span>
            </label>

            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => setSchedule({ kind: 'daily' })} className={chipClass(isKind('daily'))}>
                Every day
              </button>
              {WEEKDAYS.map((w) => (
                <button
                  key={w.value}
                  type="button"
                  onClick={() => setSchedule({ kind: 'weekly', dow: w.value })}
                  className={chipClass(isKind('weekly', w.value))}
                  title={`Every ${w.label}`}
                >
                  {w.short}
                </button>
              ))}
              <button type="button" onClick={() => setSchedule({ kind: 'weekdays' })} className={chipClass(isKind('weekdays'))}>
                Weekdays
              </button>
              <button type="button" onClick={() => setSchedule({ kind: 'monthly', dom: 1 })} className={chipClass(isKind('monthly'))}>
                1st of month
              </button>
              <button
                type="button"
                onClick={() => setIsActive(false)}
                className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                  !isActive
                    ? 'bg-slate-200 dark:bg-slate-700 border-slate-400 dark:border-slate-500 text-slate-700 dark:text-slate-200 font-semibold'
                    : 'border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400'
                }`}
              >
                Manual only
              </button>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-slate-400" />
                <span className="text-xs text-slate-500">at</span>
                <select
                  value={scheduleBase.hour}
                  disabled={!isActive || !simpleSchedule}
                  onChange={(e) => setSchedule({ hour: Number(e.target.value) })}
                  className="px-2.5 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50"
                >
                  {Array.from({ length: 24 }, (_, h) => (
                    <option key={h} value={h}>
                      {h % 12 === 0 ? 12 : h % 12} {h < 12 ? 'AM' : 'PM'}
                    </option>
                  ))}
                </select>
                <select
                  value={scheduleBase.minute}
                  disabled={!isActive || !simpleSchedule}
                  onChange={(e) => setSchedule({ minute: Number(e.target.value) })}
                  className="px-2.5 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50"
                >
                  {[0, 15, 30, 45].map((m) => (
                    <option key={m} value={m}>
                      :{String(m).padStart(2, '0')}
                    </option>
                  ))}
                </select>
              </div>
              {isActive && (
                <span className="text-sm font-medium text-slate-800 dark:text-slate-200">
                  {describeCron(cronSchedule)}
                </span>
              )}
              <button
                type="button"
                onClick={() => setShowRawCron((v) => !v)}
                className="ml-auto text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 underline-offset-2 hover:underline"
              >
                {showRawCron ? 'Hide cron expression' : 'Edit cron expression'}
              </button>
            </div>

            {(showRawCron || (isActive && !simpleSchedule)) && (
              <div className="mt-2">
                <input
                  id="cronSchedule"
                  type="text"
                  required={isActive}
                  disabled={!isActive}
                  value={cronSchedule}
                  onChange={(e) => setCronSchedule(e.target.value)}
                  placeholder="0 6 * * 1"
                  className="w-full px-3.5 py-2 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50 disabled:cursor-not-allowed"
                />
                <p className="text-xs text-slate-400 mt-1">
                  Five fields: minute hour day-of-month month day-of-week (0 = Sunday). Expressions outside the presets are kept as typed.
                </p>
              </div>
            )}

            <p className="text-xs text-slate-400 mt-2">
              {isActive
                ? 'Scheduled audits always run the full scope: every page and post in the sitemap (up to 500 URLs), Lighthouse on up to 60 of them, plus WordPress, security, SEO and Search Console checks. Sites sharing a slot run one after another.'
                : 'Automated scheduled audits are off for this site — audits only run when triggered manually.'}
            </p>
          </div>

          {/* Notification Email Override */}
          <div>
            <label
              htmlFor="notificationEmail"
              className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5"
            >
              Alert Notification Email (Override)
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-400">
                <Mail className="w-4 h-4" />
              </div>
              <input
                id="notificationEmail"
                type="email"
                value={notificationEmail}
                onChange={(e) => setNotificationEmail(e.target.value)}
                placeholder="alerts@clientdomain.com (defaults to global alert email)"
                className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
          </div>

          {/* Active status */}
          <div className="pt-2 flex items-center gap-3">
            <input
              id="isActive"
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="w-4 h-4 rounded text-brand-600 focus:ring-brand-500 border-slate-300 dark:border-slate-700"
            />
            <label
              htmlFor="isActive"
              className="text-sm font-medium text-slate-800 dark:text-slate-200 cursor-pointer"
            >
              Enable automated scheduled audits for this site
            </label>
          </div>
        </div>

        {/* WP Credentials Section (Collapsible) */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm">
          <button
            type="button"
            onClick={() => setShowWpCredentials(!showWpCredentials)}
            className="w-full flex items-center justify-between text-left"
          >
            <div className="flex items-center gap-2">
              <KeyRound className="w-4 h-4 text-purple-500" />
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                  Integration Credentials (Optional)
                </h3>
                <p className="text-xs text-slate-400">
                  WordPress REST API credentials for deep diagnostics (plugin list, debug output across pages).
                </p>
              </div>
            </div>
            {showWpCredentials ? (
              <ChevronUp className="w-5 h-5 text-slate-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-slate-400" />
            )}
          </button>

          {showWpCredentials && (
            <div className="mt-5 pt-5 border-t border-slate-100 dark:border-slate-700/60 space-y-4">
              <div className="p-3 rounded-xl bg-purple-50/70 dark:bg-purple-950/30 border border-purple-200 dark:border-purple-900/50 text-xs text-purple-900 dark:text-purple-300 flex items-start gap-2">
                <Info className="w-4 h-4 shrink-0 text-purple-600 mt-0.5" />
                <span>
                  In your WordPress admin, navigate to <strong>Users &rarr; Profile &rarr; Application Passwords</strong> to generate a unique revocable application token.
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="wpUsername"
                    className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5"
                  >
                    WP Username
                  </label>
                  <input
                    id="wpUsername"
                    type="text"
                    value={wpUsername}
                    onChange={(e) => setWpUsername(e.target.value)}
                    placeholder="auditor_bot"
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  />
                </div>

                <div>
                  <label
                    htmlFor="wpAppPassword"
                    className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5"
                  >
                    <span>Application Password</span>
                    {initialValues?.wp_app_password_configured && (
                      <span className="inline-flex items-center gap-1 normal-case font-medium text-emerald-600 dark:text-emerald-400">
                        <Check className="w-3 h-3" />
                        Currently saved
                      </span>
                    )}
                  </label>
                  <input
                    id="wpAppPassword"
                    type="password"
                    value={wpAppPassword}
                    onChange={(e) => setWpAppPassword(e.target.value)}
                    placeholder={
                      initialValues?.wp_app_password_configured
                        ? 'Leave blank to keep the saved password'
                        : 'xxxx xxxx xxxx xxxx'
                    }
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
                  />
                </div>
              </div>

              {initialValues?.id && (
                <div className="space-y-2">
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={handleTestConnection}
                      disabled={testStatus === 'testing' || !initialValues?.wp_app_password_configured}
                      className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-lg text-slate-700 dark:text-slate-200 bg-slate-100 dark:bg-slate-700/70 hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors disabled:opacity-50"
                    >
                      {testStatus === 'testing' ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <PlugZap className="w-3.5 h-3.5" />
                      )}
                      Test Connection
                    </button>
                    <span className="text-[11px] text-slate-400">
                      Tests the currently saved credentials — save first if you just changed them above.
                    </span>
                  </div>
                  {testStatus === 'success' && (
                    <div className="flex items-start gap-1.5 text-xs text-emerald-700 dark:text-emerald-400">
                      <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5" />
                      <span>{testMessage}</span>
                    </div>
                  )}
                  {testStatus === 'error' && (
                    <div className="flex items-start gap-1.5 text-xs text-rose-700 dark:text-rose-400">
                      <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
                      <span>{testMessage}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* NAP Configuration (Collapsible) */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm">
          <button
            type="button"
            onClick={() => setShowNapConfig(!showNapConfig)}
            className="w-full flex items-center justify-between text-left"
          >
            <div className="flex items-center gap-2">
              <MapPin className="w-4 h-4 text-emerald-500" />
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                  NAP Consistency Configuration (Optional)
                </h3>
                <p className="text-xs text-slate-400">
                  Configure expected NAP (Name, Address, Phone) for local SEO consistency checking.
                </p>
              </div>
            </div>
            {showNapConfig ? (
              <ChevronUp className="w-5 h-5 text-slate-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-slate-400" />
            )}
          </button>

          {showNapConfig && (
            <div className="mt-5 pt-5 border-t border-slate-100 dark:border-slate-700/60 space-y-4">
              <div className="p-3 rounded-xl bg-emerald-50/70 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/50 text-xs text-emerald-900 dark:text-emerald-300 flex items-start gap-2">
                <Info className="w-4 h-4 shrink-0 text-emerald-600 mt-0.5" />
                <span>
                  The NAP auditor scans page footers, contact pages, and Schema blocks to confirm these exact values match across the website.
                </span>
              </div>

              <div>
                <label
                  htmlFor="napName"
                  className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5"
                >
                  Business Legal Name
                </label>
                <input
                  id="napName"
                  type="text"
                  value={napName}
                  onChange={(e) => setNapName(e.target.value)}
                  placeholder="Acme Legal Services LLC"
                  className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="napAddress"
                    className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5"
                  >
                    Physical Address
                  </label>
                  <input
                    id="napAddress"
                    type="text"
                    value={napAddress}
                    onChange={(e) => setNapAddress(e.target.value)}
                    placeholder="123 Market St, Suite 400, Austin, TX"
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  />
                </div>

                <div>
                  <label
                    htmlFor="napPhone"
                    className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5"
                  >
                    Phone Number
                  </label>
                  <input
                    id="napPhone"
                    type="text"
                    value={napPhone}
                    onChange={(e) => setNapPhone(e.target.value)}
                    placeholder="+1 (555) 234-5678"
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Search Console property override */}
        <div className="bg-white dark:bg-slate-800/90 rounded-2xl border border-slate-200 dark:border-slate-700/80 p-6 shadow-sm">
          <label htmlFor="scProperty" className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5">
            Search Console property <span className="normal-case font-normal text-slate-400">(optional)</span>
          </label>
          <input
            id="scProperty"
            type="text"
            value={scProperty}
            onChange={(e) => setScProperty(e.target.value)}
            placeholder="sc-domain:example.com or https://www.example.com/"
            className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
          <p className="mt-1.5 text-xs text-slate-500">
            Leave blank to match automatically (domain property first, then the URL-prefix property for this origin). Set it when the
            site lives under a property with a different host. The Google service account is configured once in Settings.
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={() => navigate('/sites')}
            className="px-5 py-2.5 rounded-xl text-sm font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isSubmitting}
            className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold text-white bg-brand-600 hover:bg-brand-700 shadow-md shadow-brand-500/20 disabled:opacity-60 transition-all"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Saving Site...
              </>
            ) : (
              <>
                <Check className="w-4 h-4" />
                Save Site
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  )
}

export default SiteForm
