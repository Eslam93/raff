import { useState, type FormEvent, type ReactNode, type RefObject } from "react"
import {
  BookmarkCheck,
  CircleAlert,
  HandHelping,
  Loader2,
  ScanBarcode,
  SearchX,
  Undo2,
  X,
  type LucideIcon,
} from "lucide-react"
import { toast } from "sonner"

import { FormAlert } from "@/components/forms/form-alert"
import { PendingButton } from "@/components/forms/pending-button"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { normalizeCopyCode } from "@/features/circulation/copy-code"
import { CopyLookupBadge } from "@/features/circulation/copy-lookup-badge"
import { useCopyLookup } from "@/features/circulation/hooks"
import type { HeldCopy } from "@/features/holds/held-copy"
import { LendHeldCopyDialog } from "@/features/holds/lend-held-copy-dialog"
import { BookLink } from "@/features/loans/book-link"
import { BorrowBookDialog } from "@/features/loans/borrow-book-dialog"
import {
  returnedMessage,
  useBorrowByBookId,
  useReturnLoan,
  type ReturnResult,
} from "@/features/loans/hooks"
import { MemberLink } from "@/features/members/member-link"
import { ApiError } from "@/lib/api"
import { formatDate, formatDueDate, formatPickupDate } from "@/lib/format"
import type { CopyLookupOut, HeldFor, LoanOut } from "@/lib/types"

type CopyDeskProps = {
  /** The copy-code box. The page sends focus back here after every action, ready for the next scan. */
  inputRef: RefObject<HTMLInputElement | null>
}

/** A return that set the copy aside for the first member waiting for its book. */
type SetAside = {
  code: string
  title: string
  heldFor: HeldFor
}

/**
 * The circulation desk: type or scan a copy code and press Enter. A copy on
 * loan shows its loan with Return; an available copy offers Borrow; a copy
 * held for a member shows who and until when, and Borrow lends it to them.
 * After any of these, the box is empty and focused for the next code. When a
 * return sets the copy aside for a hold, the desk says so until the next code.
 */
export function CopyDesk({ inputRef }: CopyDeskProps) {
  const [draft, setDraft] = useState("")
  const [code, setCode] = useState<string | null>(null)
  const [notACode, setNotACode] = useState<string | null>(null)
  const [setAside, setSetAside] = useState<SetAside | null>(null)
  // The dialog keeps its copy while closing, so the closing animation shows it.
  const [lending, setLending] = useState<{ open: boolean; held: HeldCopy | null }>({
    open: false,
    held: null,
  })
  const lookup = useCopyLookup(code)
  const borrow = useBorrowByBookId()

  function submit(event: FormEvent) {
    event.preventDefault()
    const typed = draft.trim()
    if (!typed) return
    const normalized = normalizeCopyCode(typed)
    borrow.clearLoadError()
    setSetAside(null)
    setNotACode(normalized ? null : typed)
    if (normalized && normalized === code) void lookup.refetch()
    setCode(normalized)
    // The next scan replaces the code instead of adding to it.
    inputRef.current?.select()
  }

  /** Ready for the next code. */
  function clear() {
    setDraft("")
    setCode(null)
    setNotACode(null)
    setSetAside(null)
    borrow.clearLoadError()
    inputRef.current?.focus()
  }

  /** Ready for the next code, still saying where the returned copy goes when a hold took it. */
  function returned({ loan, heldFor }: ReturnResult) {
    clear()
    if (heldFor) setSetAside({ code: loan.copy.code, title: loan.book.title, heldFor })
  }

  const found = lookup.data
  let result: ReactNode = null
  if (notACode) {
    result = (
      <DeskMessage icon={CircleAlert} title={`"${notACode}" is not a copy code`}>
        Copy codes look like CP-0012. The number alone works too.
      </DeskMessage>
    )
  } else if (code && found) {
    result = (
      <CopyResult
        found={found}
        busy={lookup.isFetching}
        onDone={clear}
        onReturned={returned}
        onBorrow={() => borrow.start(found.book.id, found.copy.id)}
        onLend={(held) => setLending({ open: true, held })}
        borrowLoading={borrow.loading}
        borrowError={borrow.loadError}
      />
    )
  } else if (code && lookup.isError) {
    result =
      lookup.error instanceof ApiError && lookup.error.status === 404 ? (
        <DeskMessage icon={SearchX} title={`No copy has the code ${code}`}>
          Check the code on the label and try again.
        </DeskMessage>
      ) : (
        <DeskMessage icon={CircleAlert} title={`Could not look up ${code}`}>
          {lookup.error instanceof ApiError ? lookup.error.message : "Something went wrong."}{" "}
          <Button variant="link" className="h-auto p-0" onClick={() => void lookup.refetch()}>
            Try again
          </Button>
        </DeskMessage>
      )
  } else if (code) {
    result = (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
        Looking up {code}…
      </p>
    )
  } else if (setAside) {
    const member = setAside.heldFor.member.full_name
    result = (
      <Alert role="status" className="max-w-2xl">
        <BookmarkCheck aria-hidden />
        <AlertTitle>
          {setAside.code} is held for {member}
        </AlertTitle>
        <AlertDescription>
          The return set this copy aside for the first member waiting for {setAside.title}. Keep it
          at the desk for {member} until {formatPickupDate(setAside.heldFor.pickup_by)}.
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <section aria-labelledby="copy-desk-heading" className="space-y-4">
      <h2 id="copy-desk-heading" className="sr-only">
        Return or borrow by copy code
      </h2>
      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="grid flex-1 gap-2 sm:max-w-md">
          <Label htmlFor="copy-code">Copy code</Label>
          <div className="relative">
            <ScanBarcode
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              ref={inputRef}
              id="copy-code"
              // Staff arrive here to scan: the box is ready at once.
              autoFocus
              autoComplete="off"
              spellCheck={false}
              placeholder="Type or scan, then press Enter"
              aria-describedby="copy-code-hint"
              className="h-10 pl-9 font-mono"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
          </div>
        </div>
        <Button type="submit" variant="secondary" className="h-10">
          Look up
        </Button>
      </form>
      <p id="copy-code-hint" className="-mt-2 text-xs text-muted-foreground">
        CP-0012, cp-12 and 12 all find copy CP-0012.
      </p>
      {result}
      <BorrowBookDialog
        target={borrow.target}
        onOpenChange={borrow.setOpen}
        onBorrowed={clear}
        returnFocusTo={inputRef}
      />
      <LendHeldCopyDialog
        target={lending.held}
        open={lending.open}
        onOpenChange={(open) => setLending((current) => ({ ...current, open }))}
        onBorrowed={clear}
        returnFocusTo={inputRef}
      />
    </section>
  )
}

type DeskMessageProps = {
  icon: LucideIcon
  title: string
  children: ReactNode
}

function DeskMessage({ icon: Icon, title, children }: DeskMessageProps) {
  return (
    <Alert role="alert" className="max-w-2xl">
      <Icon aria-hidden />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  )
}

type CopyResultProps = {
  found: CopyLookupOut
  /** A new lookup of the same code is on its way. */
  busy: boolean
  onDone: () => void
  onReturned: (result: ReturnResult) => void
  onBorrow: () => void
  /** Lends a held copy to the member it is set aside for. */
  onLend: (held: HeldCopy) => void
  borrowLoading: boolean
  borrowError: Error | null
}

/**
 * The copy behind the code: its loan with Return, who it is held for with
 * Borrow for that member, or Borrow when it is on the shelf.
 */
function CopyResult({
  found,
  busy,
  onDone,
  onReturned,
  onBorrow,
  onLend,
  borrowLoading,
  borrowError,
}: CopyResultProps) {
  const loan = found.active_loan
  const heldFor = found.held_for
  return (
    <Card
      role="group"
      aria-label={`Copy ${found.copy.code}`}
      aria-busy={busy || undefined}
      className="max-w-2xl gap-4 py-4 transition-opacity aria-busy:opacity-60"
    >
      <CardContent className="space-y-4 px-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-medium">{found.copy.code}</span>
          <CopyLookupBadge lookup={found} />
        </div>
        <div className="min-w-0">
          <BookLink book={found.book} />
          <p className="truncate text-sm text-muted-foreground">by {found.book.author}</p>
        </div>
        {loan ? (
          <LoanReturn loan={loan} onDone={onDone} onReturned={onReturned} />
        ) : found.status === "held" && heldFor ? (
          <>
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
              <div className="space-y-1">
                <dt className="text-xs font-medium text-muted-foreground">Held for</dt>
                <dd>
                  <MemberLink member={heldFor.member} className="font-medium" />
                </dd>
              </div>
              <div className="space-y-1">
                <dt className="text-xs font-medium text-muted-foreground">Pick up by</dt>
                <dd>{formatPickupDate(heldFor.pickup_by)}</dd>
              </div>
            </dl>
            <p className="text-sm text-muted-foreground">
              This copy is set aside for a hold. Only {heldFor.member.full_name} can borrow it until
              then.
            </p>
            <DeskActions onDone={onDone}>
              <Button
                aria-label={`Borrow ${found.copy.code} to ${heldFor.member.full_name}`}
                onClick={() =>
                  onLend({
                    book: found.book,
                    copy: found.copy,
                    member: heldFor.member,
                    pickup_by: heldFor.pickup_by,
                  })
                }
              >
                <HandHelping aria-hidden />
                Borrow
              </Button>
            </DeskActions>
          </>
        ) : found.archived ? (
          <>
            <p className="text-sm text-muted-foreground">
              This copy is archived with its book, so it cannot be borrowed.
            </p>
            <DeskActions onDone={onDone} />
          </>
        ) : (
          <>
            <FormAlert
              title="Could not open the borrow form"
              message={borrowError ? errorMessage(borrowError) : null}
            />
            <DeskActions onDone={onDone}>
              <PendingButton pending={borrowLoading} pendingLabel="Opening…" onClick={onBorrow}>
                <HandHelping aria-hidden />
                Borrow
              </PendingButton>
            </DeskActions>
          </>
        )}
      </CardContent>
    </Card>
  )
}

type LoanReturnProps = {
  loan: LoanOut
  onDone: () => void
  onReturned: (result: ReturnResult) => void
}

/** The loan on a scanned copy. Seeing it and pressing Return copy is the confirmation. */
function LoanReturn({ loan, onDone, onReturned }: LoanReturnProps) {
  const returnLoan = useReturnLoan(loan.book.id)
  const [failure, setFailure] = useState<string | null>(null)

  async function confirm() {
    setFailure(null)
    try {
      const result = await returnLoan.mutateAsync(loan.id)
      toast.success(returnedMessage(result))
      onReturned(result)
    } catch (error) {
      setFailure(
        error instanceof ApiError && error.code === "loan_already_returned"
          ? "This loan was already returned."
          : errorMessage(error),
      )
    }
  }

  return (
    <>
      <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
        <div className="space-y-1">
          <dt className="text-xs font-medium text-muted-foreground">Borrowed by</dt>
          <dd>
            <MemberLink member={loan.member} className="font-medium" />
          </dd>
        </div>
        <div className="space-y-1">
          <dt className="text-xs font-medium text-muted-foreground">Borrowed</dt>
          <dd>{formatDate(loan.borrowed_at)}</dd>
        </div>
        <div className="space-y-1">
          <dt className="text-xs font-medium text-muted-foreground">Due</dt>
          <dd className={loan.is_overdue ? "font-medium text-overdue-foreground" : undefined}>
            {formatDueDate(loan.due_at)}
          </dd>
        </div>
      </dl>
      <FormAlert title="Could not return the copy" message={failure} />
      <DeskActions onDone={onDone}>
        <PendingButton
          pending={returnLoan.isPending}
          pendingLabel="Returning…"
          onClick={() => void confirm()}
        >
          <Undo2 aria-hidden />
          Return copy
        </PendingButton>
      </DeskActions>
    </>
  )
}

function DeskActions({ onDone, children }: { onDone: () => void; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap gap-2">
      {children}
      <Button variant="ghost" onClick={onDone}>
        <X aria-hidden />
        Clear
      </Button>
    </div>
  )
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "Something went wrong. Try again."
}
