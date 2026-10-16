import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router"
import { toast } from "sonner"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { addDays, todayDateValue } from "@/lib/dates"
import { formatDueDate, formatPickupDate } from "@/lib/format"
import type { CopyLookupOut } from "@/lib/types"
import { CirculationPage } from "@/pages/circulation-page"
import { errorResponse, requestsTo, stubApi } from "@/test/api-stub"
import { copyLookup, loan, page, readyHold } from "@/test/fixtures"
import { jsonResponse, renderWithProviders } from "@/test/render"

const PICKUP_BY = "2026-10-19T23:59:59Z"
const maya = { id: "member-1", full_name: "Maya Hassan" }

const heldLookup: CopyLookupOut = copyLookup({
  copy: { id: "copy-12", code: "CP-0012" },
  status: "held",
  held_for: { member: maya, pickup_by: PICKUP_BY },
})

const omarsLoan = loan({
  id: "loan-7",
  copy: { id: "copy-12", code: "CP-0012" },
  member: { id: "member-2", full_name: "Omar Nasser" },
  due_at: "2026-10-20T23:59:59Z",
})

function renderCirculation() {
  return renderWithProviders(
    <Routes>
      <Route path="/circulation" element={<CirculationPage />} />
    </Routes>,
    { route: "/circulation" },
  )
}

function codeBox() {
  return screen.getByRole("textbox", { name: "Copy code" })
}

describe("CirculationPage: waiting for pick-up", () => {
  it("lists the copies set aside, and lends one to its member", async () => {
    const success = vi.spyOn(toast, "success")
    const dueDate = addDays(todayDateValue(), 14)
    const fetchMock = stubApi({
      "GET /api/loans": () => page([]),
      "GET /api/holds": () => page([readyHold()]),
      "POST /api/loans": () =>
        jsonResponse(
          loan({ copy: { id: "copy-12", code: "CP-0012" }, member: maya, due_at: `${dueDate}T23:59:59Z` }),
          201,
        ),
    })
    const user = userEvent.setup()
    renderCirculation()

    const panel = await screen.findByRole("region", { name: "Waiting for pick-up" })
    const row = (await within(panel).findByRole("link", { name: "Dune" })).closest("tr") as HTMLElement
    // The member's name shows once per layout, narrow and wide; both link to the member.
    for (const link of within(row).getAllByRole("link", { name: "Maya Hassan" })) {
      expect(link).toHaveAttribute("href", "/members/member-1")
    }
    expect(row).toHaveTextContent("CP-0012")
    expect(row).toHaveTextContent(formatPickupDate(PICKUP_BY))
    const [request] = requestsTo(fetchMock, "GET /api/holds")
    expect(request.search.get("status")).toBe("ready")

    await user.click(within(row).getByRole("button", { name: "Borrow CP-0012 to Maya Hassan" }))
    const dialog = await screen.findByRole("dialog", { name: "Borrow Dune to Maya Hassan" })
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
    // Ready for the next scan.
    await waitFor(() => expect(codeBox()).toHaveFocus())
  })

  it("cancels a hold from the list after staff confirm", async () => {
    const fetchMock = stubApi({
      "GET /api/loans": () => page([]),
      "GET /api/holds": () => page([readyHold()]),
      "POST /api/holds/hold-1/cancel": () => readyHold({ status: "cancelled", closed_at: "2026-10-16T12:00:00Z" }),
    })
    const user = userEvent.setup()
    renderCirculation()

    await user.click(await screen.findByRole("button", { name: "Cancel the hold of Maya Hassan" }))
    const dialog = await screen.findByRole("alertdialog", { name: "Cancel this hold?" })
    expect(dialog).toHaveTextContent(
      `CP-0012 of Dune is set aside for Maya Hassan until ${formatPickupDate(PICKUP_BY)}. Cancelling gives the copy to the next member in line, or puts it back on the shelf.`,
    )
    await user.click(within(dialog).getByRole("button", { name: "Cancel hold" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
    expect(requestsTo(fetchMock, "POST /api/holds/hold-1/cancel")).toHaveLength(1)
  })

  it("says so when no copy is waiting, and when the list cannot load", async () => {
    stubApi({ "GET /api/loans": () => page([]), "GET /api/holds": () => page([]) })
    const { unmount } = renderCirculation()

    const panel = await screen.findByRole("region", { name: "Waiting for pick-up" })
    expect(
      await within(panel).findByRole("heading", { name: "No copies waiting for pick-up" }),
    ).toBeInTheDocument()
    unmount()

    stubApi({
      "GET /api/loans": () => page([]),
      "GET /api/holds": () => errorResponse(500, "internal_error", "The server failed."),
    })
    renderCirculation()

    const failed = await screen.findByRole("region", { name: "Waiting for pick-up" })
    expect(await within(failed).findByRole("alert")).toHaveTextContent(
      "Could not load the copies waiting for pick-up",
    )
  })
})

describe("CirculationPage: held copies at the desk", () => {
  it("shows who a scanned copy is held for and until when, and lends it to them", async () => {
    stubApi({
      "GET /api/loans": () => page([]),
      "GET /api/holds": () => page([]),
      "GET /api/copies/by-code/CP-0012": () => heldLookup,
    })
    const user = userEvent.setup()
    renderCirculation()

    await user.type(codeBox(), "12{Enter}")

    const found = await screen.findByRole("group", { name: "Copy CP-0012" })
    expect(within(found).getByText("Held for pick-up")).toBeInTheDocument()
    expect(within(found).getByRole("link", { name: "Maya Hassan" })).toHaveAttribute("href", "/members/member-1")
    expect(within(found).getByText(formatPickupDate(PICKUP_BY))).toBeInTheDocument()
    expect(within(found).queryByRole("button", { name: "Return copy" })).not.toBeInTheDocument()

    await user.click(within(found).getByRole("button", { name: "Borrow CP-0012 to Maya Hassan" }))

    expect(await screen.findByRole("dialog", { name: "Borrow Dune to Maya Hassan" })).toBeInTheDocument()
  })

  it("says plainly when a return set the copy aside for the next member in line", async () => {
    const success = vi.spyOn(toast, "success")
    let lookup: CopyLookupOut = copyLookup({ active_loan: omarsLoan })
    const fetchMock = stubApi({
      "GET /api/loans": () => page([]),
      "GET /api/holds": () => page([]),
      "GET /api/copies/by-code/CP-0012": () => lookup,
      "POST /api/loans/loan-7/return": () => {
        lookup = heldLookup
        return { ...omarsLoan, returned_at: "2026-10-16T10:00:00Z" }
      },
    })
    const user = userEvent.setup()
    renderCirculation()

    await user.type(codeBox(), "CP-0012{Enter}")
    const found = await screen.findByRole("group", { name: "Copy CP-0012" })
    await user.click(within(found).getByRole("button", { name: "Return copy" }))

    const notice = await screen.findByRole("status")
    expect(notice).toHaveTextContent("CP-0012 is held for Maya Hassan")
    expect(notice).toHaveTextContent(
      `The return set this copy aside for the first member waiting for Dune. Keep it at the desk for Maya Hassan until ${formatPickupDate(PICKUP_BY)}.`,
    )
    expect(success).toHaveBeenCalledWith(
      `Returned Dune (CP-0012) from Omar Nasser. It is set aside for Maya Hassan until ${formatPickupDate(PICKUP_BY)}.`,
    )
    expect(requestsTo(fetchMock, "POST /api/loans/loan-7/return")).toHaveLength(1)
    expect(codeBox()).toHaveValue("")
    expect(codeBox()).toHaveFocus()

    // The next scan replaces the notice.
    await user.type(codeBox(), "CP-0012{Enter}")
    await screen.findByRole("group", { name: "Copy CP-0012" })
    expect(screen.queryByText("CP-0012 is held for Maya Hassan")).not.toBeInTheDocument()
  })
})

describe("CirculationPage: renewing loans", () => {
  beforeEach(() => {
    // Midday UTC keeps "today" the same calendar date in every time zone.
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(new Date("2026-10-16T12:00:00Z"))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("renews a loan after staff confirm, showing the due date the renewal gives", async () => {
    const success = vi.spyOn(toast, "success")
    const fetchMock = stubApi({
      "GET /api/loans": () => page([omarsLoan]),
      "GET /api/holds": () => page([]),
      "POST /api/loans/loan-7/renew": () => ({ ...omarsLoan, due_at: "2026-11-03T23:59:59Z", renewals: 1 }),
    })
    const user = userEvent.setup()
    renderCirculation()

    await user.click(await screen.findByRole("button", { name: "Renew CP-0012" }))

    const dialog = await screen.findByRole("alertdialog", { name: "Renew this loan?" })
    // Due 20 Oct, renewed on 16 Oct: 14 days from the due date.
    expect(dialog).toHaveTextContent(
      `Dune (CP-0012), borrowed by Omar Nasser, is due ${formatDueDate("2026-10-20T23:59:59Z")}. Renewing moves the due date to ${formatDueDate("2026-11-03T23:59:59Z")}. This is renewal 1 of 2.`,
    )
    await user.click(within(dialog).getByRole("button", { name: "Renew" }))

    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
    expect(requestsTo(fetchMock, "POST /api/loans/loan-7/renew")).toHaveLength(1)
    expect(success).toHaveBeenCalledWith(
      `Renewed Dune (CP-0012) for Omar Nasser, now due ${formatDueDate("2026-11-03T23:59:59Z")}`,
    )
    await waitFor(() => expect(codeBox()).toHaveFocus())
  })

  it("shows how often a loan was renewed, and why one cannot be renewed", async () => {
    stubApi({
      "GET /api/loans": () =>
        page([
          loan({ id: "loan-1", copy: { id: "c1", code: "CP-0001" }, renewals: 1, can_renew: true }),
          loan({ id: "loan-2", copy: { id: "c2", code: "CP-0002" }, renewals: 2, can_renew: false }),
          loan({ id: "loan-3", copy: { id: "c3", code: "CP-0003" }, renewals: 0, can_renew: false }),
        ]),
      "GET /api/holds": () => page([]),
    })
    renderCirculation()

    const row = (code: string) => screen.getByRole("button", { name: `Return ${code}` }).closest("tr") as HTMLElement
    await screen.findByRole("button", { name: "Return CP-0001" })
    expect(row("CP-0001")).toHaveTextContent("Renewed 1 of 2 times")
    expect(within(row("CP-0001")).getByRole("button", { name: "Renew CP-0001" })).toBeInTheDocument()
    expect(row("CP-0002")).toHaveTextContent("Renewed 2 of 2 times")
    expect(row("CP-0002")).toHaveTextContent("No renewals left")
    expect(within(row("CP-0002")).queryByRole("button", { name: "Renew CP-0002" })).not.toBeInTheDocument()
    expect(row("CP-0003")).toHaveTextContent("Cannot renew: a member is waiting for this book")
    expect(row("CP-0003")).not.toHaveTextContent("Renewed")
    expect(within(row("CP-0003")).queryByRole("button", { name: "Renew CP-0003" })).not.toBeInTheDocument()
  })

  it("shows the API's reason when a renewal is refused", async () => {
    stubApi({
      "GET /api/loans": () => page([omarsLoan]),
      "GET /api/holds": () => page([]),
      "POST /api/loans/loan-7/renew": () =>
        errorResponse(409, "book_has_holds", "A member is waiting for this book, so the loan cannot be renewed."),
    })
    const user = userEvent.setup()
    renderCirculation()

    await user.click(await screen.findByRole("button", { name: "Renew CP-0012" }))
    const dialog = await screen.findByRole("alertdialog", { name: "Renew this loan?" })
    await user.click(within(dialog).getByRole("button", { name: "Renew" }))

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "A member is waiting for this book, so the loan cannot be renewed.",
    )
  })
})
