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
import { returnedMessage, useReturnLoan } from "@/features/loans/hooks"
import type { ReturnableLoan } from "@/features/loans/returnable-loan"
import { useDialogSession } from "@/hooks/use-dialog-session"
import { ApiError } from "@/lib/api"
import { formatDate, formatDueDate } from "@/lib/format"
import type { LoanOut } from "@/lib/types"

type ReturnDialogProps = {
  /** The loan to return, as it was when the dialog opened. */
  loan: ReturnableLoan | null
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called after the return succeeded, before the dialog closes. */
  onReturned?: (loan: LoanOut) => void
  /** Where focus goes when the dialog closes. By default it goes back to the button that opened it. */
  returnFocusTo?: RefObject<HTMLElement | null>
}

/**
 * Confirms a return: the loan closes and the copy is available again, or set
 * aside for the first member waiting for the book.
 */
export function ReturnDialog({ loan, open, onOpenChange, onReturned, returnFocusTo }: ReturnDialogProps) {
  const session = useDialogSession(open)
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      {loan && (
        <ReturnContent
          key={session}
          loan={loan}
          onReturned={onReturned}
          returnFocusTo={returnFocusTo}
          onClose={() => onOpenChange(false)}
        />
      )}
    </AlertDialog>
  )
}

type ReturnContentProps = Pick<ReturnDialogProps, "onReturned" | "returnFocusTo"> & {
  loan: ReturnableLoan
  onClose: () => void
}

function ReturnContent({ loan, onReturned, returnFocusTo, onClose }: ReturnContentProps) {
  const returnLoan = useReturnLoan(loan.book.id)
  const [failure, setFailure] = useState<string | null>(null)

  async function confirm() {
    setFailure(null)
    try {
      const result = await returnLoan.mutateAsync(loan.id)
      toast.success(returnedMessage(result))
      onReturned?.(result.loan)
      onClose()
    } catch (error) {
      if (error instanceof ApiError && error.code === "loan_already_returned") {
        setFailure("This loan was already returned. The page is now up to date.")
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
        <AlertDialogTitle>Return this copy?</AlertDialogTitle>
        <AlertDialogDescription>
          {loan.book.title} ({loan.copy.code}), borrowed by {loan.member.full_name} on{" "}
          {formatDate(loan.borrowed_at)}, due {formatDueDate(loan.due_at)}
          {loan.is_overdue ? " (overdue)" : ""}. The copy becomes available again, or is set
          aside for the first member waiting for the book.
        </AlertDialogDescription>
      </AlertDialogHeader>
      <FormAlert title="Could not return the copy" message={failure} />
      <AlertDialogFooter>
        <AlertDialogCancel>Cancel</AlertDialogCancel>
        <PendingButton
          pending={returnLoan.isPending}
          pendingLabel="Returning…"
          onClick={() => void confirm()}
        >
          Return copy
        </PendingButton>
      </AlertDialogFooter>
    </AlertDialogContent>
  )
}
