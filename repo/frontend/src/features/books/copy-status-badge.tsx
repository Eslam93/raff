import { Badge } from "@/components/ui/badge"
import type { CopyStatus } from "@/lib/types"

type CopyStatusBadgeProps = {
  status: CopyStatus
  overdue: boolean
}

/**
 * A copy's state: available, held (set aside for a member's hold), borrowed,
 * or overdue when its loan is past the due date.
 */
export function CopyStatusBadge({ status, overdue }: CopyStatusBadgeProps) {
  if (status === "available") return <Badge variant="available">Available</Badge>
  if (status === "held") return <Badge variant="held">Held</Badge>
  if (overdue) return <Badge variant="overdue">Overdue</Badge>
  return <Badge variant="borrowed">Borrowed</Badge>
}
