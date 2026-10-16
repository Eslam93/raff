import {
  ArrowDownLeft,
  ArrowUpRight,
  Archive,
  BookmarkCheck,
  BookmarkPlus,
  BookmarkX,
  BookOpen,
  CalendarPlus,
  Copy,
  Hourglass,
  PackageCheck,
  ScrollText,
  Sparkles,
  Trash2,
  UserPlus,
  type LucideIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { formatDateTime, formatRelative } from "@/lib/format"
import type { ActivityOut } from "@/lib/types"

type ActionKind = {
  icon: LucideIcon
  /** The kind of action in plain words, shown when the pointer rests on its icon. */
  label: string
}

const actionKinds: Partial<Record<string, ActionKind>> = {
  "book.created": { icon: BookOpen, label: "Book added" },
  "book.updated": { icon: BookOpen, label: "Book edited" },
  "book.archived": { icon: Archive, label: "Book archived" },
  "book.deleted": { icon: Trash2, label: "Book deleted" },
  "copy.added": { icon: Copy, label: "Copies added" },
  "member.created": { icon: UserPlus, label: "Member added" },
  "loan.borrowed": { icon: ArrowUpRight, label: "Borrowed" },
  "loan.returned": { icon: ArrowDownLeft, label: "Returned" },
  "loan.renewed": { icon: CalendarPlus, label: "Loan renewed" },
  "hold.placed": { icon: BookmarkPlus, label: "Hold placed" },
  "hold.ready": { icon: BookmarkCheck, label: "Copy set aside for a hold" },
  "hold.expired": { icon: Hourglass, label: "Hold expired: not picked up in time" },
  "hold.cancelled": { icon: BookmarkX, label: "Hold cancelled" },
  "hold.fulfilled": { icon: PackageCheck, label: "Hold fulfilled: the member borrowed the book" },
}

/**
 * One action: what happened, when, who did it, and whether through the
 * Copilot. An action the library took by itself, such as a hold expiring
 * after its pick-up date, has no person and says so.
 */
export function ActivityItem({ event, now }: { event: ActivityOut; now: number }) {
  const kind = actionKinds[event.action]
  const Icon = kind?.icon ?? ScrollText

  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <span
        title={kind?.label}
        className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground"
      >
        <Icon className="size-3.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm">{event.summary}</p>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <time dateTime={event.occurred_at} title={formatDateTime(event.occurred_at)}>
            {formatRelative(event.occurred_at, now)}
          </time>
          {event.actor && <span>by {event.actor}</span>}
          {!event.actor && event.via === "system" && <span>done automatically</span>}
          {event.via === "copilot" && (
            <Badge variant="secondary">
              <Sparkles aria-hidden />
              Copilot
            </Badge>
          )}
        </div>
      </div>
    </li>
  )
}
