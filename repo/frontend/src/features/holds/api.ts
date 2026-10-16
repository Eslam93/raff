import { apiRequest } from "@/lib/api"
import { withSearchParams } from "@/lib/search-params"
import type {
  HoldCreate,
  HoldOut,
  HoldsParams,
  MyHoldCreate,
  MyHoldsParams,
  Page,
} from "@/lib/types"

export const holdKeys = {
  all: ["holds"] as const,
  lists: () => [...holdKeys.all, "list"] as const,
  list: (params: HoldsParams) => [...holdKeys.lists(), params] as const,
  mine: (params: MyHoldsParams) => [...holdKeys.all, "mine", params] as const,
}

/** Every member's holds, for staff: filtered by status, a book or a member. */
export function fetchHolds(params: HoldsParams, signal?: AbortSignal) {
  return apiRequest<Page<HoldOut>>(withSearchParams("/api/holds", params), { signal })
}

/** The signed-in member's own holds. The API answers 404 no_member_profile for a user without one. */
export function fetchMyHolds(params: MyHoldsParams, signal?: AbortSignal) {
  return apiRequest<Page<HoldOut>>(withSearchParams("/api/me/holds", params), { signal })
}

/** Staff put a member in line for a book that has no copy on the shelf. */
export function placeHold(body: HoldCreate) {
  return apiRequest<HoldOut>("/api/holds", { method: "POST", body })
}

/** The signed-in member puts themselves in line for a book. */
export function placeMyHold(body: MyHoldCreate) {
  return apiRequest<HoldOut>("/api/me/holds", { method: "POST", body })
}

export function cancelHold(holdId: string) {
  return apiRequest<HoldOut>(`/api/holds/${encodeURIComponent(holdId)}/cancel`, { method: "POST" })
}

/** Cancels one of the signed-in member's own holds. Another member's hold is 404. */
export function cancelMyHold(holdId: string) {
  return apiRequest<HoldOut>(`/api/me/holds/${encodeURIComponent(holdId)}/cancel`, {
    method: "POST",
  })
}
