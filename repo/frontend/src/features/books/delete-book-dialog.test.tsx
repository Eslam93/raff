import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router"
import { toast } from "sonner"
import { describe, expect, it, vi } from "vitest"

import { DeleteBookDialog } from "@/features/books/delete-book-dialog"
import type { BookDetail } from "@/lib/types"
import { errorResponse, requestsTo, stubApi } from "@/test/api-stub"
import { availableCopy, bookDetail, borrowedCopy, heldCopy } from "@/test/fixtures"
import { renderWithProviders } from "@/test/render"

const onShelf = [availableCopy("copy-1", "CP-0001"), availableCopy("copy-2", "CP-0002")]

function renderDialog(book: BookDetail) {
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<DeleteBookDialog book={book} open onOpenChange={vi.fn()} />} />
      <Route path="/catalog" element={<p>Catalog page</p>} />
    </Routes>,
  )
}

describe("DeleteBookDialog", () => {
  it("says a book that was never borrowed will be permanently deleted", async () => {
    const success = vi.spyOn(toast, "success")
    const fetchMock = stubApi({ "DELETE /api/books/book-1": () => ({ outcome: "deleted" }) })
    const user = userEvent.setup()
    renderDialog(bookDetail({ has_loan_history: false, copies: onShelf }))

    const dialog = screen.getByRole("alertdialog", { name: "Delete Dune?" })
    expect(dialog).toHaveTextContent("Dune will be permanently deleted, with its 2 copies.")
    expect(dialog).not.toHaveTextContent("archived")

    await user.click(screen.getByRole("button", { name: "Delete book" }))

    expect(await screen.findByText("Catalog page")).toBeInTheDocument()
    expect(requestsTo(fetchMock, "DELETE /api/books/book-1")).toHaveLength(1)
    expect(success).toHaveBeenCalledWith("Deleted Dune")
  })

  it("says a book with loan history will be archived", async () => {
    const success = vi.spyOn(toast, "success")
    stubApi({ "DELETE /api/books/book-1": () => ({ outcome: "archived" }) })
    const user = userEvent.setup()
    renderDialog(bookDetail({ has_loan_history: true, copies: onShelf }))

    const dialog = screen.getByRole("alertdialog", { name: "Archive Dune?" })
    expect(dialog).toHaveTextContent(
      "Dune will be archived: hidden from the catalog, its loan history kept.",
    )
    expect(dialog).not.toHaveTextContent("permanently deleted")

    await user.click(screen.getByRole("button", { name: "Archive book" }))

    expect(await screen.findByText("Catalog page")).toBeInTheDocument()
    expect(success).toHaveBeenCalledWith("Archived Dune")
  })

  it("says the open holds on the book are cancelled with it", () => {
    stubApi({})
    renderDialog(
      bookDetail({ has_loan_history: true, copies: [heldCopy("copy-1", "CP-0001")], holds_waiting: 2 }),
    )

    expect(screen.getByRole("alertdialog", { name: "Archive Dune?" })).toHaveTextContent(
      "Its copies can no longer be borrowed. 3 open holds on it are cancelled.",
    )
  })

  it("explains up front that a book with a copy on loan cannot be removed", () => {
    const fetchMock = stubApi({})
    renderDialog(bookDetail({ copies: [borrowedCopy("copy-1", "CP-0001"), ...onShelf] }))

    const dialog = screen.getByRole("alertdialog", { name: "Dune cannot be removed now" })
    expect(dialog).toHaveTextContent("1 copy is on loan.")
    expect(screen.queryByRole("button", { name: /Delete book|Archive book/ })).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("shows the refusal when a copy went out on loan after the page loaded", async () => {
    stubApi({
      "DELETE /api/books/book-1": () =>
        errorResponse(409, "book_has_active_loans", "A copy of this book is on loan."),
    })
    const user = userEvent.setup()
    renderDialog(bookDetail({ copies: onShelf }))

    await user.click(screen.getByRole("button", { name: "Archive book" }))

    const dialog = await screen.findByRole("alertdialog", { name: "Dune cannot be removed now" })
    expect(dialog).toHaveTextContent(
      "A copy of this book is on loan. Return every copy first, then try again.",
    )
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument()
    expect(screen.queryByText("Catalog page")).not.toBeInTheDocument()
  })
})
