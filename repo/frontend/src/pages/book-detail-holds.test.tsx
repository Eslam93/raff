import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router"
import { toast } from "sonner"
import { describe, expect, it, vi } from "vitest"

import { addDays, todayDateValue } from "@/lib/dates"
import { formatDueDate, formatPickupDate } from "@/lib/format"
import type { CopyOut, HoldOut, UserOut } from "@/lib/types"
import { BookDetailPage } from "@/pages/book-detail-page"
import { errorResponse, requestsTo, stubApi } from "@/test/api-stub"
import {
  availableCopy,
  bookDetail,
  borrowedCopy,
  copyOnLoan,
  heldCopy,
  hold,
  loan,
  member,
  memberUser,
  page,
  readyHold,
  staffUser,
} from "@/test/fixtures"
import { jsonResponse, renderWithProviders } from "@/test/render"

const PICKUP_BY = "2026-10-19T23:59:59Z"
const LATER = "2099-01-15T23:59:59Z"

/** Staff pages ask for the loan history and the holds; both answer empty unless a test gives its own. */
function stubBookApi(routes: Parameters<typeof stubApi>[0]) {
  return stubApi({ "GET /api/loans": () => page([]), "GET /api/holds": () => page([]), ...routes })
}

function renderBook(user: UserOut = staffUser()) {
  return renderWithProviders(
    <Routes>
      <Route path="/books/:bookId" element={<BookDetailPage />} />
    </Routes>,
    { route: "/books/book-1", user },
  )
}

/** A held copy as a member sees it: set aside, but not for whom. */
function heldCopyForMember(id: string, code: string): CopyOut {
  return { id, code, status: "held", due_at: null, active_loan: null, held_for: null }
}

function copyRow(code: string) {
  return screen.getByRole("cell", { name: code }).closest("tr") as HTMLElement
}

describe("BookDetailPage: a member's hold", () => {
  it("offers Place hold when no copy is on the shelf, then shows the member's place in line", async () => {
    const success = vi.spyOn(toast, "success")
    let myHold: HoldOut | null = null
    const fetchMock = stubBookApi({
      "GET /api/books/book-1": () =>
        bookDetail({ copies: [copyOnLoan("copy-1", "CP-0001", LATER)], my_hold: myHold }),
      "GET /api/me/loans": () => page([]),
      "POST /api/me/holds": () => {
        myHold = hold({ position: 2 })
        return jsonResponse(myHold, 201)
      },
    })
    const user = userEvent.setup()
    renderBook(memberUser())

    expect(
      await screen.findByText("No copy is on the shelf now. Place a hold to get the next copy that comes back."),
    ).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Place hold" }))

    expect(await screen.findByText("You are number 2 in line.")).toBeInTheDocument()
    expect(await screen.findByRole("button", { name: "Cancel hold" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Place hold" })).not.toBeInTheDocument()
    expect(requestsTo(fetchMock, "POST /api/me/holds")[0].body).toEqual({ book_id: "book-1" })
    expect(success).toHaveBeenCalledWith("You are number 2 in line for Dune")
    // A member never asks for the staff list of holds.
    expect(requestsTo(fetchMock, "GET /api/holds")).toHaveLength(0)
  })

  it("shows the API's reason when the hold is refused", async () => {
    stubBookApi({
      "GET /api/books/book-1": () => bookDetail({ copies: [copyOnLoan("copy-1", "CP-0001", LATER)] }),
      "GET /api/me/loans": () => page([]),
      "POST /api/me/holds": () =>
        errorResponse(409, "hold_limit_reached", "Demo Member already has 5 open holds, the most allowed."),
    })
    const user = userEvent.setup()
    renderBook(memberUser())

    await user.click(await screen.findByRole("button", { name: "Place hold" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Demo Member already has 5 open holds, the most allowed.",
    )
  })

  it("offers no hold while a copy is on the shelf, without asking for the member's loans", async () => {
    const fetchMock = stubBookApi({ "GET /api/books/book-1": () => bookDetail() })

    renderBook(memberUser())

    expect(await screen.findByRole("heading", { level: 1, name: "Dune" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Place hold" })).not.toBeInTheDocument()
    expect(requestsTo(fetchMock, "GET /api/me/loans")).toHaveLength(0)
  })

  it("offers no hold on a book the member has on loan, and says so", async () => {
    stubBookApi({
      "GET /api/books/book-1": () => bookDetail({ copies: [copyOnLoan("copy-1", "CP-0001", LATER)] }),
      "GET /api/me/loans": () =>
        page([loan({ book: { id: "book-1", title: "Dune", author: "Frank Herbert" }, due_at: LATER })]),
    })

    renderBook(memberUser())

    expect(
      await screen.findByText(`You have this book on loan, due back ${formatDueDate(LATER)}.`),
    ).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Place hold" })).not.toBeInTheDocument()
  })

  it("tells a member a copy is waiting for them, with the pick-up date and the copy", async () => {
    stubBookApi({
      "GET /api/books/book-1": () =>
        bookDetail({
          copies: [heldCopyForMember("copy-12", "CP-0012"), copyOnLoan("copy-1", "CP-0001", LATER)],
          my_hold: readyHold(),
        }),
    })

    renderBook(memberUser())

    expect(
      await screen.findByText(`A copy is waiting for you: pick it up by ${formatPickupDate(PICKUP_BY)}.`),
    ).toBeInTheDocument()
    expect(screen.getByText(/Ask at the desk for copy/)).toHaveTextContent("CP-0012")
    expect(within(copyRow("CP-0012")).getByText("Held")).toBeInTheDocument()
    expect(within(copyRow("CP-0012")).getByText("Set aside for you")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Cancel hold" })).toBeInTheDocument()
  })

  it("cancels the member's own hold after they confirm", async () => {
    const success = vi.spyOn(toast, "success")
    const fetchMock = stubBookApi({
      "GET /api/books/book-1": () =>
        bookDetail({ copies: [copyOnLoan("copy-1", "CP-0001", LATER)], my_hold: hold({ position: 3 }) }),
      "GET /api/me/loans": () => page([]),
      "POST /api/me/holds/hold-1/cancel": () => hold({ status: "cancelled", position: null }),
    })
    const user = userEvent.setup()
    renderBook(memberUser())

    expect(await screen.findByText("You are number 3 in line.")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "Cancel hold" }))

    const dialog = await screen.findByRole("alertdialog", { name: "Cancel your hold?" })
    expect(dialog).toHaveTextContent("You are number 3 in line for Dune. Cancelling takes you out of the line.")
    await user.click(within(dialog).getByRole("button", { name: "Cancel hold" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
    expect(requestsTo(fetchMock, "POST /api/me/holds/hold-1/cancel")).toHaveLength(1)
    expect(success).toHaveBeenCalledWith("Cancelled your hold on Dune")
  })
})

describe("BookDetailPage: holds for staff", () => {
  const omarWaiting = hold({ id: "hold-2", member: { id: "member-2", full_name: "Omar Nasser" }, position: 1 })
  const heldBook = () =>
    bookDetail({
      copies: [heldCopy("copy-12", "CP-0012"), borrowedCopy("copy-1", "CP-0001")],
      holds_waiting: 1,
    })

  it("lists the open holds with places in line, the copy set aside and its pick-up date", async () => {
    const fetchMock = stubBookApi({
      "GET /api/books/book-1": heldBook,
      "GET /api/holds": () => page([readyHold(), omarWaiting]),
    })

    renderBook()

    const holds = await screen.findByRole("region", { name: "Holds" })
    await within(holds).findByRole("link", { name: "Omar Nasser" })
    const row = (name: string) => within(holds).getByRole("link", { name }).closest("tr") as HTMLElement
    expect(row("Maya Hassan")).toHaveTextContent("Ready for pick-up")
    expect(row("Maya Hassan")).toHaveTextContent("CP-0012")
    expect(row("Maya Hassan")).toHaveTextContent(formatPickupDate(PICKUP_BY))
    expect(row("Omar Nasser")).toHaveTextContent("Waiting")
    expect(within(row("Omar Nasser")).getByRole("cell", { name: "1" })).toBeInTheDocument()
    expect(
      within(row("Omar Nasser")).queryByRole("button", { name: /^Borrow/ }),
    ).not.toBeInTheDocument()
    expect(within(holds).getByText("2 holds")).toBeInTheDocument()

    const [request] = requestsTo(fetchMock, "GET /api/holds")
    expect(Object.fromEntries(request.search)).toEqual({
      status: "open",
      book_id: "book-1",
      limit: "10",
      offset: "0",
    })
  })

  it("shows a held copy's member and date in the copies, and the counts that leave it out", async () => {
    stubBookApi({ "GET /api/books/book-1": heldBook })

    renderBook()

    expect(await screen.findByRole("heading", { level: 1, name: "Dune" })).toBeInTheDocument()
    expect(within(copyRow("CP-0012")).getByText("Held")).toBeInTheDocument()
    expect(copyRow("CP-0012")).toHaveTextContent(`Held for Maya Hassan until ${formatPickupDate(PICKUP_BY)}`)
    expect(screen.getByText(/in total/)).toHaveTextContent(
      "2 copies in total, 0 available, 1 on loan, 1 set aside for a hold.",
    )
    expect(screen.getByText("1 member is waiting in line.")).toBeInTheDocument()
    const borrow = screen.getByRole("button", { name: "Borrow" })
    expect(borrow).toBeDisabled()
    expect(borrow).toHaveAccessibleDescription("Every copy is on loan or set aside for a hold.")
  })

  it("lends a held copy to the member it waits for, from the holds or the copies", async () => {
    const success = vi.spyOn(toast, "success")
    const dueDate = addDays(todayDateValue(), 14)
    const fetchMock = stubBookApi({
      "GET /api/books/book-1": heldBook,
      "GET /api/holds": () => page([readyHold()]),
      "POST /api/loans": () =>
        jsonResponse(
          loan({
            copy: { id: "copy-12", code: "CP-0012" },
            member: { id: "member-1", full_name: "Maya Hassan" },
            due_at: `${dueDate}T23:59:59Z`,
          }),
          201,
        ),
    })
    const user = userEvent.setup()
    renderBook()

    const holds = await screen.findByRole("region", { name: "Holds" })
    await user.click(await within(holds).findByRole("button", { name: "Borrow CP-0012 to Maya Hassan" }))

    const dialog = await screen.findByRole("dialog", { name: "Borrow Dune to Maya Hassan" })
    expect(dialog).toHaveTextContent(`CP-0012 is set aside for Maya Hassan until ${formatPickupDate(PICKUP_BY)}`)
    expect(within(dialog).getByLabelText("Due date")).toHaveValue(dueDate)
    await user.click(within(dialog).getByRole("button", { name: "Borrow" }))

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(requestsTo(fetchMock, "POST /api/loans")[0].body).toEqual({
      copy_id: "copy-12",
      member_id: "member-1",
      due_date: dueDate,
    })
    expect(success).toHaveBeenCalledWith(
      `Borrowed Dune (CP-0012) to Maya Hassan, due ${formatDueDate(`${dueDate}T23:59:59Z`)}`,
    )

    // The copies table offers the same for the held copy.
    await user.click(within(copyRow("CP-0012")).getByRole("button", { name: "Borrow CP-0012 to Maya Hassan" }))
    expect(await screen.findByRole("dialog", { name: "Borrow Dune to Maya Hassan" })).toBeInTheDocument()
  })

  it("says the copy went elsewhere when the hold closed before the loan", async () => {
    stubBookApi({
      "GET /api/books/book-1": heldBook,
      "POST /api/loans": () =>
        errorResponse(409, "copy_held", "Copy CP-0012 is held for Omar Nasser until 22 Oct."),
    })
    const user = userEvent.setup()
    renderBook()

    await user.click(await screen.findByRole("button", { name: "Borrow CP-0012 to Maya Hassan" }))
    const dialog = await screen.findByRole("dialog", { name: "Borrow Dune to Maya Hassan" })
    await user.click(within(dialog).getByRole("button", { name: "Borrow" }))

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Copy CP-0012 is held for Omar Nasser until 22 Oct. The page is now up to date.",
    )
  })

  it("places a hold for a member chosen with the member picker", async () => {
    const success = vi.spyOn(toast, "success")
    const omar = member({ id: "member-2", full_name: "Omar Nasser", email: "omar@example.com" })
    const fetchMock = stubBookApi({
      "GET /api/books/book-1": () => bookDetail({ copies: [borrowedCopy("copy-1", "CP-0001")] }),
      "GET /api/members": ({ search }) =>
        page([member(), omar].filter((m) => m.full_name.toLowerCase().includes(search.get("q") ?? ""))),
      "POST /api/holds": () =>
        jsonResponse(hold({ member: { id: "member-2", full_name: "Omar Nasser" }, position: 2 }), 201),
    })
    const user = userEvent.setup()
    renderBook()

    const holds = await screen.findByRole("region", { name: "Holds" })
    await user.click(within(holds).getByRole("button", { name: "Place hold for a member" }))
    const dialog = await screen.findByRole("dialog", { name: "Place a hold on Dune" })
    await user.type(within(dialog).getByRole("combobox", { name: "Member" }), "omar")
    await waitFor(() =>
      expect(within(dialog).getAllByRole("option").map((option) => option.textContent)).toEqual([
        expect.stringContaining("Omar Nasser"),
      ]),
    )
    await user.keyboard("{Enter}")
    await user.click(within(dialog).getByRole("button", { name: "Place hold" }))

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(requestsTo(fetchMock, "POST /api/holds")[0].body).toEqual({
      book_id: "book-1",
      member_id: "member-2",
    })
    expect(success).toHaveBeenCalledWith("Placed a hold on Dune for Omar Nasser, number 2 in line")
  })

  it("shows a refusal about the member on the member field", async () => {
    stubBookApi({
      "GET /api/books/book-1": () => bookDetail({ copies: [borrowedCopy("copy-1", "CP-0001")] }),
      "GET /api/members": () => page([member()]),
      "POST /api/holds": () => errorResponse(409, "hold_exists", "Maya Hassan already has a hold on Dune."),
    })
    const user = userEvent.setup()
    renderBook()

    await user.click(await screen.findByRole("button", { name: "Place hold for a member" }))
    const dialog = await screen.findByRole("dialog", { name: "Place a hold on Dune" })
    await within(dialog).findByRole("option", { name: /Maya Hassan/ })
    await user.click(within(dialog).getByRole("combobox", { name: "Member" }))
    await user.keyboard("{Enter}")
    await user.click(within(dialog).getByRole("button", { name: "Place hold" }))

    expect(await within(dialog).findByText("Maya Hassan already has a hold on Dune.")).toBeInTheDocument()
    expect(screen.getByRole("dialog", { name: "Place a hold on Dune" })).toBeInTheDocument()
  })

  it("does not offer a hold while a copy is on the shelf, and says why", async () => {
    stubBookApi({ "GET /api/books/book-1": () => bookDetail() })

    renderBook()

    const place = await screen.findByRole("button", { name: "Place hold for a member" })
    expect(place).toBeDisabled()
    expect(place).toHaveAccessibleDescription("A copy is on the shelf: borrow it instead of placing a hold.")
  })

  it("cancels a member's hold after staff confirm", async () => {
    const success = vi.spyOn(toast, "success")
    const fetchMock = stubBookApi({
      "GET /api/books/book-1": heldBook,
      "GET /api/holds": () => page([omarWaiting]),
      "POST /api/holds/hold-2/cancel": () => ({ ...omarWaiting, status: "cancelled", position: null }),
    })
    const user = userEvent.setup()
    renderBook()

    await user.click(await screen.findByRole("button", { name: "Cancel the hold of Omar Nasser" }))
    const dialog = await screen.findByRole("alertdialog", { name: "Cancel this hold?" })
    expect(dialog).toHaveTextContent("Omar Nasser is number 1 in line for Dune. Cancelling takes them out of the line.")
    await user.click(within(dialog).getByRole("button", { name: "Cancel hold" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
    expect(requestsTo(fetchMock, "POST /api/holds/hold-2/cancel")).toHaveLength(1)
    expect(success).toHaveBeenCalledWith("Cancelled the hold of Omar Nasser on Dune")
  })

  it("says so when nobody is waiting, and when the holds cannot load", async () => {
    stubBookApi({ "GET /api/books/book-1": () => bookDetail() })
    const { unmount } = renderBook()

    const holds = await screen.findByRole("region", { name: "Holds" })
    expect(await within(holds).findByRole("heading", { name: "Nobody is waiting" })).toBeInTheDocument()
    unmount()

    stubBookApi({
      "GET /api/books/book-1": () => bookDetail(),
      "GET /api/holds": () => errorResponse(500, "internal_error", "The server failed."),
    })
    renderBook()

    const failed = await screen.findByRole("region", { name: "Holds" })
    expect(await within(failed).findByRole("alert")).toHaveTextContent("Could not load the holds")
  })

  it("shows no holds for an archived book and does not ask for them", async () => {
    const fetchMock = stubBookApi({
      "GET /api/books/book-1": () => bookDetail({ archived: true, copies: [availableCopy("copy-1", "CP-0001")] }),
    })

    renderBook()

    expect(await screen.findByText("This book is archived")).toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "Holds" })).not.toBeInTheDocument()
    expect(requestsTo(fetchMock, "GET /api/holds")).toHaveLength(0)
  })
})
