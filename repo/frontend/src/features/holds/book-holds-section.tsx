import { useState } from "react"
import { BookmarkPlus, Hourglass } from "lucide-react"

import { Pager } from "@/components/list/pager"
import { EmptyState } from "@/components/states/empty-state"
import { LoadingState } from "@/components/states/loading-state"
import { QueryState } from "@/components/states/query-state"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { CancelHoldDialog } from "@/features/holds/cancel-hold-dialog"
import { heldCopyOf, type HeldCopy } from "@/features/holds/held-copy"
import { HoldActions } from "@/features/holds/hold-actions"
import { HoldStatusBadge } from "@/features/holds/hold-status-badge"
import { useHolds } from "@/features/holds/hooks"
import { PlaceHoldDialog } from "@/features/holds/place-hold-dialog"
import { MemberLink } from "@/features/members/member-link"
import { formatPickupDate } from "@/lib/format"
import type { BookDetail, HoldOut } from "@/lib/types"
import { cn } from "@/lib/utils"

const PAGE_SIZE = 10

type BookHoldsSectionProps = {
  book: BookDetail
  /** Place and cancel holds, and lend held copies: staff, on a book still in the catalog. */
  canChange: boolean
  /** Lends a ready hold's copy to its member. */
  onLend: (held: HeldCopy) => void
}

/**
 * Staff see who is waiting for a book: ready holds first, with the copy set
 * aside and the pick-up date, then the line in order.
 */
export function BookHoldsSection({ book, canChange, onLend }: BookHoldsSectionProps) {
  const [page, setPage] = useState(1)
  const holds = useHolds({
    status: "open",
    book_id: book.id,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  })
  const [placing, setPlacing] = useState(false)
  // The dialog keeps its hold while closing, so the closing animation shows it.
  const [cancelling, setCancelling] = useState<{ open: boolean; hold: HoldOut | null }>({
    open: false,
    hold: null,
  })
  const onShelf = book.copies.some((copy) => copy.status === "available")

  return (
    <section aria-labelledby="book-holds-heading" className="mt-8">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 id="book-holds-heading" className="text-lg font-semibold tracking-tight">
          Holds
        </h2>
        {canChange && (
          <Button
            variant="outline"
            size="sm"
            disabled={onShelf}
            aria-describedby={onShelf ? "place-hold-blocked" : undefined}
            onClick={() => setPlacing(true)}
          >
            <BookmarkPlus aria-hidden />
            Place hold for a member
          </Button>
        )}
      </div>
      {canChange && onShelf && (
        <p id="place-hold-blocked" className="-mt-1 mb-3 text-sm text-muted-foreground">
          A copy is on the shelf: borrow it instead of placing a hold.
        </p>
      )}
      <QueryState
        query={holds}
        isEmpty={(result) => result.items.length === 0}
        empty={
          (holds.data?.total ?? 0) > 0 ? (
            <EmptyState icon={Hourglass} title="This page is empty" description="The list is shorter now.">
              <Button variant="outline" size="sm" onClick={() => setPage(1)}>
                Go to the first page
              </Button>
            </EmptyState>
          ) : (
            <EmptyState
              icon={Hourglass}
              title="Nobody is waiting"
              description="When no copy is on the shelf, members can place a hold. They show here in line order."
            />
          )
        }
        loading={<LoadingState rows={2} label="Loading holds" />}
        errorTitle="Could not load the holds"
      >
        {(result) => (
          <div
            className={cn("transition-opacity", holds.isPlaceholderData && "opacity-60")}
            aria-busy={holds.isPlaceholderData || undefined}
          >
            <Card className="py-0">
              <BookHoldsTable
                holds={result.items}
                onLend={canChange ? onLend : undefined}
                onCancel={canChange ? (hold) => setCancelling({ open: true, hold }) : undefined}
              />
            </Card>
            <Pager
              total={result.total}
              limit={result.limit}
              offset={result.offset}
              noun={["hold", "holds"]}
              onPageChange={setPage}
            />
          </div>
        )}
      </QueryState>
      {canChange && (
        <>
          <PlaceHoldDialog book={book} open={placing} onOpenChange={setPlacing} />
          <CancelHoldDialog
            hold={cancelling.hold}
            open={cancelling.open}
            onOpenChange={(open) => setCancelling((current) => ({ ...current, open }))}
          />
        </>
      )}
    </section>
  )
}

type BookHoldsTableProps = {
  holds: HoldOut[]
  onLend?: (held: HeldCopy) => void
  onCancel?: (hold: HoldOut) => void
}

/** One row per open hold: the member, their place in line or the copy set aside, and the actions. */
function BookHoldsTable({ holds, onLend, onCancel }: BookHoldsTableProps) {
  const withActions = Boolean(onLend || onCancel)
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Member</TableHead>
          <TableHead className="hidden sm:table-cell">Place in line</TableHead>
          <TableHead className="hidden sm:table-cell">Status</TableHead>
          <TableHead className="hidden md:table-cell">Pick up by</TableHead>
          {withActions && (
            <TableHead className="text-right">
              <span className="sr-only">Actions</span>
            </TableHead>
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {holds.map((hold) => {
          const held = heldCopyOf(hold)
          return (
            <TableRow key={hold.id}>
              <TableCell className="max-w-0 min-w-32 sm:w-1/3">
                <MemberLink member={hold.member} className="block truncate font-medium" />
                <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground sm:hidden">
                  <HoldStatusBadge status={hold.status} />
                  {hold.position !== null && <span>Number {hold.position} in line</span>}
                  {held?.pickup_by && (
                    <span>
                      {held.copy.code}, pick up by {formatPickupDate(held.pickup_by)}
                    </span>
                  )}
                </span>
                {held?.pickup_by && (
                  <span className="hidden text-xs text-muted-foreground sm:block md:hidden">
                    Pick up by {formatPickupDate(held.pickup_by)}
                  </span>
                )}
              </TableCell>
              <TableCell className="hidden tabular-nums sm:table-cell">
                {hold.position ?? <span className="text-muted-foreground">Copy set aside</span>}
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                <span className="flex flex-wrap items-center gap-2">
                  <HoldStatusBadge status={hold.status} />
                  {hold.copy && <span className="font-mono text-xs">{hold.copy.code}</span>}
                </span>
              </TableCell>
              <TableCell className="hidden whitespace-nowrap md:table-cell">
                {hold.pickup_by && formatPickupDate(hold.pickup_by)}
              </TableCell>
              {withActions && (
                <TableCell className="text-right">
                  <HoldActions hold={hold} held={held} onLend={onLend} onCancel={onCancel} />
                </TableCell>
              )}
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
