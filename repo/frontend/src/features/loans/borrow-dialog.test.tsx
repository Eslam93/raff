import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { toast } from "sonner"
import { describe, expect, it, vi } from "vitest"

import { BorrowDialog } from "@/features/loans/borrow-dialog"
import { addDays, todayDateValue } from "@/lib/dates"
import { formatDueDate } from "@/lib/format"
import type { LoanOut } from "@/lib/types"
import { errorResponse, requestsTo, stubApi } from "@/test/api-stub"
import { availableCopy, bookDetail, borrowedCopy, heldCopy, member, page } from "@/test/fixtures"
import { jsonResponse, renderWithProviders } from "@/test/render"

const members = [
  member(),
  member({ id: "member-2", full_name: "Omar Nasser", email: "omar@example.com", active_loans: 1 }),
  member({ id: "member-3", full_name: "Lina Farah", email: null }),
]

function membersRoute({ search }: { search: URLSearchParams }) {
  const q = search.get("q")?.toLowerCase()
  return page(q ? members.filter((m) => m.full_name.toLowerCase().includes(q)) : members)
}

function loanFor(body: { copy_id: string; member_id: string; due_date: string }): LoanOut {
  return {
    id: "loan-1",
    copy: { id: body.copy_id, code: "CP-0003" },
    book: { id: "book-1", title: "Dune", author: "Frank Herbert" },
    member: { id: body.member_id, full_name: "Omar Nasser" },
    borrowed_at: "2026-09-19T10:00:00Z",
    due_at: `${body.due_date}T23:59:59Z`,
    returned_at: null,
    is_overdue: false,
    days_overdue: 0,
    renewals: 0,
    can_renew: true,
  }
}

async function chooseOmarWithTheKeyboard() {
  const user = userEvent.setup()
  const search = await screen.findByRole("combobox", { name: "Member" })
  expect(search).toHaveFocus()
  await user.type(search, "omar")
  const results = () => within(screen.getByRole("listbox", { name: "Members" })).getAllByRole("option")
  await waitFor(() => expect(results()).toHaveLength(1))
  expect(results()[0]).toHaveTextContent("Omar Nasser")
  expect(results()[0]).toHaveAttribute(
    "aria-selected",
    "true",
  )
  await user.keyboard("{Enter}")
  expect(screen.getByText("Omar Nasser")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Change member" })).toBeInTheDocument()
  return user
}

describe("BorrowDialog", () => {
  it("submits the preselected copy, the chosen member and the proposed due date", async () => {
    const success = vi.spyOn(toast, "success")
    const fetchMock = stubApi({
      "GET /api/members": membersRoute,
      "POST /api/loans": ({ body }) =>
        jsonResponse(loanFor(body as Parameters<typeof loanFor>[0]), 201),
    })
    const onOpenChange = vi.fn()
    renderWithProviders(
      <BorrowDialog book={bookDetail()} copyId="copy-3" open onOpenChange={onOpenChange} />,
    )

    // Only available copies are offered, and the one chosen on the page is selected.
    const copySelect = screen.getByRole("combobox", { name: "Copy" })
    expect(copySelect).toHaveValue("copy-3")
    expect(within(copySelect).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "CP-0002",
      "CP-0003",
    ])
    const dueDate = addDays(todayDateValue(), 14)
    expect(screen.getByLabelText("Due date")).toHaveValue(dueDate)

    const user = await chooseOmarWithTheKeyboard()
    await user.click(screen.getByRole("button", { name: "Borrow" }))

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false))
    expect(requestsTo(fetchMock, "POST /api/loans")[0].body).toEqual({
      copy_id: "copy-3",
      member_id: "member-2",
      due_date: dueDate,
    })
    expect(success).toHaveBeenCalledWith(
      `Borrowed Dune (CP-0003) to Omar Nasser, due ${formatDueDate(`${dueDate}T23:59:59Z`)}`,
    )
  })

  it("asks for a member before sending", async () => {
    const fetchMock = stubApi({ "GET /api/members": membersRoute })
    const user = userEvent.setup()
    renderWithProviders(<BorrowDialog book={bookDetail()} copyId={null} open onOpenChange={vi.fn()} />)

    expect(screen.getByRole("combobox", { name: "Copy" })).toHaveValue("copy-2")
    await user.click(screen.getByRole("button", { name: "Borrow" }))

    expect(await screen.findByText("Choose the member who borrows the book.")).toBeInTheDocument()
    expect(requestsTo(fetchMock, "POST /api/loans")).toHaveLength(0)
  })

  it("explains a copy taken by someone else and moves to a copy still available", async () => {
    const refreshed = bookDetail({
      copies: [
        borrowedCopy("copy-1", "CP-0001"),
        availableCopy("copy-2", "CP-0002"),
        borrowedCopy("copy-3", "CP-0003"),
      ],
    })
    const fetchMock = stubApi({
      "GET /api/members": membersRoute,
      "POST /api/loans": () =>
        errorResponse(409, "copy_unavailable", "This copy is already on loan."),
      "GET /api/books/book-1": () => refreshed,
    })
    const onOpenChange = vi.fn()
    renderWithProviders(
      <BorrowDialog book={bookDetail()} copyId="copy-3" open onOpenChange={onOpenChange} />,
    )

    const user = await chooseOmarWithTheKeyboard()
    await user.click(screen.getByRole("button", { name: "Borrow" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "CP-0003 was borrowed a moment ago by someone else. Another available copy is now selected",
    )
    expect(screen.getByRole("combobox", { name: "Copy" })).toHaveValue("copy-2")
    expect(requestsTo(fetchMock, "GET /api/books/book-1")).toHaveLength(1)
    expect(onOpenChange).not.toHaveBeenCalled()
  })

  it("never offers a copy set aside for a member's hold", () => {
    stubApi({ "GET /api/members": membersRoute })
    const book = bookDetail({
      copies: [heldCopy("copy-1", "CP-0001"), availableCopy("copy-2", "CP-0002")],
    })
    renderWithProviders(<BorrowDialog book={book} copyId={null} open onOpenChange={vi.fn()} />)

    const copySelect = screen.getByRole("combobox", { name: "Copy" })
    expect(within(copySelect).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "CP-0002",
    ])
    expect(copySelect).toHaveValue("copy-2")
  })

  it("explains a copy a return just set aside for a hold and moves to a copy still available", async () => {
    const refreshed = bookDetail({
      copies: [
        borrowedCopy("copy-1", "CP-0001"),
        availableCopy("copy-2", "CP-0002"),
        heldCopy("copy-3", "CP-0003"),
      ],
    })
    stubApi({
      "GET /api/members": membersRoute,
      "POST /api/loans": () =>
        errorResponse(409, "copy_held", "Copy CP-0003 is held for Maya Hassan until 19 Oct."),
      "GET /api/books/book-1": () => refreshed,
    })
    const onOpenChange = vi.fn()
    renderWithProviders(
      <BorrowDialog book={bookDetail()} copyId="copy-3" open onOpenChange={onOpenChange} />,
    )

    const user = await chooseOmarWithTheKeyboard()
    await user.click(screen.getByRole("button", { name: "Borrow" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Copy CP-0003 is held for Maya Hassan until 19 Oct. Another available copy is now selected: confirm to borrow it.",
    )
    expect(screen.getByRole("combobox", { name: "Copy" })).toHaveValue("copy-2")
    expect(onOpenChange).not.toHaveBeenCalled()
  })
})
