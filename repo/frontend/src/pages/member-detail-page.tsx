import { useState } from "react"
import { ArrowLeft, BookMarked, History, UserX } from "lucide-react"
import { Link, useParams } from "react-router"

import { PageHeader } from "@/components/layout/page-header"
import { EmptyState } from "@/components/states/empty-state"
import { ErrorState } from "@/components/states/error-state"
import { LoadingState } from "@/components/states/loading-state"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { LoansPanel } from "@/features/loans/loans-panel"
import { RenewDialog } from "@/features/loans/renew-dialog"
import { ReturnDialog } from "@/features/loans/return-dialog"
import { useMember } from "@/features/members/hooks"
import { ApiError } from "@/lib/api"
import { formatCalendarDate, formatCount } from "@/lib/format"
import type { LoanOut, MemberDetailOut } from "@/lib/types"

const CURRENT_PAGE_SIZE = 20
const HISTORY_PAGE_SIZE = 10

function BackToMembers() {
  return (
    <Button asChild variant="ghost" size="sm" className="mb-2 -ml-3 text-muted-foreground">
      <Link to="/members">
        <ArrowLeft aria-hidden />
        Members
      </Link>
    </Button>
  )
}

export function MemberDetailPage() {
  const { memberId = "" } = useParams()
  const query = useMember(memberId)

  // A new member starts with fresh lists: no page number or loans carried over.
  if (query.data) return <MemberDetailView key={query.data.id} member={query.data} />

  // A malformed id in the link is refused with 422 before any lookup; to the reader it is the same dead link.
  if (query.isError && query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 422)) {
    return (
      <>
        <BackToMembers />
        <PageHeader title="Member not found" />
        <EmptyState
          icon={UserX}
          title="This member is not on the list"
          description="The link may be old or mistyped."
        >
          <Button asChild variant="outline" size="sm">
            <Link to="/members">Go to the members</Link>
          </Button>
        </EmptyState>
      </>
    )
  }

  return (
    <>
      <BackToMembers />
      <PageHeader title="Member" />
      {query.isError ? (
        <ErrorState
          title="Could not load the member"
          error={query.error}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <LoadingState rows={3} label="Loading the member" />
      )}
    </>
  )
}

/** A member's profile, the copies they have now, and what they borrowed before. */
function MemberDetailView({ member }: { member: MemberDetailOut }) {
  // The dialogs keep their loan while closing, so the closing animation shows it.
  const [returning, setReturning] = useState<{ open: boolean; loan: LoanOut | null }>({
    open: false,
    loan: null,
  })
  const [renewing, setRenewing] = useState<{ open: boolean; loan: LoanOut | null }>({
    open: false,
    loan: null,
  })

  return (
    <>
      <BackToMembers />
      <PageHeader title={member.full_name} description={member.email ?? "No email address"} />

      <Card>
        <CardContent>
          <dl className="grid gap-x-6 gap-y-4 text-sm sm:grid-cols-3">
            <Detail term="Member since" value={formatCalendarDate(member.joined_on)} />
            <Detail term="Loans in total" value={formatCount(member.loans_total)} />
            <Detail term="On loan now" value={formatCount(member.active_loans)} />
          </dl>
        </CardContent>
      </Card>

      <LoansPanel
        id="current-loans-heading"
        title="Current loans"
        filter={{ status: "active", member_id: member.id }}
        pageSize={CURRENT_PAGE_SIZE}
        showMember={false}
        onReturn={(loan) => setReturning({ open: true, loan })}
        onRenew={(loan) => setRenewing({ open: true, loan })}
        empty={{
          icon: BookMarked,
          title: "Nothing on loan",
          description: `Copies ${member.full_name} borrows will show here with their due dates.`,
        }}
      />

      <LoansPanel
        id="loan-history-heading"
        title="History"
        filter={{ status: "returned", member_id: member.id }}
        pageSize={HISTORY_PAGE_SIZE}
        showMember={false}
        empty={{
          icon: History,
          title: "No returned loans yet",
          description: "Loans show here once their copies come back, most recent first.",
        }}
      />

      <ReturnDialog
        loan={returning.loan}
        open={returning.open}
        onOpenChange={(open) => setReturning((current) => ({ ...current, open }))}
      />
      <RenewDialog
        loan={renewing.loan}
        open={renewing.open}
        onOpenChange={(open) => setRenewing((current) => ({ ...current, open }))}
      />
    </>
  )
}

function Detail({ term, value }: { term: string; value: string }) {
  return (
    <div className="min-w-0 space-y-1">
      <dt className="text-xs font-medium text-muted-foreground">{term}</dt>
      <dd className="truncate">{value}</dd>
    </div>
  )
}
