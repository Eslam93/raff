import { useState } from "react"
import { useNavigate } from "react-router"
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
import { useDeleteBook } from "@/features/books/hooks"
import { useDialogSession } from "@/hooks/use-dialog-session"
import { ApiError } from "@/lib/api"
import { plural } from "@/lib/format"
import type { BookDetail } from "@/lib/types"

type DeleteBookDialogProps = {
  book: BookDetail
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * Confirms removing a book. A book that was never borrowed is deleted; one with
 * loan history is archived instead; one with a copy on loan cannot be removed.
 */
export function DeleteBookDialog({ book, open, onOpenChange }: DeleteBookDialogProps) {
  const session = useDialogSession(open)
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <DeleteBookContent key={session} book={book} onClose={() => onOpenChange(false)} />
    </AlertDialog>
  )
}

function DeleteBookContent({ book, onClose }: { book: BookDetail; onClose: () => void }) {
  const navigate = useNavigate()
  const deleteBook = useDeleteBook(book.id)
  // Set when the API refuses because a copy went out on loan after the page loaded.
  const [refusal, setRefusal] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  const copiesOnLoan = book.copies.filter((copy) => copy.status === "borrowed").length
  const refused = copiesOnLoan > 0 || refusal !== null
  const archives = book.has_loan_history
  // Removing the book cancels the holds on it: the members waiting and the copies set aside.
  const openHolds = book.holds_waiting + book.copies.filter((copy) => copy.status === "held").length
  const holdsNote =
    openHolds > 0
      ? ` ${plural(openHolds, "open hold", "open holds")} on it ${openHolds === 1 ? "is" : "are"} cancelled.`
      : ""

  async function confirm() {
    setFailure(null)
    try {
      const { outcome } = await deleteBook.mutateAsync()
      toast.success(outcome === "archived" ? `Archived ${book.title}` : `Deleted ${book.title}`)
      onClose()
      navigate("/catalog")
    } catch (error) {
      if (error instanceof ApiError && error.code === "book_has_active_loans") {
        setRefusal(error.message)
      } else {
        setFailure(error instanceof ApiError ? error.message : "Something went wrong. Try again.")
      }
    }
  }

  if (refused) {
    return (
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{book.title} cannot be removed now</AlertDialogTitle>
          <AlertDialogDescription>
            {copiesOnLoan > 0
              ? `${plural(copiesOnLoan, "copy is", "copies are")} on loan. A book cannot be deleted or archived while any copy is on loan. Return the ${copiesOnLoan === 1 ? "copy" : "copies"} first, then try again.`
              : `${refusal} Return every copy first, then try again.`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Close</AlertDialogCancel>
        </AlertDialogFooter>
      </AlertDialogContent>
    )
  }

  return (
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>
          {archives ? "Archive" : "Delete"} {book.title}?
        </AlertDialogTitle>
        <AlertDialogDescription>
          {archives
            ? `${book.title} will be archived: hidden from the catalog, its loan history kept. Its copies can no longer be borrowed.${holdsNote}`
            : `${book.title} will be permanently deleted, with its ${plural(book.copies_total, "copy", "copies")}. It has never been borrowed, so no history is lost.${holdsNote} This cannot be undone.`}
        </AlertDialogDescription>
      </AlertDialogHeader>
      <FormAlert title={`Could not ${archives ? "archive" : "delete"} the book`} message={failure} />
      <AlertDialogFooter>
        <AlertDialogCancel>Cancel</AlertDialogCancel>
        <PendingButton
          variant="destructive"
          pending={deleteBook.isPending}
          pendingLabel={archives ? "Archiving…" : "Deleting…"}
          onClick={() => void confirm()}
        >
          {archives ? "Archive book" : "Delete book"}
        </PendingButton>
      </AlertDialogFooter>
    </AlertDialogContent>
  )
}
