import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router"
import { describe, expect, it } from "vitest"

import { CirculationPage } from "@/pages/circulation-page"
import { errorResponse, requestsTo, stubApi } from "@/test/api-stub"
import { bookDetail, bookSummary, copyLookup, loan, member, page } from "@/test/fixtures"
import { renderWithProviders } from "@/test/render"

const onLoan = loan({
  id: "loan-7",
  copy: { id: "copy-12", code: "CP-0012" },
  member: { id: "member-1", full_name: "Maya Hassan" },
  due_at: "2026-09-16T23:59:59Z",
  is_overdue: true,
  days_overdue: 3,
})

/**
 * The page also lists the copies waiting for pick-up, so that request always
 * gets an answer: none waiting, unless a test gives its own.
 */
function stubDeskApi(routes: Parameters<typeof stubApi>[0]) {
  return stubApi({ "GET /api/holds": () => page([]), ...routes })
}

function renderCirculation(route = "/circulation") {
  return renderWithProviders(
    <Routes>
      <Route path="/circulation" element={<CirculationPage />} />
    </Routes>,
    { route },
  )
}

function codeBox() {
  return screen.getByRole("textbox", { name: "Copy code" })
}

function currentLocation() {
  return screen.getByTestId("location").textContent
}

describe("CirculationPage: the copy-code box", () => {
  it("is ready for a scan, reads cp-12 as CP-0012, and returns the copy on loan", async () => {
    const fetchMock = stubDeskApi({
      "GET /api/loans": () => page([]),
      "GET /api/copies/by-code/CP-0012": () => copyLookup({ active_loan: onLoan }),
      "POST /api/loans/loan-7/return": () => ({ ...onLoan, returned_at: "2026-09-19T10:00:00Z" }),
    })
    const user = userEvent.setup()
    renderCirculation()

    expect(codeBox()).toHaveFocus()
    await user.keyboard("cp-12{Enter}")

    const found = await screen.findByRole("group", { name: "Copy CP-0012" })
    expect(requestsTo(fetchMock, "GET /api/copies/by-code/CP-0012")).toHaveLength(1)
    expect(within(found).getByRole("link", { name: "Dune" })).toHaveAttribute("href", "/books/book-1")
    expect(within(found).getByRole("link", { name: "Maya Hassan" })).toHaveAttribute(
      "href",
      "/members/member-1",
    )
    expect(within(found).getByText("3 days overdue")).toBeInTheDocument()
    expect(within(found).queryByRole("button", { name: "Borrow" })).not.toBeInTheDocument()
    // The box keeps focus, so the next scan can follow at once.
    expect(codeBox()).toHaveFocus()

    await user.click(within(found).getByRole("button", { name: "Return copy" }))

    await waitFor(() =>
      expect(screen.queryByRole("group", { name: "Copy CP-0012" })).not.toBeInTheDocument(),
    )
    expect(requestsTo(fetchMock, "POST /api/loans/loan-7/return")).toHaveLength(1)
    expect(codeBox()).toHaveValue("")
    expect(codeBox()).toHaveFocus()
  })

  it("offers Borrow for an available copy and opens the borrow dialog with that copy chosen", async () => {
    const fetchMock = stubDeskApi({
      "GET /api/loans": () => page([]),
      "GET /api/copies/by-code/CP-0003": () =>
        copyLookup({ copy: { id: "copy-3", code: "CP-0003" } }),
      "GET /api/books/book-1": () => bookDetail(),
      "GET /api/members": () => page([member()]),
    })
    const user = userEvent.setup()
    renderCirculation()

    await user.type(codeBox(), "3{Enter}")

    const found = await screen.findByRole("group", { name: "Copy CP-0003" })
    expect(requestsTo(fetchMock, "GET /api/copies/by-code/CP-0003")).toHaveLength(1)
    expect(within(found).getByText("Available")).toBeInTheDocument()
    expect(within(found).queryByRole("button", { name: "Return copy" })).not.toBeInTheDocument()

    await user.click(within(found).getByRole("button", { name: "Borrow" }))

    const dialog = await screen.findByRole("dialog", { name: "Borrow Dune" })
    expect(within(dialog).getByRole("combobox", { name: "Copy" })).toHaveValue("copy-3")
  })

  it("says so when no copy has the code", async () => {
    stubDeskApi({
      "GET /api/loans": () => page([]),
      "GET /api/copies/by-code/CP-0099": () =>
        errorResponse(404, "not_found", "The copy was not found."),
    })
    const user = userEvent.setup()
    renderCirculation()

    await user.type(codeBox(), "CP-0099{Enter}")

    expect(await screen.findByRole("alert")).toHaveTextContent("No copy has the code CP-0099")
    expect(codeBox()).toHaveFocus()
  })

  it("explains text that is not a copy code without asking the API", async () => {
    const fetchMock = stubDeskApi({ "GET /api/loans": () => page([]) })
    const user = userEvent.setup()
    renderCirculation()

    await user.type(codeBox(), "dune{Enter}")

    expect(await screen.findByRole("alert")).toHaveTextContent('"dune" is not a copy code')
    const lookups = fetchMock.mock.calls.filter(([input]) => String(input).includes("/by-code/"))
    expect(lookups).toHaveLength(0)
  })
})

describe("CirculationPage: the loans list", () => {
  it("asks for the status of the chosen tab and keeps it in the URL", async () => {
    const fetchMock = stubDeskApi({ "GET /api/loans": () => page([onLoan]) })
    const user = userEvent.setup()
    renderCirculation()

    expect(await screen.findByRole("link", { name: "Dune" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Active" })).toHaveAttribute("aria-selected", "true")

    await user.click(screen.getByRole("tab", { name: "Overdue" }))
    await waitFor(() => expect(currentLocation()).toBe("/circulation?status=overdue"))
    await user.click(screen.getByRole("tab", { name: "Returned" }))
    await user.click(screen.getByRole("tab", { name: "All" }))

    await waitFor(() => expect(currentLocation()).toBe("/circulation?status=all"))
    await waitFor(() =>
      expect(requestsTo(fetchMock, "GET /api/loans").map(({ search }) => search.get("status"))).toEqual([
        "active",
        "overdue",
        "returned",
        "all",
      ]),
    )
  })

  it("opens on the tab and search in the URL, and searches by book, member or copy code", async () => {
    const fetchMock = stubDeskApi({
      "GET /api/loans": ({ search }) => (search.get("q") === "zzz" ? page([]) : page([onLoan])),
    })
    const user = userEvent.setup()
    renderCirculation("/circulation?status=returned&q=zzz")

    expect(await screen.findByRole("heading", { name: 'No loans match "zzz"' })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Returned" })).toHaveAttribute("aria-selected", "true")
    const [first] = requestsTo(fetchMock, "GET /api/loans")
    expect(first.search.get("status")).toBe("returned")
    expect(first.search.get("q")).toBe("zzz")

    await user.click(screen.getByRole("button", { name: "Clear search" }))
    await user.type(screen.getByRole("searchbox", { name: "Search loans" }), "maya")

    await waitFor(() => expect(currentLocation()).toBe("/circulation?status=returned&q=maya"))
    expect(await screen.findByRole("link", { name: "Dune" })).toBeInTheDocument()
  })

  it("returns a loan from its row and puts focus back in the copy-code box", async () => {
    const fetchMock = stubDeskApi({
      "GET /api/loans": () => page([onLoan]),
      "POST /api/loans/loan-7/return": () => ({ ...onLoan, returned_at: "2026-09-19T10:00:00Z" }),
    })
    const user = userEvent.setup()
    renderCirculation()

    await user.click(await screen.findByRole("button", { name: "Return CP-0012" }))
    const dialog = await screen.findByRole("alertdialog", { name: "Return this copy?" })
    await user.click(within(dialog).getByRole("button", { name: "Return copy" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
    expect(requestsTo(fetchMock, "POST /api/loans/loan-7/return")).toHaveLength(1)
    await waitFor(() => expect(codeBox()).toHaveFocus())
  })
})

describe("CirculationPage: borrow by book", () => {
  it("finds a book in the catalog and opens the borrow dialog for it", async () => {
    const fetchMock = stubDeskApi({
      "GET /api/loans": () => page([]),
      "GET /api/books": () =>
        page([
          bookSummary(),
          bookSummary({
            id: "book-2",
            title: "Dune Messiah",
            copies_total: 1,
            copies_available: 0,
            availability: "all_borrowed",
          }),
        ]),
      "GET /api/books/book-1": () => bookDetail(),
      "GET /api/members": () => page([member()]),
    })
    const user = userEvent.setup()
    renderCirculation()

    await user.click(screen.getByRole("button", { name: "Borrow by book" }))
    const finder = await screen.findByRole("dialog", { name: "Borrow by book" })
    await user.type(within(finder).getByRole("searchbox", { name: "Book" }), "dune")

    const results = await within(finder).findByRole("list", { name: "Books" })
    expect(within(results).getByRole("button", { name: "Borrow Dune Messiah" })).toBeDisabled()
    await user.click(within(results).getByRole("button", { name: "Borrow Dune" }))

    const dialog = await screen.findByRole("dialog", { name: "Borrow Dune" })
    expect(within(dialog).getByRole("combobox", { name: "Copy" })).toHaveValue("copy-2")
    expect(screen.queryByRole("dialog", { name: "Borrow by book" })).not.toBeInTheDocument()
    expect(requestsTo(fetchMock, "GET /api/books")[0].search.get("q")).toBe("dune")
  })
})
