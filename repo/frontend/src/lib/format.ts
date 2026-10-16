/** Display formatting. Everything goes through Intl so it follows the reader's locale. */

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" })
const utcDateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" })
const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
})
const relativeFormat = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" })
const countFormat = new Intl.NumberFormat()

/** A timestamp as a date in the reader's time zone. */
export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso))
}

/** A timestamp as a date and time in the reader's time zone. */
export function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso))
}

/**
 * A loan's due date. The API sets `due_at` to the end of the due day in UTC,
 * so the date is read in UTC; in the reader's zone it could fall on the next day.
 */
export function formatDueDate(iso: string): string {
  return utcDateFormat.format(new Date(iso))
}

/**
 * The last day to pick up a copy set aside for a hold. Like a due date, the
 * API sets it to the end of that day in UTC, so the date is read in UTC.
 */
export function formatPickupDate(iso: string): string {
  return utcDateFormat.format(new Date(iso))
}

/** A calendar date (YYYY-MM-DD), shown without a time zone shift. */
export function formatCalendarDate(value: string): string {
  return utcDateFormat.format(new Date(`${value}T00:00:00Z`))
}

const RELATIVE_STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["second", 60],
  ["minute", 60],
  ["hour", 24],
  ["day", 30],
  ["month", 12],
  ["year", Number.POSITIVE_INFINITY],
]

/** "5 minutes ago", "yesterday", and so on, measured from `now`. */
export function formatRelative(iso: string, now: number): string {
  let amount = (new Date(iso).getTime() - now) / 1000
  for (const [unit, size] of RELATIVE_STEPS) {
    if (Math.abs(amount) < size) return relativeFormat.format(Math.round(amount), unit)
    amount /= size
  }
  return formatDateTime(iso)
}

/** "Due today", "Due tomorrow", "Due in 5 days", from daysUntilDue. */
export function formatDueIn(days: number): string {
  if (days <= 0) return "Due today"
  if (days === 1) return "Due tomorrow"
  return `Due in ${days} days`
}

/** "3 days overdue". A loan past its due time by less than a day is just "Overdue". */
export function formatOverdue(daysOverdue: number): string {
  if (daysOverdue <= 0) return "Overdue"
  return `${plural(daysOverdue, "day", "days")} overdue`
}

/** A count with the reader's digit grouping: "1,234". */
export function formatCount(count: number): string {
  return countFormat.format(count)
}

/** "1 copy", "3 copies". */
export function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}
