import { useRef, useState, type RefObject } from "react"
import { ArrowLeftRight, CircleCheckBig, History, SearchX } from "lucide-react"
import { useSearchParams } from "react-router"

import { PageHeader } from "@/components/layout/page-header"
import { Pager } from "@/components/list/pager"
import { SearchField } from "@/components/list/search-field"
import { EmptyState } from "@/components/states/empty-state"
import { LoadingState } from "@/components/states/loading-state"
import { QueryState } from "@/components/states/query-state"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { BorrowByBook } from "@/features/circulation/borrow-by-book"
import { CopyDesk } from "@/features/circulation/copy-desk"
import { PickupPanel } from "@/features/holds/pickup-panel"
import { useLoans } from "@/features/loans/hooks"
import { LoansTable } from "@/features/loans/loans-table"
import { RenewDialog } from "@/features/loans/renew-dialog"
import { ReturnDialog } from "@/features/loans/return-dialog"
import { useUrlSearch } from "@/hooks/use-url-search"
import type { LoanListStatus, LoanOut } from "@/lib/types"
import { cn } from "@/lib/utils"

const PAGE_SIZE = 20

const loanTabs: readonly { status: LoanListStatus; label: string }[] = [
  { status: "active", label: "Active" },
  { status: "overdue", label: "Overdue" },
  { status: "returned", label: "Returned" },
  { status: "all", label: "All" },
]

function readStatus(value: string | null): LoanListStatus {
  return loanTabs.find((tab) => tab.status === value)?.status ?? "active"
}

/**
 * The staff workspace for the desk: return or borrow by copy code or by book,
 * the copies waiting for members to pick them up, and every loan below.
 */
export function CirculationPage() {
  const codeInput = useRef<HTMLInputElement>(null)

  return (
    <>
      <PageHeader
        title="Circulation"
        description="Return and borrow copies, and follow every loan."
        actions={<BorrowByBook returnFocusTo={codeInput} />}
      />
      <CopyDesk inputRef={codeInput} />
      <PickupPanel returnFocusTo={codeInput} />
      <LoansSection returnFocusTo={codeInput} />
    </>
  )
}

/** The loans list: a tab per status, a search, and paging, all kept in the URL. */
function LoansSection({ returnFocusTo }: { returnFocusTo: RefObject<HTMLElement | null> }) {
  const search = useUrlSearch()
  const [searchParams, setSearchParams] = useSearchParams()
  const status = readStatus(searchParams.get("status"))
  const offset = (search.page - 1) * PAGE_SIZE
  const loans = useLoans({ status, q: search.q || undefined, limit: PAGE_SIZE, offset })
  // The dialogs keep their loan while closing, so the closing animation shows it.
  const [returning, setReturning] = useState<{ open: boolean; loan: LoanOut | null }>({
    open: false,
    loan: null,
  })
  const [renewing, setRenewing] = useState<{ open: boolean; loan: LoanOut | null }>({
    open: false,
    loan: null,
  })

  function changeStatus(next: string) {
    setSearchParams((previous) => {
      const params = new URLSearchParams(previous)
      if (next === "active") params.delete("status")
      else params.set("status", next)
      params.delete("page")
      return params
    })
  }

  const list = (
    <>
      <SearchField
        label="Search loans"
        placeholder="Search by book, member or copy code"
        value={search.draft}
        onChange={search.changeDraft}
        onClear={search.clear}
        busy={loans.isFetching && loans.isPlaceholderData}
        className="mb-4"
      />
      <QueryState
        query={loans}
        isEmpty={(page) => page.items.length === 0}
        empty={
          <LoansEmpty
            status={status}
            q={search.q}
            total={loans.data?.total ?? 0}
            onClearSearch={search.clear}
            onFirstPage={() => search.setPage(1)}
          />
        }
        loading={<LoadingState rows={5} label="Loading loans" />}
        errorTitle="Could not load the loans"
      >
        {(page) => (
          <div
            className={cn("transition-opacity", loans.isPlaceholderData && "opacity-60")}
            aria-busy={loans.isPlaceholderData || undefined}
          >
            <Card className="py-0">
              <LoansTable
                loans={page.items}
                onReturn={(loan) => setReturning({ open: true, loan })}
                onRenew={(loan) => setRenewing({ open: true, loan })}
              />
            </Card>
            <Pager
              total={page.total}
              limit={page.limit}
              offset={page.offset}
              noun={["loan", "loans"]}
              onPageChange={search.setPage}
            />
          </div>
        )}
      </QueryState>
    </>
  )

  return (
    <section aria-labelledby="loans-heading" className="mt-10">
      <h2 id="loans-heading" className="mb-3 text-lg font-semibold tracking-tight">
        Loans
      </h2>
      <Tabs value={status} onValueChange={changeStatus}>
        <TabsList aria-label="Loans by status">
          {loanTabs.map((tab) => (
            <TabsTrigger key={tab.status} value={tab.status}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {loanTabs.map((tab) => (
          <TabsContent key={tab.status} value={tab.status}>
            {list}
          </TabsContent>
        ))}
      </Tabs>
      <ReturnDialog
        loan={returning.loan}
        open={returning.open}
        onOpenChange={(open) => setReturning((current) => ({ ...current, open }))}
        returnFocusTo={returnFocusTo}
      />
      <RenewDialog
        loan={renewing.loan}
        open={renewing.open}
        onOpenChange={(open) => setRenewing((current) => ({ ...current, open }))}
        returnFocusTo={returnFocusTo}
      />
    </section>
  )
}

type LoansEmptyProps = {
  status: LoanListStatus
  q: string
  total: number
  onClearSearch: () => void
  onFirstPage: () => void
}

/** Why the list is empty: the search, a page past the end, or nothing in this status. */
function LoansEmpty({ status, q, total, onClearSearch, onFirstPage }: LoansEmptyProps) {
  if (q) {
    return (
      <EmptyState
        icon={SearchX}
        title={`No loans match "${q}"`}
        description="Search looks at book titles and authors, member names and copy codes."
      >
        <Button variant="outline" size="sm" onClick={onClearSearch}>
          Clear search
        </Button>
      </EmptyState>
    )
  }
  if (total > 0) {
    return (
      <EmptyState icon={ArrowLeftRight} title="This page is empty" description="The list is shorter now.">
        <Button variant="outline" size="sm" onClick={onFirstPage}>
          Go to the first page
        </Button>
      </EmptyState>
    )
  }
  switch (status) {
    case "active":
      return (
        <EmptyState
          icon={ArrowLeftRight}
          title="No active loans"
          description="Every copy is on the shelf. Borrowed copies will show here with their due dates."
        />
      )
    case "overdue":
      return (
        <EmptyState
          icon={CircleCheckBig}
          title="No overdue loans"
          description="Good news: every copy on loan is within its due date."
        />
      )
    case "returned":
      return (
        <EmptyState
          icon={History}
          title="No returned loans yet"
          description="Loans will show here once their copies come back."
        />
      )
    case "all":
      return (
        <EmptyState
          icon={ArrowLeftRight}
          title="No loans yet"
          description="Borrow a copy by its code or by book to start."
        />
      )
  }
}
