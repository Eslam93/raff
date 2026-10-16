import { renewalCount, renewBlockedReason } from "@/features/loans/renewal"
import type { LoanOut } from "@/lib/types"
import { cn } from "@/lib/utils"

type RenewalNoteProps = {
  loan: LoanOut
  /** Also say why an active loan cannot be renewed, where Renew would be offered. */
  showReason?: boolean
  className?: string
}

/** "Renewed 1 of 2 times" under a loan's state, and the reason it cannot be renewed when asked. */
export function RenewalNote({ loan, showReason = false, className }: RenewalNoteProps) {
  const count = renewalCount(loan)
  const reason = showReason ? renewBlockedReason(loan) : null
  if (!count && !reason) return null
  return (
    <span className={cn("block text-xs text-muted-foreground", className)}>
      {count && <span className="block">{count}</span>}
      {reason && <span className="block">{reason}</span>}
    </span>
  )
}
