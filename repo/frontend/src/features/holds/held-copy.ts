import type { BookRef, CopyRef, HoldOut, MemberRef } from "@/lib/types"

/** A copy set aside for a member's ready hold: from a hold, a book's copies, or the desk. */
export type HeldCopy = {
  book: Pick<BookRef, "id" | "title">
  copy: CopyRef
  member: MemberRef
  pickup_by: string | null
}

/** The copy behind a ready hold, in the shape the lend dialog takes. Null for any other hold. */
export function heldCopyOf(hold: HoldOut): HeldCopy | null {
  if (hold.status !== "ready" || !hold.copy) return null
  return { book: hold.book, copy: hold.copy, member: hold.member, pickup_by: hold.pickup_by }
}
