import { useState } from "react"
import { BookmarkPlus } from "lucide-react"
import { toast } from "sonner"

import { FormAlert } from "@/components/forms/form-alert"
import { PendingButton } from "@/components/forms/pending-button"
import { Button } from "@/components/ui/button"
import { CancelHoldDialog } from "@/features/holds/cancel-hold-dialog"
import { usePlaceMyHold } from "@/features/holds/hooks"
import { useMyActiveLoanOf } from "@/features/loans/hooks"
import { ApiError } from "@/lib/api"
import { formatDueDate, formatPickupDate } from "@/lib/format"
import type { BookDetail, HoldOut } from "@/lib/types"

/**
 * A member's hold on the book's page: a copy waiting for them, their place in
 * line, or Place hold when no copy is on the shelf and they do not have the
 * book already. Nothing while a copy is on the shelf: they borrow it at the desk.
 */
export function MemberHoldPanel({ book }: { book: BookDetail }) {
  const hold = book.my_hold
  // The dialog keeps its hold while closing: after a cancel, the page no longer has one.
  const [cancelling, setCancelling] = useState<{ open: boolean; hold: HoldOut | null }>({
    open: false,
    hold: null,
  })

  return (
    <>
      {hold ? (
        <div className="space-y-3 border-t pt-3">
          {hold.status === "ready" && hold.pickup_by ? (
            <div className="space-y-1">
              <p className="font-medium">
                A copy is waiting for you: pick it up by {formatPickupDate(hold.pickup_by)}.
              </p>
              {hold.copy && (
                <p className="text-muted-foreground">
                  Ask at the desk for copy <span className="font-mono">{hold.copy.code}</span>.
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-1">
              <p className="font-medium">
                {hold.position ? `You are number ${hold.position} in line.` : "You are in line."}
              </p>
              <p className="text-muted-foreground">
                When a copy comes back, it is set aside for the first member in line.
              </p>
            </div>
          )}
          <Button variant="outline" size="sm" onClick={() => setCancelling({ open: true, hold })}>
            Cancel hold
          </Button>
        </div>
      ) : (
        <PlaceHoldOffer book={book} />
      )}
      <CancelHoldDialog
        hold={cancelling.hold}
        open={cancelling.open}
        onOpenChange={(open) => setCancelling((current) => ({ ...current, open }))}
        mine
      />
    </>
  )
}

/** Place hold, for a book with no copy on the shelf that the member does not have on loan. */
function PlaceHoldOffer({ book }: { book: BookDetail }) {
  const canPlace = !book.archived && book.copies_available === 0
  const activeLoan = useMyActiveLoanOf(book.id, { enabled: canPlace })
  const placeHold = usePlaceMyHold(book.id)
  const [failure, setFailure] = useState<string | null>(null)

  // Placed: the book's page reloads with the hold. Until it does, say where the member stands.
  if (placeHold.data) {
    return (
      <p className="border-t pt-3 font-medium">
        You are number {placeHold.data.position ?? 1} in line.
      </p>
    )
  }
  if (!canPlace) return null
  // Wait for the loans, so the button does not show and then vanish. If they fail to load, offer
  // the hold: the API refuses it for a member who has the book.
  if (activeLoan.isPending) return null
  if (activeLoan.data) {
    return (
      <p className="border-t pt-3 text-muted-foreground">
        You have this book on loan, due back {formatDueDate(activeLoan.data.due_at)}.
      </p>
    )
  }

  async function place() {
    setFailure(null)
    try {
      const hold = await placeHold.mutateAsync()
      toast.success(`You are number ${hold.position ?? 1} in line for ${hold.book.title}`)
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : "Something went wrong. Try again.")
    }
  }

  return (
    <div className="space-y-3 border-t pt-3">
      <p className="text-muted-foreground">
        {book.copies_total === 0
          ? "The library has no copies of this book yet. Place a hold to get the first one."
          : "No copy is on the shelf now. Place a hold to get the next copy that comes back."}
      </p>
      <FormAlert title="Could not place the hold" message={failure} />
      <PendingButton
        size="sm"
        pending={placeHold.isPending}
        pendingLabel="Placing…"
        onClick={() => void place()}
      >
        <BookmarkPlus aria-hidden />
        Place hold
      </PendingButton>
    </div>
  )
}
