import { Badge } from "@/components/ui/badge"
import type { HoldStatus } from "@/lib/types"

const labels: Record<HoldStatus, string> = {
  waiting: "Waiting",
  ready: "Ready for pick-up",
  fulfilled: "Picked up",
  cancelled: "Cancelled",
  expired: "Expired",
}

/** A hold's state: waiting in line, a copy ready for pick-up, or how it closed. */
export function HoldStatusBadge({ status }: { status: HoldStatus }) {
  if (status === "ready") return <Badge variant="held">{labels.ready}</Badge>
  if (status === "waiting") return <Badge variant="secondary">{labels.waiting}</Badge>
  return <Badge variant="outline">{labels[status]}</Badge>
}
