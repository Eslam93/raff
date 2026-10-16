import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ActivityItem } from "@/features/activity/activity-item"
import { activityEvent } from "@/test/fixtures"

const NOW = Date.parse("2026-10-16T12:00:00Z")

function renderItem(event: ReturnType<typeof activityEvent>) {
  return render(
    <ol>
      <ActivityItem event={event} now={NOW} />
    </ol>,
  )
}

describe("ActivityItem", () => {
  it.each([
    ["hold.placed", "Hold placed"],
    ["hold.ready", "Copy set aside for a hold"],
    ["hold.expired", "Hold expired: not picked up in time"],
    ["hold.cancelled", "Hold cancelled"],
    ["hold.fulfilled", "Hold fulfilled: the member borrowed the book"],
    ["loan.renewed", "Loan renewed"],
  ])("names %s in plain words", (action, label) => {
    renderItem(activityEvent({ action, summary: "Something happened" }))

    expect(screen.getByTitle(label)).toBeInTheDocument()
  })

  it("says an action the library took by itself was done automatically", () => {
    renderItem(
      activityEvent({
        action: "hold.expired",
        entity_type: "hold",
        summary: "The hold of Maya Hassan on Dune expired: CP-0012 was not picked up in time",
        via: "system",
        actor: null,
      }),
    )

    expect(
      screen.getByText("The hold of Maya Hassan on Dune expired: CP-0012 was not picked up in time"),
    ).toBeInTheDocument()
    expect(screen.getByText("done automatically")).toBeInTheDocument()
    expect(screen.queryByText(/^by /)).not.toBeInTheDocument()
  })

  it("names the person who acted, and never calls it automatic", () => {
    renderItem(
      activityEvent({
        action: "loan.renewed",
        summary: "Renewed Dune (CP-0001) for Maya Hassan, due 30 Oct 2026 instead of 16 Oct 2026",
        actor: "Maya Hassan",
      }),
    )

    expect(screen.getByText("by Maya Hassan")).toBeInTheDocument()
    expect(screen.queryByText("done automatically")).not.toBeInTheDocument()
  })
})
