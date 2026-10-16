import { useState, type RefObject } from "react"
import { BookmarkCheck } from "lucide-react"

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
import { useHolds } from "@/features/holds/hooks"
import { LendHeldCopyDialog } from "@/features/holds/lend-held-copy-dialog"
import { BookLink } from "@/features/loans/book-link"
import { MemberLink } from "@/features/members/member-link"
import { formatPickupDate } from "@/lib/format"
import type { HoldOut } from "@/lib/types"
import { cn } from "@/lib/utils"

const PAGE_SIZE = 10

/**
 * The circulation desk's shelf of copies set aside for holds: each ready hold
 * with its copy and pick-up date, the soonest first. Borrow lends the copy to
 * the member it waits for; Cancel gives it to the next in line.
 */
export function PickupPanel({ returnFocusTo }: { returnFocusTo: RefObject<HTMLElement | null> }) {
  const [page, setPage] = useState(1)
  const holds = useHolds({ status: "ready", limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  // The dialogs keep their hold while closing, so the closing animation shows it.
  const [lending, setLending] = useState<{ open: boolean; held: HeldCopy | null }>({
    open: false,
    held: null,
  })
  const [cancelling, setCancelling] = useState<{ open: boolean; hold: HoldOut | null }>({
    open: false,
    hold: null,
  })

  return (
    <section aria-labelledby="pickup-heading" className="mt-10">
      <h2 id="pickup-heading" className="mb-1 text-lg font-semibold tracking-tight">
        Waiting for pick-up
      </h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Copies set aside for members' holds. Each waits until the end of its pick-up day, then
        goes to the next member in line or back to the shelf.
      </p>
      <QueryState
        query={holds}
        isEmpty={(result) => result.items.length === 0}
        empty={
          (holds.data?.total ?? 0) > 0 ? (
            <EmptyState icon={BookmarkCheck} title="This page is empty" description="The list is shorter now.">
              <Button variant="outline" size="sm" onClick={() => setPage(1)}>
                Go to the first page
              </Button>
            </EmptyState>
          ) : (
            <EmptyState
              icon={BookmarkCheck}
              title="No copies waiting for pick-up"
              description="When a returned copy is set aside for a member's hold, it shows here until they borrow it."
            />
          )
        }
        loading={<LoadingState rows={2} label="Loading copies waiting for pick-up" />}
        errorTitle="Could not load the copies waiting for pick-up"
      >
        {(result) => (
          <div
            className={cn("transition-opacity", holds.isPlaceholderData && "opacity-60")}
            aria-busy={holds.isPlaceholderData || undefined}
          >
            <Card className="py-0">
              <PickupTable
                holds={result.items}
                onLend={(held) => setLending({ open: true, held })}
                onCancel={(hold) => setCancelling({ open: true, hold })}
              />
            </Card>
            <Pager
              total={result.total}
              limit={result.limit}
              offset={result.offset}
              noun={["copy", "copies"]}
              onPageChange={setPage}
            />
          </div>
        )}
      </QueryState>
      <LendHeldCopyDialog
        target={lending.held}
        open={lending.open}
        onOpenChange={(open) => setLending((current) => ({ ...current, open }))}
        returnFocusTo={returnFocusTo}
      />
      <CancelHoldDialog
        hold={cancelling.hold}
        open={cancelling.open}
        onOpenChange={(open) => setCancelling((current) => ({ ...current, open }))}
        returnFocusTo={returnFocusTo}
      />
    </section>
  )
}

type PickupTableProps = {
  holds: HoldOut[]
  onLend: (held: HeldCopy) => void
  onCancel: (hold: HoldOut) => void
}

function PickupTable({ holds, onLend, onCancel }: PickupTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Book</TableHead>
          <TableHead className="hidden md:table-cell">Member</TableHead>
          <TableHead className="hidden sm:table-cell">Copy</TableHead>
          <TableHead className="hidden sm:table-cell">Pick up by</TableHead>
          <TableHead className="text-right">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {holds.map((hold) => {
          const held = heldCopyOf(hold)
          return (
            <TableRow key={hold.id}>
              <TableCell className="max-w-0 min-w-32 md:w-1/3">
                <BookLink book={hold.book} />
                <span className="block truncate text-xs text-muted-foreground">{hold.book.author}</span>
                <span className="block truncate text-xs md:hidden">
                  For <MemberLink member={hold.member} />
                </span>
                {held?.pickup_by && (
                  <span className="block truncate text-xs text-muted-foreground sm:hidden">
                    <span className="font-mono">{held.copy.code}</span>, pick up by{" "}
                    {formatPickupDate(held.pickup_by)}
                  </span>
                )}
              </TableCell>
              <TableCell className="hidden max-w-0 min-w-28 md:table-cell">
                <MemberLink member={hold.member} className="block truncate" />
              </TableCell>
              <TableCell className="hidden font-mono text-xs whitespace-nowrap sm:table-cell">
                {hold.copy?.code}
              </TableCell>
              <TableCell className="hidden whitespace-nowrap sm:table-cell">
                {hold.pickup_by && formatPickupDate(hold.pickup_by)}
              </TableCell>
              <TableCell className="text-right">
                <HoldActions hold={hold} held={held} onLend={onLend} onCancel={onCancel} />
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
