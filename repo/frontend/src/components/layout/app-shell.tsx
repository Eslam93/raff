import { Suspense, useState } from "react"
import { LibraryBig, Menu } from "lucide-react"
import { Link, Outlet } from "react-router"

import { AccountMenu } from "@/components/layout/account-menu"
import { ApiStatus } from "@/components/layout/api-status"
import { SidebarNav } from "@/components/layout/sidebar-nav"
import { LoadingState } from "@/components/states/loading-state"
import { RouteErrorBoundary } from "@/components/states/route-error-boundary"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { useCurrentUser } from "@/features/auth/current-user"
import { CopilotLauncher } from "@/features/copilot/copilot-launcher"
import { homePaths, navigation } from "@/lib/navigation"
import { cn } from "@/lib/utils"

function Brand({ to, className }: { to: string; className?: string }) {
  return (
    <Link
      to={to}
      className={cn(
        "flex items-center gap-2 rounded-md font-semibold tracking-tight outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        className,
      )}
    >
      <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <LibraryBig className="size-4" aria-hidden />
      </span>
      Raff
    </Link>
  )
}

/**
 * The frame around every signed-in page: a sidebar on wide screens, a menu
 * sheet on small screens, and a top bar with the Copilot, the API status and
 * the account menu. The navigation follows the signed-in user's role.
 */
export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false)
  const user = useCurrentUser()
  const items = navigation[user.role]
  const home = homePaths[user.role]

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[15rem_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-background px-3 py-2 text-sm focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>

      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-r bg-card py-4 md:flex">
        <Brand to={home} className="mx-6" />
        <SidebarNav items={items} label="Main navigation" />
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur md:px-8">
          <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon-sm" className="md:hidden">
                <Menu aria-hidden />
                <span className="sr-only">Open navigation</span>
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-72 gap-2 bg-card p-0">
              <SheetHeader>
                <SheetTitle>Raff</SheetTitle>
                <SheetDescription className="sr-only">Go to a section of the app.</SheetDescription>
              </SheetHeader>
              <SidebarNav
                items={items}
                label="Mobile navigation"
                onNavigate={() => setMenuOpen(false)}
              />
            </SheetContent>
          </Sheet>
          <Brand to={home} className="md:hidden" />
          <div className="ml-auto flex items-center gap-2">
            {/* Keyed by user: each person gets their own conversation. */}
            <CopilotLauncher key={user.id} />
            <ApiStatus />
            <AccountMenu />
          </div>
        </header>

        <main id="main" className="flex-1 px-4 py-6 md:px-8 md:py-8">
          <div className="mx-auto w-full max-w-6xl">
            <RouteErrorBoundary>
              {/* Pages load in their own files; the shell stays while one arrives. */}
              <Suspense fallback={<LoadingState rows={3} label="Loading the page" />}>
                <Outlet />
              </Suspense>
            </RouteErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  )
}
