import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { format, formatDistanceToNow, isValid, parseISO } from 'date-fns'
import {
  Gauge,
  Search,
  ShieldCheck,
  Link2Off,
  FileCode,
  Cookie,
  MapPin,
  Image,
  HeartPulse,
  ArrowRightLeft,
  Eye,
  Activity,
  Layers,
  CheckCircle,
  AlertTriangle,
  XCircle,
  Compass,
  HelpCircle,
  type LucideIcon,
} from 'lucide-react'

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

export function parseDateSafe(date: string | number | Date | null | undefined): Date | null {
  if (!date) return null
  if (date instanceof Date) return isValid(date) ? date : null
  try {
    const parsed = typeof date === 'string' ? parseISO(date) : new Date(date)
    return isValid(parsed) ? parsed : null
  } catch {
    return null
  }
}

export function formatDate(date: string | number | Date | null | undefined): string {
  const parsed = parseDateSafe(date)
  if (!parsed) return 'Never'
  return format(parsed, 'MMM d, yyyy h:mm a')
}

export function formatRelative(date: string | number | Date | null | undefined): string {
  const parsed = parseDateSafe(date)
  if (!parsed) return 'Never'
  return formatDistanceToNow(parsed, { addSuffix: true })
}

export function scoreToColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return 'text-slate-400 dark:text-slate-500'
  if (score >= 80) return 'text-emerald-600 dark:text-emerald-400'
  if (score >= 60) return 'text-amber-600 dark:text-amber-400'
  if (score >= 40) return 'text-orange-600 dark:text-orange-400'
  return 'text-rose-600 dark:text-rose-400'
}

export function scoreToBgColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return 'bg-slate-100 dark:bg-slate-800'
  if (score >= 80) return 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
  if (score >= 60) return 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800/60'
  if (score >= 40) return 'bg-orange-50 dark:bg-orange-950/40 text-orange-700 dark:text-orange-300 border-orange-200 dark:border-orange-800/60'
  return 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/60'
}

export function scoreToProgressColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return 'bg-slate-300 dark:bg-slate-700'
  if (score >= 80) return 'bg-emerald-500'
  if (score >= 60) return 'bg-amber-500'
  if (score >= 40) return 'bg-orange-500'
  return 'bg-rose-500'
}

export type ScoreLabel = 'Excellent' | 'Good' | 'Needs Work' | 'Critical' | 'Not Run'

export function scoreToLabel(score: number | null | undefined): ScoreLabel {
  if (score === null || score === undefined) return 'Not Run'
  if (score >= 90) return 'Excellent'
  if (score >= 70) return 'Good'
  if (score >= 50) return 'Needs Work'
  return 'Critical'
}

export function statusToIcon(status: string | null | undefined): LucideIcon {
  if (!status) return HelpCircle
  const s = status.toLowerCase()
  if (s === 'pass' || s === 'completed' || s === 'healthy' || s === 'ok') return CheckCircle
  if (s === 'warn' || s === 'warning' || s === 'pending') return AlertTriangle
  if (s === 'fail' || s === 'failed' || s === 'error' || s === 'critical') return XCircle
  return HelpCircle
}

export function statusToColor(status: string | null | undefined): string {
  if (!status) return 'text-slate-500'
  const s = status.toLowerCase()
  if (s === 'pass' || s === 'completed' || s === 'healthy' || s === 'ok') return 'text-emerald-500'
  if (s === 'warn' || s === 'warning' || s === 'pending') return 'text-amber-500'
  if (s === 'fail' || s === 'failed' || s === 'error' || s === 'critical') return 'text-rose-500'
  return 'text-slate-400'
}

export function moduleDisplayName(module: string): string {
  const map: Record<string, string> = {
    unlighthouse: 'Unlighthouse (Site-Wide)',
    advertools: 'Technical SEO (Advertools)',
    pagespeed: 'PageSpeed',
    seo: 'SEO',
    security: 'Security',
    broken_links: 'Broken Links',
    links: 'Broken Links',
    schema: 'Schema & Structured Data',
    cookie_consent: 'Cookie Consent',
    cookies: 'Cookie Consent',
    nap: 'NAP Consistency',
    images: 'Image Optimization',
    wp_health: 'WordPress Health',
    health: 'WordPress Health',
    redirects: 'Redirects & Headers',
    accessibility: 'Accessibility (A11y)',
    a11y: 'Accessibility (A11y)',
    uptime: 'Uptime & Response',
  }
  return map[module.toLowerCase()] || module.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function moduleIcon(module: string): LucideIcon {
  const map: Record<string, LucideIcon> = {
    unlighthouse: Layers,
    advertools: Compass,
    pagespeed: Gauge,
    seo: Search,
    security: ShieldCheck,
    broken_links: Link2Off,
    links: Link2Off,
    schema: FileCode,
    cookie_consent: Cookie,
    cookies: Cookie,
    nap: MapPin,
    images: Image,
    wp_health: HeartPulse,
    health: HeartPulse,
    redirects: ArrowRightLeft,
    accessibility: Eye,
    a11y: Eye,
    uptime: Activity,
  }
  return map[module.toLowerCase()] || Activity
}
