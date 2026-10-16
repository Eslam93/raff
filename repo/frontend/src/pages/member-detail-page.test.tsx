import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router"
import { describe, expect, it } from "vitest"

import { formatCalendarDate, formatDate } from "@/lib/format"
import { MemberDetailPage } from "@/pages/member-detail-page"
import { MembersPage } from "@/pages/members-page"
import { errorResponse, requestsTo, stubApi } from "@/test/api-stub"
import { loan, member, memberDetail, page } from "@/test/fixtures"
import { renderWithProviders } from "@/test/render"

const maya = { id: "member-1", full_name: "Maya Hassan" }

const overdueLoan = loan({
  id: "loan-1",
  member: maya,
  copy: { id: "copy-1", code: "CP-0001" },
  due_at: "2026-09-10T23:59:59Z",
  is_overdue: true,
  days_overdue: 9,
})

const currentLoan = loan({
  id: "loan-2",
  member: maya,
  copy: { id: "copy-5", code: "CP-0005" },
  book: { id: "book-2", title: "Emma", author: "Jane Austen" },
  due_at: "2026-09-30T23:59:59Z",
})

const returnedLoan = loan({
  id: "loan-3",
  member: maya,
  copy: { id: "copy-9", code: "CP-0009" },
  book: { id: "book-3", title: "Middlemarch", author: "George Eliot" },
  borrowed_at: "2026-07-01T10:00:00Z",
  due_at: "2026-07-15T23:59:59Z",
  returned_at: "2026-07-12T15:00:00Z",
})

function renderMember(id = "member-1") {
  return renderWithProviders(
    <Routes>
      <Route path="/members" element={<MembersPage />} />
      <Route path="/members/:memberId" element={<MemberDetailPage />} />
    </Routes>,
    { route: `/members/${id}` },
  )
}

function rowOf(title: string) {
  return screen.getByRole("link", { name: title }).closest("tr") as HTMLElement
}

describe("MemberDetailPage", () => {
  it("shows the profile, the current loans with overdue marked, and the history", async () => {
    const fetchMock = stubApi({
      "GET /api/members/member-1": () =>
        memberDetail({ joined_on: "2024-03-02", loans_total: 14, active_loans: 2 }),
      "GET /api/loans": ({ search }) =>
        search.get("status") === "active"
          ? page([overdueLoan, currentLoan])
          : page([returnedLoan], { total: 12, limit: 10, offset: Number(search.get("offset") ?? 0) }),
    })
    const user = userEvent.setup()
    renderMember()

    expect(await screen.findByRole("heading", { level: 1, name: "Maya Hassan" })).toBeInTheDocument()
    expect(screen.getByText("maya@example.com")).toBeInTheDocument()
    expect(screen.getByText(formatCalendarDate("2024-03-02"))).toBeInTheDocument()
    expect(screen.getByText("Loans in total").nextElementSibling).toHaveTextContent("14")

    const current = screen.getByRole("region", { name: "Current loans" })
    await within(current).findByRole("link", { name: "Dune" })
    expect(rowOf("Dune")).toHaveTextContent("9 days overdue")
    expect(within(rowOf("Dune")).getByRole("button", { name: "Return CP-0001" })).toBeInTheDocument()
    expect(rowOf("Emma")).toHaveTextContent("On loan")
    expect(within(current).queryByRole("columnheader", { name: "Member" })).not.toBeInTheDocument()

    const history = screen.getByRole("region", { name: "History" })
    await within(history).findByRole("link", { name: "Middlemarch" })
    expect(rowOf("Middlemarch")).toHaveTextContent(`Returned ${formatDate("2026-07-12T15:00:00Z")}`)
    expect(within(rowOf("Middlemarch")).queryByRole("button")).not.toBeInTheDocument()
    expect(within(history).getByText("Showing 1–10 of 12 loans")).toBeInTheDocument()

    await user.click(within(history).getByRole("button", { name: "Next" }))

    expect(await within(history).findByText("Showing 11–12 of 12 loans")).toBeInTheDocument()
    const requests = requestsTo(fetchMock, "GET /api/loans").map(({ search }) => ({
      status: search.get("status"),
      member: search.get("member_id"),
      offset: search.get("offset"),
    }))
    expect(requests).toEqual([
      { status: "active", member: "member-1", offset: "0" },
      { status: "returned", member: "member-1", offset: "0" },
      { status: "returned", member: "member-1", offset: "10" },
    ])
  })

  it("returns a current loan after confirmation", async () => {
    let returned = false
    const fetchMock = stubApi({
      "GET /api/members/member-1": () => memberDetail({ loans_total: 1, active_loans: 1 }),
      "GET /api/loans": ({ search }) =>
        search.get("status") === "active" && !returned ? page([currentLoan]) : page([]),
      "POST /api/loans/loan-2/return": () => {
        returned = true
        return { ...currentLoan, returned_at: "2026-09-19T10:00:00Z" }
      },
    })
    const user = userEvent.setup()
    renderMember()

    await user.click(await screen.findByRole("button", { name: "Return CP-0005" }))
    const dialog = await screen.findByRole("alertdialog", { name: "Return this copy?" })
    await user.click(within(dialog).getByRole("button", { name: "Return copy" }))

    expect(await screen.findByRole("heading", { name: "Nothing on loan" })).toBeInTheDocument()
    expect(requestsTo(fetchMock, "POST /api/loans/loan-2/return")).toHaveLength(1)
    await waitFor(() => expect(requestsTo(fetchMock, "GET /api/members/member-1")).toHaveLength(2))
  })

  it("renews a current loan after confirmation, and says why another cannot be renewed", async () => {
    const fetchMock = stubApi({
      "GET /api/members/member-1": () => memberDetail({ loans_total: 2, active_loans: 2 }),
      "GET /api/loans": ({ search }) =>
        search.get("status") === "active"
          ? page([{ ...overdueLoan, can_renew: false }, currentLoan])
          : page([]),
      "POST /api/loans/loan-2/renew": () => ({ ...currentLoan, renewals: 1 }),
    })
    const user = userEvent.setup()
    renderMember()

    const current = await screen.findByRole("region", { name: "Current loans" })
    await within(current).findByRole("link", { name: "Dune" })
    expect(rowOf("Dune")).toHaveTextContent("Cannot renew: a member is waiting for this book")
    expect(within(rowOf("Dune")).queryByRole("button", { name: "Renew CP-0001" })).not.toBeInTheDocument()

    await user.click(within(rowOf("Emma")).getByRole("button", { name: "Renew CP-0005" }))
    const dialog = await screen.findByRole("alertdialog", { name: "Renew this loan?" })
    expect(dialog).toHaveTextContent("Emma (CP-0005), borrowed by Maya Hassan")
    await user.click(within(dialog).getByRole("button", { name: "Renew" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
    expect(requestsTo(fetchMock, "POST /api/loans/loan-2/renew")).toHaveLength(1)
  })

  it("shows a not-found state for a member that does not exist", async () => {
    stubApi({
      "GET /api/members/missing": () => errorResponse(404, "not_found", "The member was not found."),
    })

    renderMember("missing")

    expect(await screen.findByRole("heading", { level: 1, name: "Member not found" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Go to the members" })).toHaveAttribute("href", "/members")
  })

  it("shows the same not-found state for a malformed id, which the API refuses with 422", async () => {
    stubApi({
      "GET /api/members/not-an-id": () =>
        errorResponse(422, "validation_failed", "The request is not valid.", {
          errors: [{ location: ["path", "member_id"], message: "Input should be a valid UUID", type: "uuid_parsing" }],
        }),
    })

    renderMember("not-an-id")

    expect(await screen.findByRole("heading", { level: 1, name: "Member not found" })).toBeInTheDocument()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("is where a member's row in the list leads", async () => {
    stubApi({
      "GET /api/members": () => page([member({ active_loans: 1 })]),
      "GET /api/members/member-1": () => memberDetail(),
      "GET /api/loans": () => page([]),
    })
    const user = userEvent.setup()
    renderWithProviders(
      <Routes>
        <Route path="/members" element={<MembersPage />} />
        <Route path="/members/:memberId" element={<MemberDetailPage />} />
      </Routes>,
      { route: "/members" },
    )

    const link = await screen.findByRole("link", { name: "Maya Hassan" })
    expect(link).toHaveAttribute("href", "/members/member-1")
    await user.click(within(link.closest("tr") as HTMLElement).getByText("maya@example.com", { selector: "td" }))

    expect(await screen.findByRole("heading", { level: 1, name: "Maya Hassan" })).toBeInTheDocument()
  })
})
