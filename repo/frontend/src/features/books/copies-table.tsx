import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { isCopyOverdue } from "@/features/books/copy-status"
import { CopyStatusBadge } from "@/features/books/copy-status-badge"
import { useNow } from "@/hooks/use-now"
import { formatDueDate, formatPickupDate } from "@/lib/format"
import type { CopyOut } from "@/lib/types"
import { cn } from "@/lib/utils"

type CopiesTableProps = {
  copies: CopyOut[]
  /**
   * Staff see who has each copy and who a held copy is set aside for. Everyone
   * else sees only when a copy is due back, and that a copy is set aside.
   */
  showBorrowers?: boolean
  /** The copy set aside for the signed-in member's own ready hold, which the table says is theirs. */
  myHeldCopyId?: string | null
  /** Row actions. Leave them out for a read-only table, such as for an archived book. */
  onBorrow?: (copy: CopyOut) => void
  onReturn?: (copy: CopyOut) => void
  /** Lends a held copy to the member it is set aside for. */
  onLend?: (copy: CopyOut) => void
}

function dueClass(overdue: boolean) {
  return overdue ? "font-medium text-overdue-foreground" : "text-muted-foreground"
}

/** One row per physical copy: its code, state, and the current loan or hold if it is out. */
export function CopiesTable({
  copies,
  showBorrowers = false,
  myHeldCopyId = null,
  onBorrow,
  onReturn,
  onLend,
}: CopiesTableProps) {
  const now = useNow()
  const withActions = Boolean(onBorrow || onReturn || onLend)

  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead>Copy</TableHead>
          <TableHead>Status</TableHead>
          {showBorrowers ? (
            <>
              <TableHead>Borrower</TableHead>
              <TableHead className="hidden sm:table-cell">Due</TableHead>
            </>
          ) : (
            <TableHead>Due</TableHead>
          )}
          {withActions && (
            <TableHead className="text-right">
              <span className="sr-only">Actions</span>
            </TableHead>
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {copies.map((copy) => {
          const loan = copy.active_loan
          const heldFor = copy.held_for
          const overdue = isCopyOverdue(copy, now)
          return (
            <TableRow key={copy.id}>
              <TableCell className="font-mono text-xs font-medium whitespace-nowrap">{copy.code}</TableCell>
              <TableCell>
                <CopyStatusBadge status={copy.status} overdue={overdue} />
              </TableCell>
              {showBorrowers ? (
                <>
                  <TableCell>
                    {loan?.member.full_name}
                    {loan && (
                      <span className={cn("block text-xs sm:hidden", dueClass(overdue))}>
                        Due {formatDueDate(loan.due_at)}
                      </span>
                    )}
                    {heldFor && (
                      <span className="text-muted-foreground">
                        Held for <span className="text-foreground">{heldFor.member.full_name}</span>{" "}
                        until {formatPickupDate(heldFor.pickup_by)}
                      </span>
                    )}
                  </TableCell>
                  <TableCell
                    className={cn("hidden whitespace-nowrap sm:table-cell", dueClass(overdue))}
                  >
                    {loan && formatDueDate(loan.due_at)}
                  </TableCell>
                </>
              ) : (
                <TableCell className={cn("whitespace-nowrap", dueClass(overdue))}>
                  {copy.status === "borrowed" && copy.due_at && `Due back ${formatDueDate(copy.due_at)}`}
                  {copy.status === "held" &&
                    (copy.id === myHeldCopyId ? "Set aside for you" : "Set aside for a member's hold")}
                </TableCell>
              )}
              {withActions && (
                <TableCell className="text-right">
                  {copy.status === "available" && onBorrow && (
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label={`Borrow ${copy.code}`}
                      onClick={() => onBorrow(copy)}
                    >
                      Borrow
                    </Button>
                  )}
                  {copy.status === "held" && heldFor && onLend && (
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label={`Borrow ${copy.code} to ${heldFor.member.full_name}`}
                      onClick={() => onLend(copy)}
                    >
                      Borrow
                    </Button>
                  )}
                  {copy.status === "borrowed" && loan && onReturn && (
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label={`Return ${copy.code}`}
                      onClick={() => onReturn(copy)}
                    >
                      Return
                    </Button>
                  )}
                </TableCell>
              )}
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
