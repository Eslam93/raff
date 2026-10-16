import { describe, expect, it } from "vitest"

import { renewalCount, renewBlockedReason, renewedDueAt } from "@/features/loans/renewal"

const TODAY = Date.parse("2026-10-16T12:00:00Z")

describe("renewedDueAt", () => {
  it("adds the loan period to a due date still ahead", () => {
    expect(renewedDueAt("2026-10-20T23:59:59Z", TODAY)).toBe("2026-11-03T23:59:59Z")
  })

  it("counts from today for an overdue loan", () => {
    expect(renewedDueAt("2026-10-10T23:59:59Z", TODAY)).toBe("2026-10-30T23:59:59Z")
  })

  it("counts from today for a loan due today", () => {
    expect(renewedDueAt("2026-10-16T23:59:59Z", TODAY)).toBe("2026-10-30T23:59:59Z")
  })

  it("never goes past 90 days from today", () => {
    // Due 2027-01-10; plus 14 days would be 2027-01-24, past 2027-01-14.
    expect(renewedDueAt("2027-01-10T23:59:59Z", TODAY)).toBe("2027-01-14T23:59:59Z")
  })

  it("reads today as the UTC day, as the API does", () => {
    // 23:30 UTC on 16 Oct is already 17 Oct east of UTC, but the API's day is still the 16th.
    expect(renewedDueAt("2026-10-10T23:59:59Z", Date.parse("2026-10-16T23:30:00Z"))).toBe(
      "2026-10-30T23:59:59Z",
    )
  })
})

describe("renewalCount", () => {
  it("says nothing for a loan never renewed", () => {
    expect(renewalCount({ renewals: 0 })).toBeNull()
  })

  it("counts renewals against the limit", () => {
    expect(renewalCount({ renewals: 1 })).toBe("Renewed 1 of 2 times")
    expect(renewalCount({ renewals: 2 })).toBe("Renewed 2 of 2 times")
  })

  it("never shows more renewals than the limit it names", () => {
    // A library that allows more renewals than the default.
    expect(renewalCount({ renewals: 3 })).toBe("Renewed 3 of 3 times")
  })
})

describe("renewBlockedReason", () => {
  it("has no reason for a loan that can be renewed, or one already returned", () => {
    expect(renewBlockedReason({ renewals: 0, can_renew: true, returned_at: null })).toBeNull()
    expect(
      renewBlockedReason({ renewals: 0, can_renew: false, returned_at: "2026-10-01T10:00:00Z" }),
    ).toBeNull()
  })

  it("names the limit once every renewal is used", () => {
    expect(renewBlockedReason({ renewals: 2, can_renew: false, returned_at: null })).toBe(
      "No renewals left",
    )
  })

  it("names the waiting member otherwise", () => {
    expect(renewBlockedReason({ renewals: 1, can_renew: false, returned_at: null })).toBe(
      "Cannot renew: a member is waiting for this book",
    )
  })
})
