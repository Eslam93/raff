import { useState } from "react"
import { Hourglass } from "lucide-react"

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
import { HoldStatusBadge } from "@/features/holds/hold-status-badge"
import { useMyHolds } from "@/features/holds/hooks"
import { BookLink } from "@/features/loans/book-link"
import { formatDate, formatPickupDate } from "@/lib/format"
import type { HoldOut } from "@/lib/types"
import { cn } from "@/lib/utils"

const PAGE_SIZE = 10

/** The signed-in member's open holds: copies waiting for them first, then their places in line. */
export function MyHoldsSection() {
  const [page, setPage] = useState(1)
  const holds = useMyHolds({ status: "open", limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })
  // The dialog keeps its hold while closing, so the closing animation shows it.
  const [cancelling, setCancelling] = useState<{ open: boolean; hold: HoldOut | null }>({
    open: false,
    hold: null,
  })

  return (
    <section aria-labelledby="my-holds-heading" className="mb-10">
      <h2 id="my-holds-heading" className="mb-3 text-lg font-semibold tracking-tight">
        Holds
      </h2>
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
              title="You have no holds"
              description="When no copy of a book is on the shelf, place a hold on the book's page to get the next copy that comes back."
            />
          )
        }
        loading={<LoadingState rows={2} label="Loading your holds" />}
        errorTitle="Could not load your holds"
      >
        {(result) => (
          <div
            className={cn("transition-opacity", holds.isPlaceholderData && "opacity-60")}
            aria-busy={holds.isPlaceholderData || undefined}
          >
            <Card className="py-0">
              <MyHoldsTable holds={result.items} onCancel={(hold) => setCancelling({ open: true, hold })} />
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
      <CancelHoldDialog
        hold={cancelling.hold}
        open={cancelling.open}
        onOpenChange={(open) => setCancelling((current) => ({ ...current, open }))}
        mine
      />
    </section>
  )
}

/** Where the member stands: a copy to pick up by a date, or their place in line. */
function HoldProgress({ hold }: { hold: HoldOut }) {
  if (hold.status === "ready" && hold.pickup_by) {
    return (
      <span className="block">
        A copy is waiting for you: pick it up by {formatPickupDate(hold.pickup_by)}
        {hold.copy && (
          <span className="block text-xs text-muted-foreground">
            Ask at the desk for copy <span className="font-mono">{hold.copy.code}</span>
          </span>
        )}
      </span>
    )
  }
  if (hold.position) return <span className="block">Number {hold.position} in line</span>
  return null
}

function MyHoldsTable({ holds, onCancel }: { holds: HoldOut[]; onCancel: (hold: HoldOut) => void }) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Book</TableHead>
          <TableHead className="hidden sm:table-cell">Status</TableHead>
          <TableHead className="hidden md:table-cell">Placed</TableHead>
          <TableHead className="text-right">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {holds.map((hold) => (
          <TableRow key={hold.id}>
            <TableCell className="max-w-0 min-w-32 md:w-2/5">
              <BookLink book={hold.book} />
              <span className="block truncate text-xs text-muted-foreground">{hold.book.author}</span>
              <span className="mt-1 block text-xs whitespace-normal sm:hidden">
                <HoldStatusBadge status={hold.status} />
                <HoldProgress hold={hold} />
              </span>
            </TableCell>
            <TableCell className="hidden text-sm whitespace-normal sm:table-cell">
              <HoldStatusBadge status={hold.status} />
              <span className="mt-1 block">
                <HoldProgress hold={hold} />
              </span>
            </TableCell>
            <TableCell className="hidden whitespace-nowrap text-muted-foreground md:table-cell">
              {formatDate(hold.placed_at)}
            </TableCell>
            <TableCell className="text-right">
              <Button
                variant="outline"
                size="sm"
                aria-label={`Cancel your hold on ${hold.book.title}`}
                onClick={() => onCancel(hold)}
              >
                Cancel
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
