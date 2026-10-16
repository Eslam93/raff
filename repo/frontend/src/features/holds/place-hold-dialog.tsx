import { useState } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import { Controller, useForm } from "react-hook-form"
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
import { usePlaceHold } from "@/features/holds/hooks"
import { MemberPicker } from "@/features/members/member-picker"
import type { PickedMember } from "@/features/members/member-schema"
import { useDialogSession } from "@/hooks/use-dialog-session"
import { applyServerErrors } from "@/lib/form-errors"
import type { BookDetail } from "@/lib/types"

const placeHoldSchema = z.object({
  member: z.custom<PickedMember | null>().transform((member, ctx) => {
    if (!member) {
      ctx.addIssue({ code: "custom", message: "Choose the member who waits for the book." })
      return z.NEVER
    }
    return member
  }),
})

type PlaceHoldValues = z.input<typeof placeHoldSchema>
type PlaceHoldOutput = z.output<typeof placeHoldSchema>

type PlaceHoldDialogProps = {
  book: BookDetail
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Staff put a member in line for a book that has no copy on the shelf. */
export function PlaceHoldDialog({ book, open, onOpenChange }: PlaceHoldDialogProps) {
  const session = useDialogSession(open)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <PlaceHoldContent key={session} book={book} onClose={() => onOpenChange(false)} />
    </Dialog>
  )
}

function PlaceHoldContent({ book, onClose }: { book: BookDetail; onClose: () => void }) {
  const placeHold = usePlaceHold(book.id)
  const [formError, setFormError] = useState<string | null>(null)
  const {
    control,
    handleSubmit,
    setError,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<PlaceHoldValues, unknown, PlaceHoldOutput>({
    resolver: zodResolver(placeHoldSchema),
    defaultValues: { member: null },
  })

  async function place({ member }: PlaceHoldOutput) {
    setFormError(null)
    try {
      const hold = await placeHold.mutateAsync(member.id)
      toast.success(
        `Placed a hold on ${hold.book.title} for ${hold.member.full_name}, number ${hold.position ?? 1} in line`,
      )
      onClose()
    } catch (error) {
      setFormError(
        applyServerErrors(error, setError, {
          fields: { member_id: "member" },
          // Refusals about this member belong on the member field.
          codes: {
            already_borrowed: "member",
            hold_exists: "member",
            hold_limit_reached: "member",
          },
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
    >
      <DialogHeader>
        <DialogTitle>Place a hold on {book.title}</DialogTitle>
        <DialogDescription>
          The member joins the end of the line. When a copy comes back, it is set aside for the
          first member in line.
        </DialogDescription>
      </DialogHeader>

      <form noValidate onSubmit={handleSubmit(place)} className="grid gap-4">
        <FormAlert title="Could not place the hold" message={formError} />

        <Field id="hold-member" label="Member" error={errors.member?.message}>
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

        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Cancel
            </Button>
          </DialogClose>
          <PendingButton type="submit" pending={isSubmitting} pendingLabel="Placing…">
            Place hold
          </PendingButton>
        </DialogFooter>
      </form>
    </DialogContent>
  )
}
