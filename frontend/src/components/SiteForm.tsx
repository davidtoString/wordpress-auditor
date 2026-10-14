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
} from 'lucide-react'
import type { Site, SiteCreateInput } from '../lib/types'

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
  const [notificationEmail, setNotificationEmail] = useState(initialValues?.notification_email || '')
  const [isActive, setIsActive] = useState(initialValues?.is_active !== false)

  // Collapsible sections
  const [showWpCredentials, setShowWpCredentials] = useState(
    !!initialValues?.wp_username || !!initialValues?.wp_app_password
  )
  const [wpUsername, setWpUsername] = useState(initialValues?.wp_username || '')
  const [wpAppPassword, setWpAppPassword] = useState(initialValues?.wp_app_password || '')

  const [showNapConfig, setShowNapConfig] = useState(
    !!initialValues?.nap_name || !!initialValues?.nap_address || !!initialValues?.nap_phone
  )
  const [napName, setNapName] = useState(initialValues?.nap_name || '')
  const [napAddress, setNapAddress] = useState(initialValues?.nap_address || '')
  const [napPhone, setNapPhone] = useState(initialValues?.nap_phone || '')

  const cronPresets = [
    { label: 'Daily 6 AM', value: '0 6 * * *' },
    { label: 'Daily Midnight', value: '0 0 * * *' },
    { label: 'Weekly Monday', value: '0 6 * * 1' },
    { label: 'Hourly', value: '0 * * * *' },
  ]

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
      notification_email: notificationEmail.trim() || null,
      is_active: isActive,
      wp_username: wpUsername.trim() || null,
      wp_app_password: wpAppPassword.trim() || null,
      nap_name: napName.trim() || null,
      nap_address: napAddress.trim() || null,
      nap_phone: napPhone.trim() || null,
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

          {/* Cron Schedule */}
          <div>
            <label
              htmlFor="cronSchedule"
              className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5"
            >
              Cron Schedule Expression
            </label>
            <div className="flex flex-col sm:flex-row gap-3">
              <input
                id="cronSchedule"
                type="text"
                required
                value={cronSchedule}
                onChange={(e) => setCronSchedule(e.target.value)}
                placeholder="0 6 * * *"
                className="flex-1 px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
            {/* Presets */}
            <div className="flex flex-wrap gap-2 mt-2.5">
              <span className="text-xs text-slate-400 self-center mr-1">Presets:</span>
              {cronPresets.map((preset) => (
                <button
                  key={preset.value}
                  type="button"
                  onClick={() => setCronSchedule(preset.value)}
                  className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                    cronSchedule === preset.value
                      ? 'bg-brand-50 dark:bg-brand-950/60 border-brand-500 text-brand-600 dark:text-brand-400 font-semibold'
                      : 'border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400'
                  }`}
                >
                  {preset.label} ({preset.value})
                </button>
              ))}
            </div>
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
                  WordPress Application Passwords (Optional)
                </h3>
                <p className="text-xs text-slate-400">
                  Used by WP Health & deep core diagnostic checks via WP REST API.
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
                    className="block text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-1.5"
                  >
                    Application Password
                  </label>
                  <input
                    id="wpAppPassword"
                    type="password"
                    value={wpAppPassword}
                    onChange={(e) => setWpAppPassword(e.target.value)}
                    placeholder="xxxx xxxx xxxx xxxx"
                    className="w-full px-3.5 py-2.5 rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
                  />
                </div>
              </div>
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
