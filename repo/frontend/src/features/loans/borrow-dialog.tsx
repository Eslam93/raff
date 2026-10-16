import { useState, type RefObject } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import { useQueryClient } from "@tanstack/react-query"
import { Controller, useForm } from "react-hook-form"
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
import { NativeSelect } from "@/components/ui/native-select"
import { bookKeys, fetchBook } from "@/features/books/api"
import {
  borrowSchema,
  LOAN_PERIOD_DAYS,
  MAX_LOAN_DAYS,
  type BorrowFormOutput,
  type BorrowFormValues,
} from "@/features/loans/borrow-schema"
import { useBorrowCopy } from "@/features/loans/hooks"
import { MemberPicker } from "@/features/members/member-picker"
import { useDialogSession } from "@/hooks/use-dialog-session"
import { ApiError } from "@/lib/api"
import { addDays, todayDateValue } from "@/lib/dates"
import { applyServerErrors } from "@/lib/form-errors"
import { formatDueDate } from "@/lib/format"
import type { BookDetail, LoanOut } from "@/lib/types"

type BorrowDialogProps = {
  book: BookDetail
  /** The copy to preselect. The first available copy when not given. */
  copyId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called after the loan was created, before the dialog closes. */
  onBorrowed?: (loan: LoanOut) => void
  /** Where focus goes when the dialog closes. By default it goes back to the button that opened it. */
  returnFocusTo?: RefObject<HTMLElement | null>
}

/** Lends an available copy of a book to a member until a due date. */
export function BorrowDialog({
  book,
  copyId,
  open,
  onOpenChange,
  onBorrowed,
  returnFocusTo,
}: BorrowDialogProps) {
  const session = useDialogSession(open)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <BorrowContent
        key={session}
        book={book}
        copyId={copyId}
        onBorrowed={onBorrowed}
        returnFocusTo={returnFocusTo}
        onClose={() => onOpenChange(false)}
      />
    </Dialog>
  )
}

function firstAvailableCopyId(book: BookDetail) {
  return book.copies.find((copy) => copy.status === "available")?.id ?? ""
}

type BorrowContentProps = Pick<BorrowDialogProps, "book" | "copyId" | "onBorrowed" | "returnFocusTo"> & {
  onClose: () => void
}

function BorrowContent({ book, copyId, onBorrowed, returnFocusTo, onClose }: BorrowContentProps) {
  const queryClient = useQueryClient()
  const borrowCopy = useBorrowCopy(book.id)
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

  const availableCopies = book.copies.filter((copy) => copy.status === "available")
  const {
    control,
    register,
    handleSubmit,
    setError,
    setValue,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<BorrowFormValues, unknown, BorrowFormOutput>({
    resolver: zodResolver(borrowSchema),
    defaultValues: {
      copy_id: copyId ?? firstAvailableCopyId(book),
      member: null,
      due_date: dates.proposed,
    },
  })

  /**
   * Someone borrowed the chosen copy first, or a return set it aside for a
   * member's hold: reload the book and move to another copy. `heldMessage` is
   * the API's sentence for a held copy, which names the member.
   */
  async function recoverFromTakenCopy(takenCopyId: string, heldMessage?: string) {
    const takenCode = book.copies.find((copy) => copy.id === takenCopyId)?.code ?? "This copy"
    const fresh = await queryClient
      .fetchQuery({ queryKey: bookKeys.detail(book.id), queryFn: () => fetchBook(book.id) })
      .catch(() => null)
    const nextCopyId = fresh ? firstAvailableCopyId(fresh) : ""
    setValue("copy_id", nextCopyId)
    if (heldMessage) {
      setFormError(
        nextCopyId
          ? `${heldMessage} Another available copy is now selected: confirm to borrow it.`
          : `${heldMessage} No other copy of ${book.title} is available now.`,
      )
      return
    }
    setFormError(
      nextCopyId
        ? `${takenCode} was borrowed a moment ago by someone else. Another available copy is now selected: confirm to borrow it.`
        : `${takenCode} was borrowed a moment ago by someone else, and no other copy of ${book.title} is available now.`,
    )
  }

  async function borrow(values: BorrowFormOutput) {
    setFormError(null)
    try {
      const loan = await borrowCopy.mutateAsync({
        copy_id: values.copy_id,
        member_id: values.member.id,
        due_date: values.due_date,
      })
      toast.success(
        `Borrowed ${loan.book.title} (${loan.copy.code}) to ${loan.member.full_name}, due ${formatDueDate(loan.due_at)}`,
      )
      onBorrowed?.(loan)
      onClose()
    } catch (error) {
      if (error instanceof ApiError && error.code === "copy_unavailable") {
        await recoverFromTakenCopy(values.copy_id)
        return
      }
      if (error instanceof ApiError && error.code === "copy_held") {
        await recoverFromTakenCopy(values.copy_id, error.message)
        return
      }
      setFormError(
        applyServerErrors(error, setError, {
          fields: { copy_id: "copy_id", member_id: "member", due_date: "due_date" },
        }),
      )
    }
  }

  return (
    <DialogContent
      className="sm:max-w-lg"
      onInteractOutside={(event) => {
        if (isDirty) event.preventDefault()
      }}
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
        <DialogTitle>Borrow {book.title}</DialogTitle>
        <DialogDescription>
          by {book.author}. Choose the copy, the member and the due date.
        </DialogDescription>
      </DialogHeader>

      <form noValidate onSubmit={handleSubmit(borrow)} className="grid gap-4">
        <FormAlert title="Could not borrow the copy" message={formError} />

        <Field id="borrow-copy" label="Copy" error={errors.copy_id?.message}>
          {(control) => (
            <NativeSelect {...control} {...register("copy_id")}>
              {availableCopies.length === 0 && <option value="">No copy is available</option>}
              {availableCopies.map((copy) => (
                <option key={copy.id} value={copy.id}>
                  {copy.code}
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>

        <Field id="borrow-member" label="Member" error={errors.member?.message}>
          {(fieldControl) => (
            <Controller
              control={control}
              name="member"
              render={({ field }) => (
                <MemberPicker
                  {...fieldControl}
                  autoFocus
                  value={field.value}
                  onChange={field.onChange}
                  onBlur={field.onBlur}
                />
              )}
            />
          )}
        </Field>

        <Field
          id="borrow-due-date"
          label="Due date"
          error={errors.due_date?.message}
          hint={`Proposed: ${LOAN_PERIOD_DAYS} days from today. At most ${MAX_LOAN_DAYS} days.`}
          className="sm:max-w-56"
        >
          {(control) => (
            <Input
              {...control}
              type="date"
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
          <PendingButton
            type="submit"
            pending={isSubmitting}
            pendingLabel="Borrowing…"
            disabled={availableCopies.length === 0}
          >
            Borrow
          </PendingButton>
        </DialogFooter>
      </form>
    </DialogContent>
  )
}
