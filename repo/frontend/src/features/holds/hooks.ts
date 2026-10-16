import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  cancelHold,
  cancelMyHold,
  fetchHolds,
  fetchMyHolds,
  holdKeys,
  placeHold,
  placeMyHold,
} from "@/features/holds/api"
import { refreshAfterLoanChange } from "@/features/loans/hooks"
import { ApiError } from "@/lib/api"
import type { HoldOut, HoldsParams, MyHoldsParams } from "@/lib/types"

/**
 * Refusals that mean the page showed an old state of the book or the hold:
 * a copy came back, the member borrowed it, or the hold closed meanwhile.
 */
const STALE_HOLD_CODES = new Set([
  "book_archived",
  "already_borrowed",
  "hold_exists",
  "copy_available",
  "hold_closed",
])

/** Every member's holds, for staff, one page at a time. */
export function useHolds(params: HoldsParams) {
  return useQuery({
    queryKey: holdKeys.list(params),
    queryFn: ({ signal }) => fetchHolds(params, signal),
    // Keep the current page on screen while the next one loads.
    placeholderData: keepPreviousData,
  })
}

/** The signed-in member's holds, one page at a time. */
export function useMyHolds(params: MyHoldsParams) {
  return useQuery({
    queryKey: holdKeys.mine(params),
    queryFn: ({ signal }) => fetchMyHolds(params, signal),
    placeholderData: keepPreviousData,
  })
}

/**
 * A write to a hold on the book `bookId`. A hold changes what a loan changes:
 * the book's copies and availability, whether its loans can be renewed, the
 * dashboard and the activity, so the same views refresh.
 */
function useHoldChange<T>(bookId: string, mutationFn: (input: T) => Promise<HoldOut>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: (hold) => refreshAfterLoanChange(queryClient, hold.book.id),
    onError: (error) => {
      if (error instanceof ApiError && STALE_HOLD_CODES.has(error.code)) {
        refreshAfterLoanChange(queryClient, bookId)
      }
    },
  })
}

/** Staff put a member in line for the book `bookId`. */
export function usePlaceHold(bookId: string) {
  return useHoldChange(bookId, (memberId: string) => placeHold({ book_id: bookId, member_id: memberId }))
}

/** The signed-in member puts themselves in line for the book `bookId`. */
export function usePlaceMyHold(bookId: string) {
  return useHoldChange<void>(bookId, () => placeMyHold({ book_id: bookId }))
}

/** Cancels a hold on the book `bookId`, through the member's own route when `mine`. */
export function useCancelHold(bookId: string, { mine = false } = {}) {
  return useHoldChange(bookId, mine ? cancelMyHold : cancelHold)
}
