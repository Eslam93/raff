import { Badge } from "@/components/ui/badge"
import { formatOverdue } from "@/lib/format"
import type { CopyLookupOut } from "@/lib/types"

/** Where a looked-up copy stands: days overdue, on loan, held for a member, archived or available. */
export function CopyLookupBadge({ lookup }: { lookup: CopyLookupOut }) {
  const loan = lookup.active_loan
  if (loan) {
    return (
      <Badge variant={loan.is_overdue ? "overdue" : "borrowed"}>
        {loan.is_overdue ? formatOverdue(loan.days_overdue) : "On loan"}
      </Badge>
    )
  }
  if (lookup.status === "held") return <Badge variant="held">Held for pick-up</Badge>
  return (
    <Badge variant={lookup.archived ? "outline" : "available"}>
      {lookup.archived ? "Archived" : "Available"}
    </Badge>
  )
}
