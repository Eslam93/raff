import { useState } from "react"
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query"

import { activityKeys } from "@/features/activity/api"
import { bookKeys, fetchBook } from "@/features/books/api"
import { copyKeys, fetchCopyByCode } from "@/features/circulation/api"
import { dashboardKeys } from "@/features/dashboard/api"
import { holdKeys } from "@/features/holds/api"
import {
  borrowCopy,
  fetchLoans,
  fetchMyLoans,
  loanKeys,
  renewLoan,
  renewMyLoan,
  returnLoan,
} from "@/features/loans/api"
import { memberKeys } from "@/features/members/api"
import { ApiError } from "@/lib/api"
import { formatPickupDate } from "@/lib/format"
import type { HeldFor, LoanOut, LoansParams, MyLoansParams } from "@/lib/types"

/**
 * Everything that shows loans or counts them, apart from the book itself. The
 * holds are here too: a return can set a copy aside for the next in line, a
 * borrow fulfils the member's hold, and the holds decide whether a loan can
 * be renewed.
 */
function refreshLoanViews(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: bookKeys.lists() })
  void queryClient.invalidateQueries({ queryKey: loanKeys.all })
  void queryClient.invalidateQueries({ queryKey: copyKeys.all })
  void queryClient.invalidateQueries({ queryKey: holdKeys.all })
  void queryClient.invalidateQueries({ queryKey: dashboardKeys.all })
}

/**
 * A loan or a hold changes the book's copies, the catalog's availability, the
 * loans and holds lists, the member's page and counts, the dashboard and the
 * activity.
 */
export function refreshAfterLoanChange(queryClient: QueryClient, bookId: string) {
  void queryClient.invalidateQueries({ queryKey: bookKeys.detail(bookId) })
  void queryClient.invalidateQueries({ queryKey: memberKeys.all })
  void queryClient.invalidateQueries({ queryKey: activityKeys.all })
  refreshLoanViews(queryClient)
}

/** Conflicts that mean the page showed an old state of the book or the loan. */
const STALE_LOAN_CODES = new Set([
  "copy_unavailable",
  "copy_held",
  "book_archived",
  "loan_already_returned",
  "renewal_limit_reached",
  "book_has_holds",
  "loan_changed",
])

function refreshOnConflict(queryClient: QueryClient, bookId: string, error: Error) {
  if (error instanceof ApiError && STALE_LOAN_CODES.has(error.code)) {
    void queryClient.invalidateQueries({ queryKey: bookKeys.detail(bookId) })
    void queryClient.invalidateQueries({ queryKey: memberKeys.all })
    refreshLoanViews(queryClient)
  }
}

/** Borrows a copy of the book `bookId`. */
export function useBorrowCopy(bookId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: borrowCopy,
    onSuccess: (loan) => refreshAfterLoanChange(queryClient, loan.book.id),
    onError: (error) => refreshOnConflict(queryClient, bookId, error),
  })
}

/** A return, and who the copy is set aside for when the return gave it to the next member in line. */
export type ReturnResult = {
  loan: LoanOut
  heldFor: HeldFor | null
}

async function returnAndCheckHolds(loanId: string): Promise<ReturnResult> {
  const loan = await returnLoan(loanId)
  // The return answers with the loan only. The copy itself says whether a hold took it; when that
  // lookup fails, the return still succeeded and the copy shows as held on the next look.
  const copy = await fetchCopyByCode(loan.copy.code).catch(() => null)
  return { loan, heldFor: copy?.status === "held" ? copy.held_for : null }
}

/** The toast after a return: who returned the copy, and who it is set aside for when a hold took it. */
export function returnedMessage({ loan, heldFor }: ReturnResult): string {
  const returned = `Returned ${loan.book.title} (${loan.copy.code}) from ${loan.member.full_name}`
  if (!heldFor) return returned
  return `${returned}. It is set aside for ${heldFor.member.full_name} until ${formatPickupDate(heldFor.pickup_by)}.`
}

/** Returns a loan on a copy of the book `bookId`. */
export function useReturnLoan(bookId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: returnAndCheckHolds,
    onSuccess: ({ loan }) => refreshAfterLoanChange(queryClient, loan.book.id),
    onError: (error) => refreshOnConflict(queryClient, bookId, error),
  })
}

/**
 * Renews a loan on a copy of the book `bookId`. `mine` renews through the
 * member's own route, which acts only on their own loans.
 */
export function useRenewLoan(bookId: string, { mine = false } = {}) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: mine ? renewMyLoan : renewLoan,
    onSuccess: (loan) => refreshAfterLoanChange(queryClient, loan.book.id),
    onError: (error) => refreshOnConflict(queryClient, bookId, error),
  })
}

/** The signed-in member's loans, active or returned, one page at a time. */
export function useMyLoans(params: MyLoansParams) {
  return useQuery({
    queryKey: loanKeys.mine(params),
    queryFn: ({ signal }) => fetchMyLoans(params, signal),
    // Keep the current page on screen while the next one loads.
    placeholderData: keepPreviousData,
  })
}

/** All of a member's active loans in one request: the API's largest page. */
const MY_ACTIVE_LOANS: MyLoansParams = { status: "active", limit: 100 }

/**
 * The signed-in member's active loan of a book, or null. Only the first 100
 * active loans are read; a loan past them shows as none here, and the API
 * still refuses a hold on that book with already_borrowed.
 */
export function useMyActiveLoanOf(bookId: string, { enabled = true } = {}) {
  return useQuery({
    queryKey: loanKeys.mine(MY_ACTIVE_LOANS),
    queryFn: ({ signal }) => fetchMyLoans(MY_ACTIVE_LOANS, signal),
    select: (page) => page.items.find((loan) => loan.book.id === bookId) ?? null,
    enabled,
  })
}

/** Loans of every member, for staff, one page at a time. */
export function useLoans(params: LoansParams) {
  return useQuery({
    queryKey: loanKeys.list(params),
    queryFn: ({ signal }) => fetchLoans(params, signal),
    // Keep the current page on screen while the next search, tab or page loads.
    placeholderData: keepPreviousData,
  })
}

/** The book and copy the borrow dialog is for. Kept while the dialog closes, so its closing animation still shows them. */
export type BorrowTarget = {
  open: boolean
  bookId: string | null
  copyId: string | null
}

/**
 * Borrowing for a book known only by its id, such as one found by copy code
 * or by a search. `start` loads the book with its copies first, so the
 * dialog opens with the copy choice ready, and a failure to load shows where
 * staff asked for it.
 */
export function useBorrowByBookId() {
  const queryClient = useQueryClient()
  const [target, setTarget] = useState<BorrowTarget>({ open: false, bookId: null, copyId: null })
  const loadBook = useMutation({
    mutationFn: (bookId: string) =>
      // Always fresh: the dialog offers only the copies available now.
      queryClient.fetchQuery({
        queryKey: bookKeys.detail(bookId),
        queryFn: ({ signal }) => fetchBook(bookId, signal),
        staleTime: 0,
      }),
  })

  /** Loads the book, then opens the dialog and calls `onOpened`. `copyId` preselects a copy. */
  function start(bookId: string, copyId: string | null = null, onOpened?: () => void) {
    loadBook.mutate(bookId, {
      onSuccess: () => {
        setTarget({ open: true, bookId, copyId })
        onOpened?.()
      },
    })
  }

  function setOpen(open: boolean) {
    setTarget((current) => ({ ...current, open }))
  }

  return {
    target,
    start,
    setOpen,
    loading: loadBook.isPending,
    loadError: loadBook.error,
    clearLoadError: loadBook.reset,
  }
}
