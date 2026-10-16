import { useState, type RefObject } from "react"
import { toast } from "sonner"

import { FormAlert } from "@/components/forms/form-alert"
import { PendingButton } from "@/components/forms/pending-button"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { useCancelHold } from "@/features/holds/hooks"
import { useDialogSession } from "@/hooks/use-dialog-session"
import { ApiError } from "@/lib/api"
import { formatPickupDate } from "@/lib/format"
import type { HoldOut } from "@/lib/types"

type CancelHoldDialogProps = {
  /** The hold to cancel, as it was when the dialog opened. */
  hold: HoldOut | null
  open: boolean
  onOpenChange: (open: boolean) => void
  /** The signed-in member cancels their own hold, through their own route. */
  mine?: boolean
  /** Where focus goes when the dialog closes. By default it goes back to the button that opened it. */
  returnFocusTo?: RefObject<HTMLElement | null>
}

/** Confirms cancelling a hold: the member leaves the line, and a copy set aside goes to the next. */
export function CancelHoldDialog({
  hold,
  open,
  onOpenChange,
  mine = false,
  returnFocusTo,
}: CancelHoldDialogProps) {
  const session = useDialogSession(open)
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      {hold && (
        <CancelHoldContent
          key={session}
          hold={hold}
          mine={mine}
          returnFocusTo={returnFocusTo}
          onClose={() => onOpenChange(false)}
        />
      )}
    </AlertDialog>
  )
}

type CancelHoldContentProps = Pick<CancelHoldDialogProps, "returnFocusTo"> & {
  hold: HoldOut
  mine: boolean
  onClose: () => void
}

/** What cancelling does to this hold, in the words of the person cancelling it. */
function consequence(hold: HoldOut, mine: boolean): string {
  const who = mine ? "you" : hold.member.full_name
  if (hold.status === "ready" && hold.copy && hold.pickup_by) {
    return `${hold.copy.code} of ${hold.book.title} is set aside for ${who} until ${formatPickupDate(hold.pickup_by)}. Cancelling gives the copy to the next member in line, or puts it back on the shelf.`
  }
  const place = hold.position ? `number ${hold.position} in line` : "in line"
  return mine
    ? `You are ${place} for ${hold.book.title}. Cancelling takes you out of the line.`
    : `${who} is ${place} for ${hold.book.title}. Cancelling takes them out of the line.`
}

function CancelHoldContent({ hold, mine, returnFocusTo, onClose }: CancelHoldContentProps) {
  const cancelHold = useCancelHold(hold.book.id, { mine })
  const [failure, setFailure] = useState<string | null>(null)

  async function confirm() {
    setFailure(null)
    try {
      const cancelled = await cancelHold.mutateAsync(hold.id)
      toast.success(
        mine
          ? `Cancelled your hold on ${cancelled.book.title}`
          : `Cancelled the hold of ${cancelled.member.full_name} on ${cancelled.book.title}`,
      )
      onClose()
    } catch (error) {
      if (error instanceof ApiError && error.code === "hold_closed") {
        setFailure("This hold is already closed. The page is now up to date.")
      } else {
        setFailure(error instanceof ApiError ? error.message : "Something went wrong. Try again.")
      }
    }
  }

  return (
    <AlertDialogContent
      onCloseAutoFocus={
        returnFocusTo
          ? (event) => {
              event.preventDefault()
              returnFocusTo.current?.focus()
            }
          : undefined
      }
    >
      <AlertDialogHeader>
        <AlertDialogTitle>{mine ? "Cancel your hold?" : "Cancel this hold?"}</AlertDialogTitle>
        <AlertDialogDescription>{consequence(hold, mine)}</AlertDialogDescription>
      </AlertDialogHeader>
      <FormAlert title="Could not cancel the hold" message={failure} />
      <AlertDialogFooter>
        <AlertDialogCancel>Keep hold</AlertDialogCancel>
        <PendingButton
          variant="destructive"
          pending={cancelHold.isPending}
          pendingLabel="Cancelling…"
          onClick={() => void confirm()}
        >
          Cancel hold
        </PendingButton>
      </AlertDialogFooter>
    </AlertDialogContent>
  )
}
