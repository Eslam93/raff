import type { ProposalOut, TableDisplay } from "@/features/copilot/types"
import type {
  ActivityOut,
  BookDetail,
  BookSummary,
  CopyLookupOut,
  CopyOut,
  DashboardOut,
  HoldOut,
  LoanOut,
  MemberDetailOut,
  MemberOut,
  Page,
  UserOut,
} from "@/lib/types"

export function staffUser(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: "user-staff",
    display_name: "Demo Staff",
    email: "staff@demo.local",
    role: "staff",
    member_id: null,
    is_demo: true,
    ...overrides,
  }
}

export function memberUser(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: "user-member",
    display_name: "Demo Member",
    email: "member@demo.local",
    role: "member",
    member_id: "member-1",
    is_demo: true,
    ...overrides,
  }
}

export function page<T>(items: T[], overrides: Partial<Page<T>> = {}): Page<T> {
  return { items, total: items.length, limit: 20, offset: 0, ...overrides }
}

export function bookSummary(overrides: Partial<BookSummary> = {}): BookSummary {
  return {
    id: "book-1",
    title: "Dune",
    author: "Frank Herbert",
    isbn: "9780441172719",
    category: "Science fiction",
    published_year: 1965,
    copies_total: 3,
    copies_available: 2,
    availability: "available",
    ...overrides,
  }
}

export function availableCopy(id: string, code: string): CopyOut {
  return { id, code, status: "available", due_at: null, active_loan: null, held_for: null }
}

export function borrowedCopy(id: string, code: string, overdue = false): CopyOut {
  return {
    id,
    code,
    status: "borrowed",
    due_at: "2026-09-15T23:59:59Z",
    active_loan: {
      id: `loan-${id}`,
      member: { id: "member-9", full_name: "Lina Farah" },
      borrowed_at: "2026-09-01T10:00:00Z",
      due_at: "2026-09-15T23:59:59Z",
      is_overdue: overdue,
    },
    held_for: null,
  }
}

/** A borrowed copy as a member sees it: the due time, never the loan. */
export function copyOnLoan(id: string, code: string, dueAt: string): CopyOut {
  return { id, code, status: "borrowed", due_at: dueAt, active_loan: null, held_for: null }
}

/** A copy set aside for a member's ready hold, as staff see it: who it waits for, and until when. */
export function heldCopy(id: string, code: string, memberName = "Maya Hassan"): CopyOut {
  return {
    id,
    code,
    status: "held",
    due_at: null,
    active_loan: null,
    held_for: {
      member: { id: "member-1", full_name: memberName },
      pickup_by: "2026-10-19T23:59:59Z",
    },
  }
}

export function bookDetail(overrides: Partial<BookDetail> = {}): BookDetail {
  const copies = overrides.copies ?? [
    borrowedCopy("copy-1", "CP-0001"),
    availableCopy("copy-2", "CP-0002"),
    availableCopy("copy-3", "CP-0003"),
  ]
  const available = copies.filter((copy) => copy.status === "available").length
  return {
    ...bookSummary(),
    copies_total: copies.length,
    copies_available: available,
    availability: copies.length === 0 ? "no_copies" : available === 0 ? "all_borrowed" : "available",
    description: "A desert planet and the spice it guards.",
    has_loan_history: true,
    archived: false,
    created_at: "2026-09-01T09:00:00Z",
    updated_at: "2026-09-01T09:00:00Z",
    copies,
    holds_waiting: 0,
    my_hold: null,
    ...overrides,
  }
}

export function member(overrides: Partial<MemberOut> = {}): MemberOut {
  return {
    id: "member-1",
    full_name: "Maya Hassan",
    email: "maya@example.com",
    joined_on: "2026-01-15",
    active_loans: 0,
    ...overrides,
  }
}

export function loan(overrides: Partial<LoanOut> = {}): LoanOut {
  return {
    id: "loan-1",
    copy: { id: "copy-1", code: "CP-0001" },
    book: { id: "book-1", title: "Dune", author: "Frank Herbert" },
    member: { id: "member-1", full_name: "Demo Member" },
    borrowed_at: "2026-09-01T10:00:00Z",
    due_at: "2026-09-15T23:59:59Z",
    returned_at: null,
    is_overdue: false,
    days_overdue: 0,
    renewals: 0,
    can_renew: true,
    ...overrides,
  }
}

/** A member waiting in line for Dune: number 1 unless the overrides say otherwise. */
export function hold(overrides: Partial<HoldOut> = {}): HoldOut {
  return {
    id: "hold-1",
    status: "waiting",
    book: { id: "book-1", title: "Dune", author: "Frank Herbert" },
    member: { id: "member-1", full_name: "Maya Hassan" },
    copy: null,
    placed_at: "2026-10-10T09:00:00Z",
    ready_at: null,
    pickup_by: null,
    closed_at: null,
    position: 1,
    ...overrides,
  }
}

/** A hold whose copy is set aside: Maya Hassan picks up CP-0012 by 19 Oct 2026. */
export function readyHold(overrides: Partial<HoldOut> = {}): HoldOut {
  return hold({
    status: "ready",
    copy: { id: "copy-12", code: "CP-0012" },
    ready_at: "2026-10-16T10:00:00Z",
    pickup_by: "2026-10-19T23:59:59Z",
    position: null,
    ...overrides,
  })
}

export function memberDetail(overrides: Partial<MemberDetailOut> = {}): MemberDetailOut {
  return { ...member(), loans_total: 0, ...overrides }
}

export function activityEvent(overrides: Partial<ActivityOut> = {}): ActivityOut {
  return {
    id: 1,
    occurred_at: "2026-09-19T09:30:00Z",
    action: "loan.borrowed",
    entity_type: "loan",
    entity_id: "loan-1",
    summary: "Borrowed Dune (CP-0001) to Maya Hassan",
    via: "ui",
    actor: "Demo Staff",
    ...overrides,
  }
}

export function dashboard(overrides: Partial<DashboardOut> = {}): DashboardOut {
  return {
    counts: {
      titles: 0,
      copies: 0,
      available: 0,
      on_loan: 0,
      overdue: 0,
      members: 0,
      active_members_90d: 0,
    },
    overdue: [],
    due_soon: [],
    recent_activity: [],
    ...overrides,
  }
}

/** A copy found by code: on loan when an active_loan is given, otherwise on the shelf. */
export function copyLookup(overrides: Partial<CopyLookupOut> = {}): CopyLookupOut {
  const activeLoan = overrides.active_loan ?? null
  return {
    copy: activeLoan?.copy ?? { id: "copy-1", code: "CP-0001" },
    book: activeLoan?.book ?? { id: "book-1", title: "Dune", author: "Frank Herbert" },
    status: activeLoan ? "borrowed" : "available",
    archived: false,
    active_loan: activeLoan,
    held_for: null,
    ...overrides,
  }
}

/** A Borrow the Copilot prepared: waiting for confirmation, made at 12:00 UTC and open for ten minutes. */
export function proposal(overrides: Partial<ProposalOut> = {}): ProposalOut {
  return {
    id: "proposal-1",
    action: "borrow",
    status: "pending",
    book: { id: "book-7", title: "The Hobbit", author: "J. R. R. Tolkien" },
    copy: { id: "copy-17", code: "CP-0217" },
    member: { id: "member-1", full_name: "Maya Hassan" },
    due_at: "2026-10-03T23:59:59Z",
    borrowed_at: null,
    is_overdue: false,
    created_at: "2026-09-19T12:00:00Z",
    expires_at: "2026-09-19T12:10:00Z",
    resolved_at: null,
    loan: null,
    error: null,
    ...overrides,
  }
}

/**
 * Loans by category this quarter against the previous quarter, as the analyst
 * sends it: raw numbers the panel formats, a total the server measured, and
 * horizontal bars for the current and previous values.
 */
export function tableDisplay(overrides: Partial<TableDisplay> = {}): TableDisplay {
  return {
    kind: "table",
    title: "Loans by category",
    subtitle: "1 Jul 2026 to 19 Sep 2026 (so far), against 1 Apr 2026 to 19 Jun 2026",
    columns: [
      { key: "label", label: "Category", format: "text" },
      { key: "value", label: "Loans", format: "count" },
      { key: "share_pct", label: "Share", format: "percent" },
      { key: "previous_value", label: "Previous", format: "count" },
      { key: "previous_share_pct", label: "Previous share", format: "percent" },
      { key: "change", label: "Change", format: "count" },
      { key: "change_pct", label: "Change %", format: "change_percent" },
    ],
    rows: [
      {
        label: "Technology",
        value: 1234,
        share_pct: 37.1,
        previous_value: 1097,
        previous_share_pct: 28.9,
        change: 137,
        change_pct: 12.5,
      },
      {
        label: "Fiction",
        value: 980,
        share_pct: 29.5,
        previous_value: 1010,
        previous_share_pct: 26.6,
        change: -30,
        change_pct: -3,
      },
      { label: "Poetry", value: 12, share_pct: 0.4, previous_value: 0, previous_share_pct: 0, change: 12, change_pct: null },
    ],
    total: { value: 3325, previous_value: 3800, change: -475, change_pct: -12.5 },
    chart: {
      type: "bar",
      x: "label",
      series: [
        { key: "value", label: "This quarter" },
        { key: "previous_value", label: "Previous quarter" },
      ],
    },
    ...overrides,
  }
}
