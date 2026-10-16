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
import { useRenewLoan } from "@/features/loans/hooks"
import { MAX_RENEWALS, renewedDueAt } from "@/features/loans/renewal"
import { useDialogSession } from "@/hooks/use-dialog-session"
import { ApiError } from "@/lib/api"
import { formatDueDate } from "@/lib/format"
import type { LoanOut } from "@/lib/types"

type RenewDialogProps = {
  /** The loan to renew, as it was when the dialog opened. */
  loan: LoanOut | null
  open: boolean
  onOpenChange: (open: boolean) => void
  /** The signed-in member renews their own loan, through their own route. */
  mine?: boolean
  /** Where focus goes when the dialog closes. By default it goes back to the button that opened it. */
  returnFocusTo?: RefObject<HTMLElement | null>
}

/** Confirms a renewal: the loan stays out with a later due date. */
export function RenewDialog({ loan, open, onOpenChange, mine = false, returnFocusTo }: RenewDialogProps) {
  const session = useDialogSession(open)
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      {loan && (
        <RenewContent
          key={session}
          loan={loan}
          mine={mine}
          returnFocusTo={returnFocusTo}
          onClose={() => onOpenChange(false)}
        />
      )}
    </AlertDialog>
  )
}

type RenewContentProps = Pick<RenewDialogProps, "mine" | "returnFocusTo"> & {
  loan: LoanOut
  onClose: () => void
}

function RenewContent({ loan, mine, returnFocusTo, onClose }: RenewContentProps) {
  const renewLoan = useRenewLoan(loan.book.id, { mine })
  const [failure, setFailure] = useState<string | null>(null)
  // The new date is worked out once, when the dialog opens.
  const [newDueAt] = useState(() => renewedDueAt(loan.due_at, Date.now()))
  const renewal = `This is renewal ${loan.renewals + 1} of ${Math.max(loan.renewals + 1, MAX_RENEWALS)}.`

  async function confirm() {
    setFailure(null)
    try {
      const renewed = await renewLoan.mutateAsync(loan.id)
      const due = formatDueDate(renewed.due_at)
      toast.success(
        mine
          ? `Renewed ${renewed.book.title}, now due ${due}`
          : `Renewed ${renewed.book.title} (${renewed.copy.code}) for ${renewed.member.full_name}, now due ${due}`,
      )
      onClose()
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : "Something went wrong. Try again.")
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
        <AlertDialogTitle>Renew this loan?</AlertDialogTitle>
        <AlertDialogDescription>
          {mine
            ? `${loan.book.title} (${loan.copy.code}) is due ${formatDueDate(loan.due_at)}`
            : `${loan.book.title} (${loan.copy.code}), borrowed by ${loan.member.full_name}, is due ${formatDueDate(loan.due_at)}`}
          {loan.is_overdue ? " (overdue)" : ""}. Renewing moves the due date to{" "}
          {formatDueDate(newDueAt)}. {renewal}
        </AlertDialogDescription>
      </AlertDialogHeader>
      <FormAlert title="Could not renew the loan" message={failure} />
      <AlertDialogFooter>
        <AlertDialogCancel>Cancel</AlertDialogCancel>
        <PendingButton
          pending={renewLoan.isPending}
          pendingLabel="Renewing…"
          onClick={() => void confirm()}
        >
          Renew
        </PendingButton>
      </AlertDialogFooter>
    </AlertDialogContent>
  )
}
