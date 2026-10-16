import { useState } from "react"
import { Archive, ArrowLeft, BookX, HandHelping, History, Pencil, Plus, Trash2 } from "lucide-react"
import { Link, useParams } from "react-router"

import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { ErrorState } from "@/components/states/error-state"
import { LoadingState } from "@/components/states/loading-state"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AddCopiesDialog } from "@/features/books/add-copies-dialog"
import { useIsStaff } from "@/features/auth/current-user"
import { AvailabilityBadge } from "@/features/books/availability-badge"
import { BookCover } from "@/features/books/book-cover"
import { BookFormDialog } from "@/features/books/book-form-dialog"
import { CopiesTable } from "@/features/books/copies-table"
import { isCopyOverdue } from "@/features/books/copy-status"
import { DeleteBookDialog } from "@/features/books/delete-book-dialog"
import { useBook } from "@/features/books/hooks"
import { BookHoldsSection } from "@/features/holds/book-holds-section"
import type { HeldCopy } from "@/features/holds/held-copy"
import { LendHeldCopyDialog } from "@/features/holds/lend-held-copy-dialog"
import { MemberHoldPanel } from "@/features/holds/member-hold-panel"
import { BorrowDialog } from "@/features/loans/borrow-dialog"
import { LoansPanel } from "@/features/loans/loans-panel"
import { ReturnDialog } from "@/features/loans/return-dialog"
import { loanOfCopy, type ReturnableLoan } from "@/features/loans/returnable-loan"
import { useNow } from "@/hooks/use-now"
import { ApiError } from "@/lib/api"
import { formatDate, plural } from "@/lib/format"
import type { BookDetail, CopyOut } from "@/lib/types"
import { cn } from "@/lib/utils"

function BackToCatalog() {
  return (
    <Button asChild variant="ghost" size="sm" className="mb-2 -ml-3 text-muted-foreground">
      <Link to="/catalog">
        <ArrowLeft aria-hidden />
        Catalog
      </Link>
    </Button>
  )
}

export function BookDetailPage() {
  const { bookId = "" } = useParams()
  const query = useBook(bookId)

  if (query.data) return <BookDetailView book={query.data} />

  // A malformed id in the link is refused with 422 before any lookup; to the reader it is the same dead link.
  if (query.isError && query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 422)) {
    return (
      <>
        <BackToCatalog />
        <PageHeader title="Book not found" />
        <EmptyState
          icon={BookX}
          title="This book is not in the catalog"
          description="It may have been deleted, or the link is wrong."
        >
          <Button asChild variant="outline" size="sm">
            <Link to="/catalog">Go to the catalog</Link>
          </Button>
        </EmptyState>
      </>
    )
  }

  return (
    <>
      <BackToCatalog />
      <PageHeader title="Book" />
      {query.isError ? (
        <ErrorState
          title="Could not load the book"
          error={query.error}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <LoadingState rows={3} label="Loading the book" />
      )}
    </>
  )
}

type OpenDialog = "edit" | "delete" | "copies" | null

/** A book with its copies. Staff also get the actions and see who has each copy. */
function BookDetailView({ book }: { book: BookDetail }) {
  const isStaff = useIsStaff()
  const now = useNow()
  const canChange = isStaff && !book.archived
  const [dialog, setDialog] = useState<OpenDialog>(null)
  // The borrow and return dialogs keep their copy while closing, so the closing animation shows it.
  const [borrow, setBorrow] = useState<{ open: boolean; copyId: string | null }>({
    open: false,
    copyId: null,
  })
  const [returning, setReturning] = useState<{ open: boolean; loan: ReturnableLoan | null }>({
    open: false,
    loan: null,
  })
  const [lending, setLending] = useState<{ open: boolean; held: HeldCopy | null }>({
    open: false,
    held: null,
  })

  const firstAvailable = book.copies.find((copy) => copy.status === "available")
  const onLoan = book.copies.filter((copy) => copy.status === "borrowed")
  const held = book.copies.filter((copy) => copy.status === "held").length
  const overdue = onLoan.filter((copy) => isCopyOverdue(copy, now)).length
  const borrowBlocked = firstAvailable
    ? null
    : book.copies.length === 0
      ? "No copies yet. Add a copy to lend this book."
      : held > 0
        ? "Every copy is on loan or set aside for a hold."
        : "Every copy is on loan. Return one to lend it again."

  function lendHeldCopy(copy: CopyOut) {
    if (!copy.held_for) return
    setLending({
      open: true,
      held: {
        book,
        copy: { id: copy.id, code: copy.code },
        member: copy.held_for.member,
        pickup_by: copy.held_for.pickup_by,
      },
    })
  }

  const closeDialog = (open: boolean) => {
    if (!open) setDialog(null)
  }

  return (
    <>
      <BackToCatalog />
      <PageHeader
        title={book.title}
        description={`by ${book.author}`}
        actions={
          canChange && (
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={!firstAvailable}
                aria-describedby={borrowBlocked ? "borrow-blocked" : undefined}
                onClick={() => setBorrow({ open: true, copyId: firstAvailable?.id ?? null })}
              >
                <HandHelping aria-hidden />
                Borrow
              </Button>
              <Button variant="outline" onClick={() => setDialog("copies")}>
                <Plus aria-hidden />
                Add copy
              </Button>
              <Button variant="outline" onClick={() => setDialog("edit")}>
                <Pencil aria-hidden />
                Edit
              </Button>
              <Button
                variant="outline"
                className="text-destructive hover:text-destructive"
                onClick={() => setDialog("delete")}
              >
                <Trash2 aria-hidden />
                Delete
              </Button>
            </div>
          )
        }
      />

      {book.archived && (
        <Alert variant="muted" className="mb-6">
          <Archive aria-hidden />
          <AlertTitle>This book is archived</AlertTitle>
          <AlertDescription>
            It is hidden from the catalog and its loan history is kept. It can no longer be edited
            or borrowed.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardContent className="flex items-start gap-6">
            <BookCover book={book} size="M" />
            <dl className="grid min-w-0 flex-1 gap-x-6 gap-y-4 text-sm sm:grid-cols-2">
              <Detail term="ISBN" value={book.isbn} mono />
              <Detail term="Category" value={book.category} />
              <Detail term="Year published" value={book.published_year?.toString() ?? null} />
              <Detail term="Added to the catalog" value={formatDate(book.created_at)} />
              <Detail term="Description" value={book.description} className="sm:col-span-2" />
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Availability</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <AvailabilityBadge book={book} />
            <p className="text-muted-foreground">
              {plural(book.copies_total, "copy", "copies")} in total, {book.copies_available}{" "}
              available, {onLoan.length} on loan
              {held > 0 && `, ${held} set aside for ${held === 1 ? "a hold" : "holds"}`}
              {overdue > 0 && (
                <span className="font-medium text-overdue-foreground">, {overdue} overdue</span>
              )}
              .
            </p>
            {book.holds_waiting > 0 && (
              <p className="text-muted-foreground">
                {book.holds_waiting === 1
                  ? "1 member is waiting in line."
                  : `${book.holds_waiting} members are waiting in line.`}
              </p>
            )}
            {borrowBlocked && canChange && (
              <p id="borrow-blocked" className="text-muted-foreground">
                {borrowBlocked}
              </p>
            )}
            {!isStaff && <MemberHoldPanel book={book} />}
          </CardContent>
        </Card>
      </div>

      <section aria-labelledby="copies-heading" className="mt-8">
        <h2 id="copies-heading" className="mb-3 text-lg font-semibold tracking-tight">
          Copies
        </h2>
        {book.copies.length === 0 ? (
          <EmptyState
            title="No copies yet"
            description={
              isStaff
                ? "Add a copy so members can borrow this book."
                : "The library has no copies of this book to lend yet."
            }
          >
            {canChange && (
              <Button variant="outline" size="sm" onClick={() => setDialog("copies")}>
                <Plus aria-hidden />
                Add copy
              </Button>
            )}
          </EmptyState>
        ) : (
          <Card className="py-0">
            <CopiesTable
              copies={book.copies}
              showBorrowers={isStaff}
              myHeldCopyId={book.my_hold?.status === "ready" ? book.my_hold.copy?.id : null}
              onBorrow={canChange ? (copy) => setBorrow({ open: true, copyId: copy.id }) : undefined}
              onReturn={
                canChange ? (copy) => setReturning({ open: true, loan: loanOfCopy(book, copy) }) : undefined
              }
              onLend={canChange ? lendHeldCopy : undefined}
            />
          </Card>
        )}
      </section>

      {/* Who is waiting is for staff only; a member sees their own hold above. A new book starts at page 1. */}
      {isStaff && !book.archived && (
        <BookHoldsSection
          key={`holds-${book.id}`}
          book={book}
          canChange={canChange}
          onLend={(heldCopy) => setLending({ open: true, held: heldCopy })}
        />
      )}

      {/* Who borrowed a copy is for staff only; members never see it. A new book starts at page 1. */}
      {isStaff && (
        <LoansPanel
          key={book.id}
          id="book-loans-heading"
          title="Loan history"
          filter={{ status: "all", book_id: book.id }}
          showBook={false}
          empty={{
            icon: History,
            title: "Never borrowed",
            description: "Each loan of a copy of this book will show here, newest first.",
          }}
        />
      )}

      {canChange && (
        <>
          <BookFormDialog book={book} open={dialog === "edit"} onOpenChange={closeDialog} />
          <AddCopiesDialog book={book} open={dialog === "copies"} onOpenChange={closeDialog} />
          <DeleteBookDialog book={book} open={dialog === "delete"} onOpenChange={closeDialog} />
          <BorrowDialog
            book={book}
            copyId={borrow.copyId}
            open={borrow.open}
            onOpenChange={(open) => setBorrow((current) => ({ ...current, open }))}
          />
          <ReturnDialog
            loan={returning.loan}
            open={returning.open}
            onOpenChange={(open) => setReturning((current) => ({ ...current, open }))}
          />
          <LendHeldCopyDialog
            target={lending.held}
            open={lending.open}
            onOpenChange={(open) => setLending((current) => ({ ...current, open }))}
          />
        </>
      )}
    </>
  )
}

type DetailProps = {
  term: string
  value: string | null
  mono?: boolean
  className?: string
}

function Detail({ term, value, mono, className }: DetailProps) {
  return (
    <div className={cn("space-y-1", className)}>
      <dt className="text-xs font-medium text-muted-foreground">{term}</dt>
      <dd className={mono ? "font-mono" : undefined}>
        {value ?? <span className="text-muted-foreground">Not given</span>}
      </dd>
    </div>
  )
}
