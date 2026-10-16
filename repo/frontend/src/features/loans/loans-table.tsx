import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { BookLink } from "@/features/loans/book-link"
import { LoanState } from "@/features/loans/loan-state"
import { RenewalNote } from "@/features/loans/renewal-note"
import { MemberLink } from "@/features/members/member-link"
import { formatDate, formatDueDate } from "@/lib/format"
import type { LoanOut } from "@/lib/types"
import { cn } from "@/lib/utils"

type LoansTableProps = {
  loans: LoanOut[]
  /** Leave out what the page already names: the book on a book's page, the member on a member's page. */
  showBook?: boolean
  showMember?: boolean
  /** Adds Return to each loan that is still out. */
  onReturn?: (loan: LoanOut) => void
  /** Adds Renew to each loan that can be renewed now, and says why for one that cannot. */
  onRenew?: (loan: LoanOut) => void
}

function dueClass(loan: LoanOut) {
  const overdue = loan.is_overdue && !loan.returned_at
  return overdue ? "font-medium text-overdue-foreground" : "text-muted-foreground"
}

/**
 * Loans with their book, member, copy, dates and state. The first column
 * leads; on narrower screens it also carries what the hidden columns would
 * show, so every row stays readable without scrolling sideways.
 */
export function LoansTable({
  loans,
  showBook = true,
  showMember = true,
  onReturn,
  onRenew,
}: LoansTableProps) {
  const both = showBook && showMember
  const withActions = Boolean(onReturn || onRenew)
  // With both book and member there is less room, so the borrowed date gets its own column later.
  const borrowedColumn = both ? "hidden xl:table-cell" : "hidden lg:table-cell"
  const borrowedInLead = both ? "xl:hidden" : "lg:hidden"

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {showBook && <TableHead>Book</TableHead>}
          {showMember && (
            <TableHead className={cn(both && "hidden lg:table-cell")}>Member</TableHead>
          )}
          <TableHead className="hidden lg:table-cell">Copy</TableHead>
          <TableHead className={borrowedColumn}>Borrowed</TableHead>
          <TableHead className="hidden sm:table-cell">Due</TableHead>
          <TableHead className="hidden sm:table-cell">Status</TableHead>
          {withActions && (
            <TableHead className="text-right">
              <span className="sr-only">Actions</span>
            </TableHead>
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {loans.map((loan) => (
          <TableRow key={loan.id}>
            <TableCell className="max-w-0 min-w-32 lg:w-1/3">
              {showBook ? (
                <>
                  <BookLink book={loan.book} />
                  <span className="block truncate text-xs text-muted-foreground">
                    {loan.book.author}
                  </span>
                </>
              ) : (
                <MemberLink member={loan.member} className="block truncate font-medium" />
              )}
              {both && (
                <span className="block truncate text-xs lg:hidden">
                  <MemberLink member={loan.member} />
                </span>
              )}
              <span className="block truncate text-xs text-muted-foreground">
                <span className="font-mono lg:hidden">{loan.copy.code}</span>
                <span className={borrowedInLead}>
                  <span className="lg:hidden"> · </span>Borrowed {formatDate(loan.borrowed_at)}
                </span>
              </span>
              <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs sm:hidden">
                <LoanState loan={loan} />
                {!loan.returned_at && (
                  <span className={dueClass(loan)}>Due {formatDueDate(loan.due_at)}</span>
                )}
              </span>
              <RenewalNote loan={loan} showReason={Boolean(onRenew)} className="sm:hidden" />
            </TableCell>
            {both && (
              <TableCell className="hidden max-w-0 min-w-28 lg:table-cell">
                <MemberLink member={loan.member} className="block truncate" />
              </TableCell>
            )}
            <TableCell className="hidden font-mono text-xs whitespace-nowrap lg:table-cell">
              {loan.copy.code}
            </TableCell>
            <TableCell className={cn("whitespace-nowrap text-muted-foreground", borrowedColumn)}>
              {formatDate(loan.borrowed_at)}
            </TableCell>
            <TableCell className={cn("hidden whitespace-nowrap sm:table-cell", dueClass(loan))}>
              {formatDueDate(loan.due_at)}
            </TableCell>
            <TableCell className="hidden sm:table-cell">
              <LoanState loan={loan} />
              <RenewalNote loan={loan} showReason={Boolean(onRenew)} className="mt-1" />
            </TableCell>
            {withActions && (
              <TableCell className="text-right">
                {!loan.returned_at && (
                  <div className="flex flex-wrap justify-end gap-2">
                    {onRenew && loan.can_renew && (
                      <Button
                        variant="outline"
                        size="sm"
                        aria-label={`Renew ${loan.copy.code}`}
                        onClick={() => onRenew(loan)}
                      >
                        Renew
                      </Button>
                    )}
                    {onReturn && (
                      <Button
                        variant="outline"
                        size="sm"
                        aria-label={`Return ${loan.copy.code}`}
                        onClick={() => onReturn(loan)}
                      >
                        Return
                      </Button>
                    )}
                  </div>
                )}
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
