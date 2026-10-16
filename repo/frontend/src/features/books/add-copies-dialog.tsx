import { useState } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

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
import { copyCountSchema, MAX_COPIES_PER_REQUEST } from "@/features/books/book-schema"
import { useAddCopies } from "@/features/books/hooks"
import { useDialogSession } from "@/hooks/use-dialog-session"
import { applyServerErrors } from "@/lib/form-errors"
import { plural } from "@/lib/format"
import type { BookDetail } from "@/lib/types"

const addCopiesSchema = z.object({ count: copyCountSchema })

type AddCopiesDialogProps = {
  book: BookDetail
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Adds physical copies to a book. Each new copy gets the next copy code. */
export function AddCopiesDialog({ book, open, onOpenChange }: AddCopiesDialogProps) {
  const session = useDialogSession(open)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <AddCopiesContent key={session} book={book} onClose={() => onOpenChange(false)} />
    </Dialog>
  )
}

function AddCopiesContent({ book, onClose }: { book: BookDetail; onClose: () => void }) {
  const addCopies = useAddCopies(book.id)
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(addCopiesSchema), defaultValues: { count: "1" } })

  async function save({ count }: z.output<typeof addCopiesSchema>) {
    setFormError(null)
    try {
      const saved = await addCopies.mutateAsync(count)
      toast.success(`Added ${plural(count, "copy", "copies")} to ${saved.title}`)
      onClose()
    } catch (error) {
      setFormError(applyServerErrors(error, setError, { fields: { count: "count" } }))
    }
  }

  return (
    <DialogContent className="sm:max-w-sm">
      <DialogHeader>
        <DialogTitle>Add copies</DialogTitle>
        <DialogDescription>
          {book.holds_waiting > 0
            ? `New copies of ${book.title} are set aside for the ${plural(book.holds_waiting, "member", "members")} waiting, first in line first. Any others are available to borrow at once.`
            : `New copies of ${book.title} are available to borrow at once.`}
        </DialogDescription>
      </DialogHeader>
      <form noValidate onSubmit={handleSubmit(save)} className="grid gap-4">
        <FormAlert title="Could not add copies" message={formError} />
        <Field
          id="copy-count"
          label="Number of copies"
          error={errors.count?.message}
          hint={`1 to ${MAX_COPIES_PER_REQUEST} at a time.`}
        >
          {(control) => (
            <Input {...control} type="number" min={1} max={MAX_COPIES_PER_REQUEST} {...register("count")} />
          )}
        </Field>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <PendingButton type="submit" pending={isSubmitting} pendingLabel="Adding…">
            Add copies
          </PendingButton>
        </DialogFooter>
      </form>
    </DialogContent>
  )
}
