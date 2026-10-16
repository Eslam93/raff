import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router"
import { describe, expect, it } from "vitest"

import { formatDate, formatDueDate } from "@/lib/format"
import type { UserOut } from "@/lib/types"
import { BookDetailPage } from "@/pages/book-detail-page"
import { errorResponse, requestsTo, stubApi } from "@/test/api-stub"
import {
  availableCopy,
  bookDetail,
  borrowedCopy,
  copyOnLoan,
  loan,
  member,
  memberUser,
  page,
  staffUser,
} from "@/test/fixtures"
import { renderWithProviders } from "@/test/render"

/**
 * Staff see the book's loan history and holds, so those requests always get an
 * answer: an empty history and nobody waiting unless a test gives its own.
 */
function stubBookApi(routes: Parameters<typeof stubApi>[0]) {
  return stubApi({ "GET /api/loans": () => page([]), "GET /api/holds": () => page([]), ...routes })
}

function renderBook(id = "book-1", user: UserOut = staffUser()) {
  return renderWithProviders(
    <Routes>
      <Route path="/books/:bookId" element={<BookDetailPage />} />
    </Routes>,
    { route: `/books/${id}`, user },
  )
}

describe("BookDetailPage", () => {
  it("shows each copy with its state and the loan of a borrowed copy", async () => {
    stubBookApi({
      "GET /api/books/book-1": () =>
        bookDetail({
          copies: [
            availableCopy("copy-1", "CP-0001"),
            borrowedCopy("copy-2", "CP-0002"),
            borrowedCopy("copy-3", "CP-0003", true),
          ],
        }),
    })

    renderBook()

    expect(await screen.findByRole("heading", { level: 1, name: "Dune" })).toBeInTheDocument()
    const row = (code: string) => screen.getByRole("cell", { name: code }).closest("tr") as HTMLElement
    expect(within(row("CP-0001")).getByText("Available")).toBeInTheDocument()
    expect(within(row("CP-0001")).getByRole("button", { name: "Borrow CP-0001" })).toBeInTheDocument()
    expect(within(row("CP-0002")).getByText("Borrowed")).toBeInTheDocument()
    expect(within(row("CP-0002")).getByText("Lina Farah")).toBeInTheDocument()
    expect(within(row("CP-0002")).getByRole("button", { name: "Return CP-0002" })).toBeInTheDocument()
    expect(within(row("CP-0003")).getByText("Overdue")).toBeInTheDocument()
    expect(screen.getByText("1 of 3 available")).toBeInTheDocument()
  })

  it("opens Borrow with the first available copy selected", async () => {
    stubBookApi({
      "GET /api/books/book-1": () => bookDetail(),
      "GET /api/members": () => page([member()]),
    })
    const user = userEvent.setup()
    renderBook()

    await user.click(await screen.findByRole("button", { name: "Borrow" }))

    const dialog = await screen.findByRole("dialog", { name: "Borrow Dune" })
    expect(within(dialog).getByRole("combobox", { name: "Copy" })).toHaveValue("copy-2")
  })

  it("disables Borrow and says why when every copy is on loan", async () => {
    stubBookApi({
      "GET /api/books/book-1": () => bookDetail({ copies: [borrowedCopy("copy-1", "CP-0001")] }),
    })

    renderBook()

    const borrow = await screen.findByRole("button", { name: "Borrow" })
    expect(borrow).toBeDisabled()
    expect(borrow).toHaveAccessibleDescription("Every copy is on loan. Return one to lend it again.")
  })

  it("shows an archived book with a banner and no actions", async () => {
    stubBookApi({ "GET /api/books/book-1": () => bookDetail({ archived: true }) })

    renderBook()

    expect(await screen.findByText("This book is archived")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Borrow|Return|Edit|Delete|Add copy/ })).not.toBeInTheDocument()
  })

  it("shows a not-found state for a book that does not exist", async () => {
    stubBookApi({
      "GET /api/books/missing": () => errorResponse(404, "not_found", "The book was not found."),
    })

    renderBook("missing")

    expect(await screen.findByRole("heading", { level: 1, name: "Book not found" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Go to the catalog" })).toHaveAttribute("href", "/catalog")
  })

  it("shows the same not-found state for a malformed id, which the API refuses with 422", async () => {
    stubBookApi({
      "GET /api/books/not-an-id": () =>
        errorResponse(422, "validation_failed", "The request is not valid.", {
          errors: [{ location: ["path", "book_id"], message: "Input should be a valid UUID", type: "uuid_parsing" }],
        }),
    })

    renderBook("not-an-id")

    expect(await screen.findByRole("heading", { level: 1, name: "Book not found" })).toBeInTheDocument()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("shows a member the copies with their due-back dates, without staff actions or borrowers", async () => {
    const later = "2099-01-15T23:59:59Z"
    const past = "2026-09-01T23:59:59Z"
    stubBookApi({
      "GET /api/books/book-1": () =>
        bookDetail({
          copies: [
            availableCopy("copy-1", "CP-0001"),
            copyOnLoan("copy-2", "CP-0002", later),
            copyOnLoan("copy-3", "CP-0003", past),
          ],
        }),
    })

    renderBook("book-1", memberUser())

    expect(await screen.findByRole("heading", { level: 1, name: "Dune" })).toBeInTheDocument()
    const row = (code: string) => screen.getByRole("cell", { name: code }).closest("tr") as HTMLElement
    expect(within(row("CP-0001")).getByText("Available")).toBeInTheDocument()
    expect(within(row("CP-0002")).getByText("Borrowed")).toBeInTheDocument()
    expect(within(row("CP-0002")).getByText(`Due back ${formatDueDate(later)}`)).toBeInTheDocument()
    expect(within(row("CP-0003")).getByText("Overdue")).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "Borrower" })).not.toBeInTheDocument()
    expect(
      screen.queryByRole("button", { name: /Borrow|Return|Edit|Delete|Add copy/ }),
    ).not.toBeInTheDocument()
  })

  it("shows staff the book's loan history, newest first and paged", async () => {
    const fetchMock = stubBookApi({
      "GET /api/books/book-1": () => bookDetail(),
      "GET /api/loans": ({ search }) =>
        page(
          [
            loan({ id: "loan-3", member: { id: "member-3", full_name: "Lina Farah" } }),
            loan({
              id: "loan-2",
              member: { id: "member-2", full_name: "Omar Nasser" },
              due_at: "2026-09-10T23:59:59Z",
              is_overdue: true,
              days_overdue: 9,
            }),
            loan({
              id: "loan-1",
              member: { id: "member-1", full_name: "Maya Hassan" },
              borrowed_at: "2026-06-01T10:00:00Z",
              due_at: "2026-06-15T23:59:59Z",
              returned_at: "2026-06-12T15:00:00Z",
            }),
          ],
          { total: 23, limit: 10, offset: Number(search.get("offset") ?? 0) },
        ),
    })
    const user = userEvent.setup()
    renderBook()

    const history = await screen.findByRole("region", { name: "Loan history" })
    const row = (name: string) =>
      within(history).getByRole("link", { name }).closest("tr") as HTMLElement
    await within(history).findByRole("link", { name: "Lina Farah" })
    expect(row("Lina Farah")).toHaveTextContent("On loan")
    expect(row("Omar Nasser")).toHaveTextContent("9 days overdue")
    expect(row("Maya Hassan")).toHaveTextContent(`Returned ${formatDate("2026-06-12T15:00:00Z")}`)
    expect(row("Maya Hassan")).toHaveTextContent(formatDate("2026-06-01T10:00:00Z"))
    expect(row("Maya Hassan")).toHaveTextContent(formatDueDate("2026-06-15T23:59:59Z"))
    expect(within(history).getByRole("link", { name: "Maya Hassan" })).toHaveAttribute(
      "href",
      "/members/member-1",
    )
    expect(within(history).queryByRole("columnheader", { name: "Book" })).not.toBeInTheDocument()
    expect(within(history).queryByRole("button", { name: /Return/ })).not.toBeInTheDocument()

    await user.click(within(history).getByRole("button", { name: "Next" }))

    expect(await within(history).findByText("Showing 11–20 of 23 loans")).toBeInTheDocument()
    const requests = requestsTo(fetchMock, "GET /api/loans").map(({ search }) => ({
      status: search.get("status"),
      book: search.get("book_id"),
      offset: search.get("offset"),
    }))
    expect(requests).toEqual([
      { status: "all", book: "book-1", offset: "0" },
      { status: "all", book: "book-1", offset: "10" },
    ])
  })

  it("never shows members the loan history or asks for it", async () => {
    const fetchMock = stubBookApi({ "GET /api/books/book-1": () => bookDetail() })

    renderBook("book-1", memberUser())

    expect(await screen.findByRole("heading", { level: 1, name: "Dune" })).toBeInTheDocument()
    expect(screen.queryByRole("heading", { name: "Loan history" })).not.toBeInTheDocument()
    expect(requestsTo(fetchMock, "GET /api/loans")).toHaveLength(0)
  })
})
