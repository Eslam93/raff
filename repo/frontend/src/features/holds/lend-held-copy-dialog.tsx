import { useState, type RefObject } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import { useForm } from "react-hook-form"
import { toast } from "sonner"

import { Field } from "@/components/forms/field"
import { FormAlert } from "@/components/forms/form-alert"
import { PendingButton } from "@/components/forms/pending-button"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import type { HeldCopy } from "@/features/holds/held-copy"
import { borrowSchema, LOAN_PERIOD_DAYS, MAX_LOAN_DAYS } from "@/features/loans/borrow-schema"
import { useBorrowCopy } from "@/features/loans/hooks"
import { useDialogSession } from "@/hooks/use-dialog-session"
import { ApiError } from "@/lib/api"
import { addDays, todayDateValue } from "@/lib/dates"
import { applyServerErrors } from "@/lib/form-errors"
import { formatDueDate, formatPickupDate } from "@/lib/format"
import type { LoanOut } from "@/lib/types"

type LendHeldCopyDialogProps = {
  /** The held copy, as it was when the dialog opened. */
  target: HeldCopy | null
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called after the loan was created, before the dialog closes. */
  onBorrowed?: (loan: LoanOut) => void
  /** Where focus goes when the dialog closes. By default it goes back to the button that opened it. */
  returnFocusTo?: RefObject<HTMLElement | null>
}

const dueDateSchema = borrowSchema.pick({ due_date: true })

/**
 * Lends a held copy to the member it is set aside for. The copy and the
 * member are fixed by the hold, so only the due date is chosen. The loan
 * fulfils the hold.
 */
export function LendHeldCopyDialog({ target, open, onOpenChange, ...rest }: LendHeldCopyDialogProps) {
  const session = useDialogSession(open)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {target && (
        <LendContent key={session} target={target} onClose={() => onOpenChange(false)} {...rest} />
      )}
    </Dialog>
  )
}

type LendContentProps = Pick<LendHeldCopyDialogProps, "onBorrowed" | "returnFocusTo"> & {
  target: HeldCopy
  onClose: () => void
}

function LendContent({ target, onBorrowed, returnFocusTo, onClose }: LendContentProps) {
  const borrowCopy = useBorrowCopy(target.book.id)
  const [formError, setFormError] = useState<string | null>(null)
  // Date limits are fixed when the dialog opens.
  const [dates] = useState(() => {
    const today = todayDateValue()
    return {
      earliest: addDays(today, 1),
      latest: addDays(today, MAX_LOAN_DAYS),
      proposed: addDays(today, LOAN_PERIOD_DAYS),
    }
  })
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(dueDateSchema), defaultValues: { due_date: dates.proposed } })

  async function lend({ due_date }: { due_date: string }) {
    setFormError(null)
    try {
      const loan = await borrowCopy.mutateAsync({
        copy_id: target.copy.id,
        member_id: target.member.id,
        due_date,
      })
      toast.success(
        `Borrowed ${loan.book.title} (${loan.copy.code}) to ${loan.member.full_name}, due ${formatDueDate(loan.due_at)}`,
      )
      onBorrowed?.(loan)
      onClose()
    } catch (error) {
      if (error instanceof ApiError && (error.code === "copy_held" || error.code === "copy_unavailable")) {
        // The hold expired or was cancelled meanwhile, and the copy went to someone else.
        setFormError(`${error.message} The page is now up to date.`)
        return
      }
      setFormError(applyServerErrors(error, setError, { fields: { due_date: "due_date" } }))
    }
  }

  const until = target.pickup_by ? ` until ${formatPickupDate(target.pickup_by)}` : ""

  return (
    <DialogContent
      className="sm:max-w-lg"
      onCloseAutoFocus={
        returnFocusTo
          ? (event) => {
              event.preventDefault()
              returnFocusTo.current?.focus()
            }
          : undefined
      }
    >
      <DialogHeader>
        <DialogTitle>
          Borrow {target.book.title} to {target.member.full_name}
        </DialogTitle>
        <DialogDescription>
          {target.copy.code} is set aside for {target.member.full_name}
          {until}. Choose the due date; the loan fulfils the hold.
        </DialogDescription>
      </DialogHeader>

      <form noValidate onSubmit={handleSubmit(lend)} className="grid gap-4">
        <FormAlert title="Could not borrow the copy" message={formError} />

        <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <div className="space-y-1">
            <dt className="text-xs font-medium text-muted-foreground">Copy</dt>
            <dd className="font-mono">{target.copy.code}</dd>
          </div>
          <div className="space-y-1">
            <dt className="text-xs font-medium text-muted-foreground">Member</dt>
            <dd>{target.member.full_name}</dd>
          </div>
        </dl>

        <Field
          id="lend-due-date"
          label="Due date"
          error={errors.due_date?.message}
          hint={`Proposed: ${LOAN_PERIOD_DAYS} days from today. At most ${MAX_LOAN_DAYS} days.`}
          className="sm:max-w-56"
        >
          {(control) => (
            <Input
              {...control}
              type="date"
              autoFocus
              min={dates.earliest}
              max={dates.latest}
              {...register("due_date")}
            />
          )}
        </Field>

        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <PendingButton type="submit" pending={isSubmitting} pendingLabel="Borrowing…">
            Borrow
          </PendingButton>
        </DialogFooter>
      </form>
    </DialogContent>
  )
}
