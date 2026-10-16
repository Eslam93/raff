import { useState } from "react"
import type { LucideIcon } from "lucide-react"

import { Pager } from "@/components/list/pager"
import { EmptyState } from "@/components/states/empty-state"
import { LoadingState } from "@/components/states/loading-state"
import { QueryState } from "@/components/states/query-state"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { useLoans } from "@/features/loans/hooks"
import { LoansTable } from "@/features/loans/loans-table"
import type { LoanOut, LoansParams } from "@/lib/types"
import { cn } from "@/lib/utils"

type LoansPanelProps = {
  /** The heading's id, which names the section. */
  id: string
  title: string
  /** Which loans: a status with a member or a book. */
  filter: Omit<LoansParams, "limit" | "offset">
  pageSize?: number
  showBook?: boolean
  showMember?: boolean
  onReturn?: (loan: LoanOut) => void
  onRenew?: (loan: LoanOut) => void
  empty: { icon: LucideIcon; title: string; description: string }
  className?: string
}

/** A titled list of one book's or one member's loans, a page at a time. */
export function LoansPanel({
  id,
  title,
  filter,
  pageSize = 10,
  showBook,
  showMember,
  onReturn,
  onRenew,
  empty,
  className,
}: LoansPanelProps) {
  const [page, setPage] = useState(1)
  const loans = useLoans({ ...filter, limit: pageSize, offset: (page - 1) * pageSize })

  return (
    <section aria-labelledby={id} className={cn("mt-8", className)}>
      <h2 id={id} className="mb-3 text-lg font-semibold tracking-tight">
        {title}
      </h2>
      <QueryState
        query={loans}
        isEmpty={(result) => result.items.length === 0}
        empty={
          (loans.data?.total ?? 0) > 0 ? (
            <EmptyState icon={empty.icon} title="This page is empty" description="The list is shorter now.">
              <Button variant="outline" size="sm" onClick={() => setPage(1)}>
                Go to the first page
              </Button>
            </EmptyState>
          ) : (
            <EmptyState icon={empty.icon} title={empty.title} description={empty.description} />
          )
        }
        loading={<LoadingState rows={2} label={`Loading ${title.toLowerCase()}`} />}
        errorTitle={`Could not load ${title.toLowerCase()}`}
      >
        {(result) => (
          <div
            className={cn("transition-opacity", loans.isPlaceholderData && "opacity-60")}
            aria-busy={loans.isPlaceholderData || undefined}
          >
            <Card className="py-0">
              <LoansTable
                loans={result.items}
                showBook={showBook}
                showMember={showMember}
                onReturn={onReturn}
                onRenew={onRenew}
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
  )
}
