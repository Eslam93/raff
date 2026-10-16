import { Button } from "@/components/ui/button"
import type { HeldCopy } from "@/features/holds/held-copy"
import type { HoldOut } from "@/lib/types"

type HoldActionsProps = {
  hold: HoldOut
  held: HeldCopy | null
  onLend?: (held: HeldCopy) => void
  onCancel?: (hold: HoldOut) => void
}

/** Borrow for a ready hold (lends the copy set aside to its member) and Cancel for any open hold. */
export function HoldActions({ hold, held, onLend, onCancel }: HoldActionsProps) {
  return (
    <div className="flex flex-wrap justify-end gap-2">
      {held && onLend && (
        <Button
          variant="outline"
          size="sm"
          aria-label={`Borrow ${held.copy.code} to ${hold.member.full_name}`}
          onClick={() => onLend(held)}
        >
          Borrow
        </Button>
      )}
      {onCancel && (
        <Button
          variant="outline"
          size="sm"
          aria-label={`Cancel the hold of ${hold.member.full_name}`}
          onClick={() => onCancel(hold)}
        >
          Cancel
        </Button>
      )}
    </div>
  )
}
