import { lazy } from "react"
import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Route, Routes } from "react-router"
import { beforeAll, beforeEach, describe, expect, it } from "vitest"

import { App } from "@/app"
import { AppShell } from "@/components/layout/app-shell"
import type { UserOut } from "@/lib/types"
import { errorResponse, requestsTo, stubApi } from "@/test/api-stub"
import { bookDetail, dashboard, memberDetail, memberUser, page, staffUser } from "@/test/fixtures"
import { preloadPages } from "@/test/pages"
import { renderWithProviders } from "@/test/render"

beforeAll(preloadPages)

function linkLabels(navigation: HTMLElement) {
  return within(navigation)
    .getAllByRole("link")
    .map((link) => link.textContent)
}

function currentLocation() {
  return screen.getByTestId("location").textContent
}

const healthy = () => ({ status: "ok", checks: { database: "ok" } })
const unauthorized = () => errorResponse(401, "unauthorized", "Authentication is required.")

describe("App shell", () => {
  beforeEach(() => {
    stubApi({
      "GET /api/health": healthy,
      "GET /api/dashboard": () => dashboard(),
      "GET /api/books": () => page([]),
      "GET /api/members": () => page([]),
    })
  })

  it("starts staff on the dashboard with the staff navigation", async () => {
    renderWithProviders(<App />)

    const navigation = screen.getByRole("navigation", { name: "Main navigation" })
    expect(linkLabels(navigation)).toEqual([
      "Dashboard",
      "Catalog",
      "Circulation",
      "Members",
      "Activity",
    ])
    // The router moves inside a transition, so the link turns current once the page's file has loaded.
    expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument()
    expect(within(navigation).getByRole("link", { name: "Dashboard" })).toHaveAttribute(
      "aria-current",
      "page",
    )
    expect(currentLocation()).toBe("/dashboard")
    expect(await screen.findByText("API ok")).toBeInTheDocument()
  })

  it("starts a member on the catalog with the member navigation", async () => {
    renderWithProviders(<App />, { user: memberUser() })

    const navigation = screen.getByRole("navigation", { name: "Main navigation" })
    expect(linkLabels(navigation)).toEqual(["Catalog", "My loans", "History"])
    expect(await screen.findByRole("heading", { level: 1, name: "Catalog" })).toBeInTheDocument()
    expect(currentLocation()).toBe("/catalog")
    expect(await screen.findByText("API ok")).toBeInTheDocument()
  })

  it("offers the Copilot in the top bar without asking the API about it until it opens", async () => {
    const fetchMock = stubApi({ "GET /api/health": healthy, "GET /api/books": () => page([]) })
    renderWithProviders(<App />, { user: memberUser() })

    expect(screen.getByRole("banner")).toContainElement(screen.getByRole("button", { name: "Copilot" }))
    expect(await screen.findByText("API ok")).toBeInTheDocument()
    expect(requestsTo(fetchMock, "GET /api/copilot/config")).toHaveLength(0)
  })

  it("shows a not-found page for an unknown path", async () => {
    renderWithProviders(<App />, { route: "/no-such-page" })

    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument()
    expect(await screen.findByText("API ok")).toBeInTheDocument()
  })

  it("opens the navigation in a sheet and closes it after a link is chosen", async () => {
    const user = userEvent.setup()
    renderWithProviders(<App />)

    await user.click(screen.getByRole("button", { name: "Open navigation" }))
    const sheet = await screen.findByRole("dialog")
    await user.click(within(sheet).getByRole("link", { name: "Members" }))

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(await screen.findByRole("heading", { level: 1, name: "Members" })).toBeInTheDocument()
  })
})

describe("Pages", () => {
  const staff = staffUser()
  const member = memberUser()

  it.each<[string, UserOut, string]>([
    ["/dashboard", staff, "Dashboard"],
    ["/catalog", staff, "Catalog"],
    ["/books/book-1", staff, "Dune"],
    ["/circulation", staff, "Circulation"],
    ["/members", staff, "Members"],
    ["/members/member-1", staff, "Maya Hassan"],
    ["/activity", staff, "Activity"],
    ["/catalog", member, "Catalog"],
    ["/my-loans", member, "My loans"],
    ["/history", member, "History"],
  ])("shows %s once its own file has loaded", async (route, user, heading) => {
    stubApi({
      "GET /api/health": healthy,
      "GET /api/dashboard": () => dashboard(),
      "GET /api/books": () => page([]),
      "GET /api/books/categories": () => [],
      "GET /api/books/book-1": () => bookDetail(),
      "GET /api/loans": () => page([]),
      "GET /api/me/loans": () => page([]),
      "GET /api/members": () => page([]),
      "GET /api/members/member-1": () => memberDetail(),
      "GET /api/activity": () => [],
    })

    renderWithProviders(<App />, { route, user })

    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument()
  })

  it("keeps the shell on screen with a loading state while a page's file arrives", async () => {
    stubApi({ "GET /api/health": healthy })
    // A page whose file never arrives.
    const NeverLoads = lazy(() => new Promise<never>(() => {}))

    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/slow" element={<NeverLoads />} />
        </Route>
      </Routes>,
      { route: "/slow" },
    )

    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument()
    expect(await screen.findByText("Loading the page")).toBeInTheDocument()
    expect(await screen.findByText("API ok")).toBeInTheDocument()
  })
})

describe("Roles", () => {
  it.each(["/dashboard", "/circulation", "/members", "/members/member-1", "/activity"])(
    "tells a member that %s is not available for their role",
    (route) => {
      const fetchMock = stubApi({ "GET /api/health": healthy })

      renderWithProviders(<App />, { route, user: memberUser() })

      expect(
        screen.getByRole("heading", { level: 1, name: "Not available for your role" }),
      ).toBeInTheDocument()
      expect(screen.getByText("This page is for library staff")).toBeInTheDocument()
      expect(screen.getByRole("link", { name: "Go to the start page" })).toHaveAttribute(
        "href",
        "/catalog",
      )
      // The page's own requests would be refused, so none are made.
      const paths = fetchMock.mock.calls.map(([input]) => String(input))
      expect(paths.filter((path) => path !== "/api/health")).toEqual([])
    },
  )

  it("tells staff that a member's own pages are not for them", () => {
    stubApi({ "GET /api/health": healthy })

    renderWithProviders(<App />, { route: "/my-loans" })

    expect(
      screen.getByRole("heading", { level: 1, name: "Not available for your role" }),
    ).toBeInTheDocument()
    expect(screen.getByText("This page is for members")).toBeInTheDocument()
  })
})

describe("Session", () => {
  it("sends an anonymous visitor to sign-in, set to come back to the page they asked for", async () => {
    stubApi({
      "GET /api/auth/me": unauthorized,
      "GET /api/auth/config": () => ({ demo_login: true, google: true }),
    })

    renderWithProviders(<App />, { route: "/books/book-1?tab=copies", user: undefined })

    expect(await screen.findByRole("heading", { level: 1, name: "Raff" })).toBeInTheDocument()
    expect(currentLocation()).toBe("/sign-in?next=%2Fbooks%2Fbook-1%3Ftab%3Dcopies")
    expect(await screen.findByRole("link", { name: "Continue with Google" })).toHaveAttribute(
      "href",
      "/api/auth/google/login?next=%2Fbooks%2Fbook-1%3Ftab%3Dcopies",
    )
    expect(screen.queryByText("Your session ended, sign in again.")).not.toBeInTheDocument()
  })

  it("returns to sign-in once, with a notice, when a data request is refused with 401", async () => {
    const fetchMock = stubApi({
      "GET /api/health": healthy,
      "GET /api/books": unauthorized,
      "GET /api/auth/config": () => ({ demo_login: true, google: false }),
    })

    renderWithProviders(<App />, { route: "/catalog?q=dune" })

    expect(await screen.findAllByText("Your session ended, sign in again.")).toHaveLength(1)
    expect(currentLocation()).toBe("/sign-in?next=%2Fcatalog%3Fq%3Ddune")
    expect(await screen.findByRole("button", { name: "Sign in as staff" })).toBeInTheDocument()
    expect(requestsTo(fetchMock, "GET /api/books")).toHaveLength(1)
    // The refusal already answered who is signed in: nobody.
    expect(requestsTo(fetchMock, "GET /api/auth/me")).toHaveLength(0)
  })

  it("shows the account with its role and demo badge, and signs out", async () => {
    const fetchMock = stubApi({
      "GET /api/health": healthy,
      "GET /api/books": () => page([]),
      "POST /api/auth/logout": () => new Response(null, { status: 204 }),
      "GET /api/auth/me": unauthorized,
      "GET /api/auth/config": () => ({ demo_login: true, google: false }),
    })
    const user = userEvent.setup()
    renderWithProviders(<App />, { route: "/catalog", user: memberUser() })

    await user.click(screen.getByRole("button", { name: "Account menu, Demo Member" }))
    const menu = await screen.findByRole("menu")
    expect(within(menu).getByText("member@demo.local")).toBeInTheDocument()
    expect(within(menu).getByText("Member")).toBeInTheDocument()
    expect(within(menu).getByText("Demo")).toBeInTheDocument()

    await user.click(within(menu).getByRole("menuitem", { name: "Sign out" }))

    expect(await screen.findByRole("button", { name: "Sign in as member" })).toBeInTheDocument()
    expect(currentLocation()).toBe("/sign-in")
    expect(requestsTo(fetchMock, "POST /api/auth/logout")).toHaveLength(1)
    expect(screen.queryByText("Your session ended, sign in again.")).not.toBeInTheDocument()
  })
})
