import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router"
import { toast } from "sonner"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { formatDate, formatDueDate, formatPickupDate } from "@/lib/format"
import { MyLoansPage } from "@/pages/my-loans-page"
import { errorResponse, requestsTo, stubApi } from "@/test/api-stub"
import { hold, loan, memberUser, page, readyHold } from "@/test/fixtures"
import { renderWithProviders } from "@/test/render"

const PICKUP_BY = "2026-10-19T23:59:59Z"

const emma = hold({
  id: "hold-2",
  book: { id: "book-2", title: "Emma", author: "Jane Austen" },
  position: 3,
  placed_at: "2026-10-12T09:00:00Z",
})

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/my-loans" element={<MyLoansPage />} />
    </Routes>,
    { route: "/my-loans", user: memberUser() },
  )
}

function rowIn(region: HTMLElement, title: string) {
  return within(region).getByRole("link", { name: title }).closest("tr") as HTMLElement
}

describe("MyLoansPage: holds", () => {
  it("lists the member's holds above the loans: a copy to pick up, then places in line", async () => {
    const fetchMock = stubApi({
      "GET /api/me/holds": () => page([readyHold(), emma]),
      "GET /api/me/loans": () => page([]),
    })

    renderPage()

    const holds = await screen.findByRole("region", { name: "Holds" })
    await within(holds).findByRole("link", { name: "Emma" })
    const dune = rowIn(holds, "Dune")
    expect(dune).toHaveTextContent("Ready for pick-up")
    expect(dune).toHaveTextContent(`A copy is waiting for you: pick it up by ${formatPickupDate(PICKUP_BY)}`)
    expect(dune).toHaveTextContent("Ask at the desk for copy CP-0012")
    expect(rowIn(holds, "Emma")).toHaveTextContent("Waiting")
    expect(rowIn(holds, "Emma")).toHaveTextContent("Number 3 in line")
    expect(rowIn(holds, "Emma")).toHaveTextContent(formatDate("2026-10-12T09:00:00Z"))
    expect(within(holds).getByText("2 holds")).toBeInTheDocument()

    // The holds come before the loans on the page.
    const loans = screen.getByRole("region", { name: "Loans" })
    expect(holds.compareDocumentPosition(loans) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const [request] = requestsTo(fetchMock, "GET /api/me/holds")
    expect(request.search.get("status")).toBe("open")
  })

  it("cancels the member's own hold after they confirm", async () => {
    const success = vi.spyOn(toast, "success")
    const fetchMock = stubApi({
      "GET /api/me/holds": () => page([emma]),
      "GET /api/me/loans": () => page([]),
      "POST /api/me/holds/hold-2/cancel": () => ({ ...emma, status: "cancelled", position: null }),
    })
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("button", { name: "Cancel your hold on Emma" }))
    const dialog = await screen.findByRole("alertdialog", { name: "Cancel your hold?" })
    await user.click(within(dialog).getByRole("button", { name: "Cancel hold" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
    expect(requestsTo(fetchMock, "POST /api/me/holds/hold-2/cancel")).toHaveLength(1)
    expect(success).toHaveBeenCalledWith("Cancelled your hold on Emma")
  })

  it("says the hold is closed when it closed before the cancel", async () => {
    stubApi({
      "GET /api/me/holds": () => page([emma]),
      "GET /api/me/loans": () => page([]),
      "POST /api/me/holds/hold-2/cancel": () =>
        errorResponse(409, "hold_closed", "This hold is already closed."),
    })
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("button", { name: "Cancel your hold on Emma" }))
    const dialog = await screen.findByRole("alertdialog", { name: "Cancel your hold?" })
    await user.click(within(dialog).getByRole("button", { name: "Cancel hold" }))

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "This hold is already closed. The page is now up to date.",
    )
  })

  it("says so when the member has no holds, and when they cannot load", async () => {
    stubApi({ "GET /api/me/holds": () => page([]), "GET /api/me/loans": () => page([]) })
    const { unmount } = renderPage()

    const holds = await screen.findByRole("region", { name: "Holds" })
    expect(await within(holds).findByRole("heading", { name: "You have no holds" })).toBeInTheDocument()
    unmount()

    stubApi({
      "GET /api/me/holds": () => errorResponse(500, "internal_error", "The server failed."),
      "GET /api/me/loans": () => page([]),
    })
    renderPage()

    const failed = await screen.findByRole("region", { name: "Holds" })
    expect(await within(failed).findByRole("alert")).toHaveTextContent("Could not load your holds")
    // The loans still show on their own.
    expect(await screen.findByRole("heading", { name: "You have no active loans" })).toBeInTheDocument()
  })
})

describe("MyLoansPage: renewing", () => {
  beforeEach(() => {
    // Midday UTC keeps "today" the same calendar date in every time zone.
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(new Date("2026-10-16T12:00:00Z"))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("renews the member's own loan after they confirm", async () => {
    const success = vi.spyOn(toast, "success")
    // Overdue since 10 Oct: a renewal counts 14 days from today, 16 Oct.
    const overdue = loan({ due_at: "2026-10-10T23:59:59Z", is_overdue: true, days_overdue: 6 })
    const fetchMock = stubApi({
      "GET /api/me/holds": () => page([]),
      "GET /api/me/loans": () => page([overdue]),
      "POST /api/me/loans/loan-1/renew": () => ({
        ...overdue,
        due_at: "2026-10-30T23:59:59Z",
        is_overdue: false,
        days_overdue: 0,
        renewals: 1,
      }),
    })
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("button", { name: "Renew Dune" }))

    const dialog = await screen.findByRole("alertdialog", { name: "Renew this loan?" })
    expect(dialog).toHaveTextContent(
      `Dune (CP-0001) is due ${formatDueDate("2026-10-10T23:59:59Z")} (overdue). Renewing moves the due date to ${formatDueDate("2026-10-30T23:59:59Z")}. This is renewal 1 of 2.`,
    )
    expect(dialog).not.toHaveTextContent("borrowed by")
    await user.click(within(dialog).getByRole("button", { name: "Renew" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
    expect(requestsTo(fetchMock, "POST /api/me/loans/loan-1/renew")).toHaveLength(1)
    expect(success).toHaveBeenCalledWith(`Renewed Dune, now due ${formatDueDate("2026-10-30T23:59:59Z")}`)
  })

  it("shows how often each loan was renewed, and why one cannot be renewed", async () => {
    stubApi({
      "GET /api/me/holds": () => page([]),
      "GET /api/me/loans": () =>
        page([
          loan({ id: "loan-1", renewals: 1, can_renew: true }),
          loan({
            id: "loan-2",
            book: { id: "book-2", title: "Emma", author: "Jane Austen" },
            renewals: 2,
            can_renew: false,
          }),
          loan({
            id: "loan-3",
            book: { id: "book-3", title: "Middlemarch", author: "George Eliot" },
            renewals: 0,
            can_renew: false,
          }),
        ]),
    })

    renderPage()

    const loans = await screen.findByRole("region", { name: "Loans" })
    await within(loans).findByRole("link", { name: "Dune" })
    expect(rowIn(loans, "Dune")).toHaveTextContent("Renewed 1 of 2 times")
    expect(within(rowIn(loans, "Dune")).getByRole("button", { name: "Renew Dune" })).toBeInTheDocument()
    expect(rowIn(loans, "Emma")).toHaveTextContent("Renewed 2 of 2 times")
    expect(rowIn(loans, "Emma")).toHaveTextContent("No renewals left")
    expect(within(rowIn(loans, "Emma")).queryByRole("button")).not.toBeInTheDocument()
    expect(rowIn(loans, "Middlemarch")).toHaveTextContent("Cannot renew: a member is waiting for this book")
    expect(rowIn(loans, "Middlemarch")).not.toHaveTextContent("Renewed")
    expect(within(rowIn(loans, "Middlemarch")).queryByRole("button")).not.toBeInTheDocument()
  })

  it("shows the API's reason when the renewal is refused", async () => {
    stubApi({
      "GET /api/me/holds": () => page([]),
      "GET /api/me/loans": () => page([loan()]),
      "POST /api/me/loans/loan-1/renew": () =>
        errorResponse(409, "renewal_limit_reached", "This loan cannot be renewed again: the limit is 2 renewals."),
    })
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("button", { name: "Renew Dune" }))
    const dialog = await screen.findByRole("alertdialog", { name: "Renew this loan?" })
    await user.click(within(dialog).getByRole("button", { name: "Renew" }))

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "This loan cannot be renewed again: the limit is 2 renewals.",
    )
  })
})
