import { LOAN_PERIOD_DAYS, MAX_LOAN_DAYS } from "@/features/loans/borrow-schema"
import type { LoanOut } from "@/lib/types"

/**
 * The API's default for how many times one loan can be renewed. The API does
 * not send its settings, so the app uses the default, as the borrow dialog
 * does with the loan period. Whether a loan can be renewed always comes from
 * the API (`can_renew`); this number only words it.
 */
export const MAX_RENEWALS = 2

const DAY_MS = 86_400_000

type RenewalFacts = Pick<LoanOut, "renewals" | "can_renew" | "returned_at">

/** "Renewed 1 of 2 times", or null for a loan never renewed. */
export function renewalCount({ renewals }: Pick<LoanOut, "renewals">): string | null {
  if (renewals <= 0) return null
  return `Renewed ${renewals} of ${Math.max(renewals, MAX_RENEWALS)} times`
}

/**
 * Why an active loan cannot be renewed now, or null when it can (or is
 * returned). The API refuses a renewal past the limit, and while a member is
 * waiting for the book.
 */
export function renewBlockedReason(loan: RenewalFacts): string | null {
  if (loan.returned_at || loan.can_renew) return null
  if (loan.renewals >= MAX_RENEWALS) return "No renewals left"
  return "Cannot renew: a member is waiting for this book"
}

function utcDay(time: number): number {
  const date = new Date(time)
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate())
}

/**
 * The due time a renewal gives, worked out as the API does: the later of
 * today and the current due date, plus the loan period, at most 90 days from
 * today, at the end of that day. Days are UTC days, like due dates.
 */
export function renewedDueAt(dueAt: string, now: number): string {
  const today = utcDay(now)
  const start = Math.max(today, utcDay(Date.parse(dueAt)))
  const due = Math.min(start + LOAN_PERIOD_DAYS * DAY_MS, today + MAX_LOAN_DAYS * DAY_MS)
  return `${new Date(due).toISOString().slice(0, 10)}T23:59:59Z`
}
