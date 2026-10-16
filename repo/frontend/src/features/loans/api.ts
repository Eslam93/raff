import { apiRequest } from "@/lib/api"
import { withSearchParams } from "@/lib/search-params"
import type { LoanCreate, LoanOut, LoansParams, MyLoansParams, Page } from "@/lib/types"

export const loanKeys = {
  all: ["loans"] as const,
  mine: (params: MyLoansParams) => [...loanKeys.all, "mine", params] as const,
  lists: () => [...loanKeys.all, "list"] as const,
  list: (params: LoansParams) => [...loanKeys.lists(), params] as const,
}

export function borrowCopy(body: LoanCreate) {
  return apiRequest<LoanOut>("/api/loans", { method: "POST", body })
}

export function returnLoan(loanId: string) {
  return apiRequest<LoanOut>(`/api/loans/${encodeURIComponent(loanId)}/return`, {
    method: "POST",
  })
}

/** Moves an active loan's due date by the loan period. Staff renew any member's loan. */
export function renewLoan(loanId: string) {
  return apiRequest<LoanOut>(`/api/loans/${encodeURIComponent(loanId)}/renew`, { method: "POST" })
}

/** Renews one of the signed-in member's own active loans. Another member's loan is 404. */
export function renewMyLoan(loanId: string) {
  return apiRequest<LoanOut>(`/api/me/loans/${encodeURIComponent(loanId)}/renew`, {
    method: "POST",
  })
}

/** The signed-in member's own loans. The API answers 404 no_member_profile for a user without one. */
export function fetchMyLoans(params: MyLoansParams, signal?: AbortSignal) {
  return apiRequest<Page<LoanOut>>(withSearchParams("/api/me/loans", params), { signal })
}

/** Every member's loans, for staff: filtered by status, a search, a member or a book. */
export function fetchLoans(params: LoansParams, signal?: AbortSignal) {
  return apiRequest<Page<LoanOut>>(withSearchParams("/api/loans", params), { signal })
}
