// Helpers for the five-field cron expressions stored on each site (minute hour day month dow),
// interpreted by the backend in APP_TIMEZONE. The picker in SiteForm produces the simple shapes
// below; anything else is shown and edited as a raw expression.

export type ScheduleKind = 'daily' | 'weekly' | 'weekdays' | 'monthly'

export interface SimpleSchedule {
  kind: ScheduleKind
  /** 0 = Sunday … 6 = Saturday (cron numbering). Only for kind === 'weekly'. */
  dow: number
  /** 1–28. Only for kind === 'monthly'. */
  dom: number
  hour: number
  minute: number
}

export const WEEKDAYS = [
  { value: 1, label: 'Monday', short: 'Mon' },
  { value: 2, label: 'Tuesday', short: 'Tue' },
  { value: 3, label: 'Wednesday', short: 'Wed' },
  { value: 4, label: 'Thursday', short: 'Thu' },
  { value: 5, label: 'Friday', short: 'Fri' },
  { value: 6, label: 'Saturday', short: 'Sat' },
  { value: 0, label: 'Sunday', short: 'Sun' },
]

const DOW_NAMES: Record<string, number> = {
  sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6,
}

export const DEFAULT_SCHEDULE: SimpleSchedule = { kind: 'daily', dow: 1, dom: 1, hour: 6, minute: 0 }

export function buildCron(s: SimpleSchedule): string {
  const m = s.minute
  const h = s.hour
  switch (s.kind) {
    case 'daily':
      return `${m} ${h} * * *`
    case 'weekly':
      return `${m} ${h} * * ${s.dow}`
    case 'weekdays':
      return `${m} ${h} * * 1-5`
    case 'monthly':
      return `${m} ${h} ${s.dom} * *`
  }
}

function parseDow(field: string): number | null {
  const f = field.toLowerCase()
  if (/^\d$/.test(f)) {
    const n = Number(f)
    return n === 7 ? 0 : n
  }
  if (f in DOW_NAMES) return DOW_NAMES[f]
  return null
}

/** Parse a cron expression into picker state, or null when it is not one of the simple shapes. */
export function parseCron(cron: string | null | undefined): SimpleSchedule | null {
  const parts = (cron || '').trim().split(/\s+/)
  if (parts.length !== 5) return null
  const [mStr, hStr, dom, month, dow] = parts
  if (!/^\d{1,2}$/.test(mStr) || !/^\d{1,2}$/.test(hStr)) return null
  const minute = Number(mStr)
  const hour = Number(hStr)
  if (minute > 59 || hour > 23 || month !== '*') return null
  if (dom === '*' && dow === '*') return { ...DEFAULT_SCHEDULE, kind: 'daily', hour, minute }
  if (dom === '*' && (dow === '1-5' || dow.toLowerCase() === 'mon-fri')) {
    return { ...DEFAULT_SCHEDULE, kind: 'weekdays', hour, minute }
  }
  if (dom === '*') {
    const d = parseDow(dow)
    if (d === null) return null
    return { ...DEFAULT_SCHEDULE, kind: 'weekly', dow: d, hour, minute }
  }
  if (dow === '*' && /^\d{1,2}$/.test(dom)) {
    const n = Number(dom)
    if (n < 1 || n > 28) return null
    return { ...DEFAULT_SCHEDULE, kind: 'monthly', dom: n, hour, minute }
  }
  return null
}

export function formatClock(hour: number, minute: number): string {
  const h12 = hour % 12 === 0 ? 12 : hour % 12
  const ampm = hour < 12 ? 'AM' : 'PM'
  return `${h12}:${String(minute).padStart(2, '0')} ${ampm}`
}

function ordinal(n: number): string {
  const s = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return n + (s[(v - 20) % 10] || s[v] || s[0])
}

/** "Every Monday at 6:00 AM", "Daily at 6:00 AM", …; falls back to the raw expression. */
export function describeCron(cron: string | null | undefined): string {
  const s = parseCron(cron)
  if (!s) return cron ? `Custom: ${cron}` : 'Not scheduled'
  const at = formatClock(s.hour, s.minute)
  switch (s.kind) {
    case 'daily':
      return `Daily at ${at}`
    case 'weekdays':
      return `Weekdays (Mon–Fri) at ${at}`
    case 'weekly': {
      const day = WEEKDAYS.find((w) => w.value === s.dow)?.label ?? 'day'
      return `Every ${day} at ${at}`
    }
    case 'monthly':
      return `Monthly on the ${ordinal(s.dom)} at ${at}`
  }
}
