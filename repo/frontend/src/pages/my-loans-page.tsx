import { useState } from "react"
import { BookMarked } from "lucide-react"
import { Link } from "react-router"

import { PageHeader } from "@/components/layout/page-header"
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
import { MyHoldsSection } from "@/features/holds/my-holds-section"
import { BookLink } from "@/features/loans/book-link"
import { DueState } from "@/features/loans/due-state"
import { useMyLoans } from "@/features/loans/hooks"
import { RenewDialog } from "@/features/loans/renew-dialog"
import { renewalCount, renewBlockedReason } from "@/features/loans/renewal"
import { useNow } from "@/hooks/use-now"
import { useUrlSearch } from "@/hooks/use-url-search"
import { formatDueDate } from "@/lib/format"
import type { LoanOut } from "@/lib/types"
import { cn } from "@/lib/utils"

const PAGE_SIZE = 20

/** The signed-in member's holds, then their active loans, due soonest first, with Renew. */
export function MyLoansPage() {
  const { page, setPage } = useUrlSearch()
  const offset = (page - 1) * PAGE_SIZE
  const loans = useMyLoans({ status: "active", limit: PAGE_SIZE, offset })
  const now = useNow()
  // The dialog keeps its loan while closing, so the closing animation shows it.
  const [renewing, setRenewing] = useState<{ open: boolean; loan: LoanOut | null }>({
    open: false,
    loan: null,
  })

  const empty =
    (loans.data?.total ?? 0) > 0 ? (
      <EmptyState icon={BookMarked} title="This page is empty" description="The list is shorter now.">
        <Button variant="outline" size="sm" onClick={() => setPage(1)}>
          Go to the first page
        </Button>
      </EmptyState>
    ) : (
      <EmptyState
        icon={BookMarked}
        title="You have no active loans"
        description="Books you borrow at the desk will appear here with their due dates."
      >
        <Button asChild variant="outline" size="sm">
          <Link to="/catalog">Browse the catalog</Link>
        </Button>
      </EmptyState>
    )

  return (
    <>
      <PageHeader
        title="My loans"
        description="Books you are waiting for, the books you have now, and when they are due back."
      />
      <MyHoldsSection />
      <section aria-labelledby="my-loans-heading">
        <h2 id="my-loans-heading" className="mb-3 text-lg font-semibold tracking-tight">
          Loans
        </h2>
        <QueryState
          query={loans}
          isEmpty={(result) => result.items.length === 0}
          empty={empty}
          loading={<LoadingState rows={3} label="Loading your loans" />}
          errorTitle="Could not load your loans"
        >
          {(result) => (
            <div
              className={cn("transition-opacity", loans.isPlaceholderData && "opacity-60")}
              aria-busy={loans.isPlaceholderData || undefined}
            >
              <Card className="py-0">
                <ActiveLoansTable
                  loans={result.items}
                  now={now}
                  onRenew={(loan) => setRenewing({ open: true, loan })}
                />
              </Card>
              <Pager
                total={result.total}
                limit={result.limit}
                offset={result.offset}
                noun={["loan", "loans"]}
                onPageChange={setPage}
              />
            </div>
          )}
        </QueryState>
      </section>
      <RenewDialog
        loan={renewing.loan}
        open={renewing.open}
        onOpenChange={(open) => setRenewing((current) => ({ ...current, open }))}
        mine
      />
    </>
  )
}

type ActiveLoansTableProps = {
  loans: LoanOut[]
  now: number
  onRenew: (loan: LoanOut) => void
}

function ActiveLoansTable({ loans, now, onRenew }: ActiveLoansTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Book</TableHead>
          <TableHead className="hidden sm:table-cell">Copy</TableHead>
          <TableHead>Due</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">
            <span className="sr-only">Renew</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {loans.map((loan) => (
          <TableRow key={loan.id}>
            <TableCell className="max-w-0 min-w-32 md:w-2/5">
              <BookLink book={loan.book} />
              <span className="block truncate text-xs text-muted-foreground">
                {loan.book.author}
                <span className="font-mono sm:hidden"> · {loan.copy.code}</span>
              </span>
            </TableCell>
            <TableCell className="hidden font-mono text-xs whitespace-nowrap sm:table-cell">
              {loan.copy.code}
            </TableCell>
            <TableCell className="whitespace-nowrap">
              {formatDueDate(loan.due_at)}
              {renewalCount(loan) && (
                <span className="block text-xs text-muted-foreground">{renewalCount(loan)}</span>
              )}
            </TableCell>
            <TableCell>
              <DueState loan={loan} now={now} />
            </TableCell>
            <TableCell className="text-right">
              {loan.can_renew ? (
                <Button
                  variant="outline"
                  size="sm"
                  aria-label={`Renew ${loan.book.title}`}
                  onClick={() => onRenew(loan)}
                >
                  Renew
                </Button>
              ) : (
                <span className="block text-xs text-muted-foreground">
                  {renewBlockedReason(loan)}
                </span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
