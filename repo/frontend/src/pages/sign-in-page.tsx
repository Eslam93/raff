import { useEffect, useState } from "react"
import { CircleAlert, Clock, KeyRound, LibraryBig } from "lucide-react"
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router"

import { FormAlert } from "@/components/forms/form-alert"
import { PendingButton } from "@/components/forms/pending-button"
import { EmptyState } from "@/components/states/empty-state"
import { ErrorState } from "@/components/states/error-state"
import { LoadingState } from "@/components/states/loading-state"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { googleSignInUrl } from "@/features/auth/api"
import { useAuthConfig, useDemoSignIn, useMe } from "@/features/auth/hooks"
import { isSessionEndedState, safeNextPath } from "@/features/auth/session"
import { ApiError } from "@/lib/api"
import { homePaths, roleLabels } from "@/lib/navigation"
import type { AuthConfigOut, Role } from "@/lib/types"

const demoRoles: { role: Role; description: string }[] = [
  {
    role: "staff",
    description: "Manage the catalog and members, lend and return books, and see all activity.",
  },
  {
    role: "member",
    description: "Browse the catalog and see your own loans, due dates and history.",
  },
]

function demoFailureMessage(error: unknown) {
  if (error instanceof ApiError && error.status === 404) {
    return "Demo sign-in is turned off on this server."
  }
  return error instanceof ApiError ? error.message : "Something went wrong. Try again."
}

/**
 * The only page outside the app shell. It offers the sign-in methods the API
 * has turned on and, after sign-in, opens the page in `next` or the role's
 * start page.
 */
export function SignInPage() {
  const [searchParams] = useSearchParams()
  const location = useLocation()
  const me = useMe()
  const config = useAuthConfig()

  const next = safeNextPath(searchParams.get("next"))
  const googleFailed = searchParams.get("error") === "google"
  const sessionEnded = isSessionEndedState(location.state)

  useEffect(() => {
    document.title = "Sign in · Raff"
  }, [])

  if (me.data) return <Navigate to={next ?? homePaths[me.data.role]} replace />

  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-xl space-y-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <LibraryBig className="size-6" aria-hidden />
          </span>
          <h1 className="text-2xl font-semibold tracking-tight">Raff</h1>
          <p className="text-sm text-muted-foreground">
            Find books, see what is on the shelf, and keep track of every loan.
          </p>
        </div>

        {sessionEnded && (
          <Alert role="status">
            <Clock aria-hidden />
            <AlertTitle>Your session ended, sign in again.</AlertTitle>
            <AlertDescription>You will come back to the page you were on.</AlertDescription>
          </Alert>
        )}
        {googleFailed && (
          <Alert variant="destructive" role="alert">
            <CircleAlert aria-hidden />
            <AlertTitle>Google sign-in did not work</AlertTitle>
            <AlertDescription className="text-destructive/90">
              Try again. If it keeps failing, use another way to sign in.
            </AlertDescription>
          </Alert>
        )}

        <Card>
          <CardContent>
            {config.data ? (
              <SignInMethods config={config.data} next={next} />
            ) : config.isError ? (
              <ErrorState
                title="Could not load the sign-in options"
                error={config.error}
                onRetry={() => void config.refetch()}
              />
            ) : (
              <LoadingState rows={2} label="Loading the sign-in options" />
            )}
          </CardContent>
        </Card>
        <SignInFooter />
      </div>
    </main>
  )
}

function SignInMethods({ config, next }: { config: AuthConfigOut; next: string | null }) {
  if (!config.google && !config.demo_login) {
    return (
      <EmptyState
        icon={KeyRound}
        title="Sign-in is not set up"
        description="No sign-in method is turned on for this library. An administrator can configure Google sign-in or turn on the demo sign-in."
        className="border-0 bg-transparent py-6"
      />
    )
  }

  return (
    <div className="space-y-6">
      {config.google && (
        <Button asChild variant="outline" size="lg" className="w-full">
          <a href={googleSignInUrl(next)}>
            <GoogleMark />
            Continue with Google
          </a>
        </Button>
      )}
      {config.google && config.demo_login && (
        <div className="flex items-center gap-3 text-xs text-muted-foreground" aria-hidden>
          <span className="h-px flex-1 bg-border" />
          or
          <span className="h-px flex-1 bg-border" />
        </div>
      )}
      {config.demo_login && <DemoSignIn next={next} />}
    </div>
  )
}

function DemoSignIn({ next }: { next: string | null }) {
  const navigate = useNavigate()
  const demoSignIn = useDemoSignIn()
  const [failure, setFailure] = useState<string | null>(null)
  const pendingRole = demoSignIn.isPending ? demoSignIn.variables : null

  async function signIn(role: Role) {
    setFailure(null)
    try {
      const user = await demoSignIn.mutateAsync(role)
      navigate(next ?? homePaths[user.role], { replace: true })
    } catch (error) {
      setFailure(demoFailureMessage(error))
    }
  }

  return (
    <section aria-labelledby="demo-heading" className="space-y-4">
      <div className="space-y-1">
        <h2 id="demo-heading" className="font-semibold">
          Try the demo
        </h2>
        <p className="text-sm text-muted-foreground">
          Shared demo accounts with sample data. Pick a role to see what it can do.
        </p>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2">
        {demoRoles.map(({ role, description }) => (
          <li key={role} className="flex flex-col gap-3 rounded-lg border p-4">
            <div className="space-y-1">
              <p className="text-sm font-medium">{roleLabels[role]}</p>
              <p id={`demo-${role}`} className="text-sm text-muted-foreground">
                {description}
              </p>
            </div>
            <PendingButton
              className="mt-auto w-full"
              pending={pendingRole === role}
              pendingLabel="Signing in…"
              disabled={demoSignIn.isPending}
              aria-describedby={`demo-${role}`}
              onClick={() => void signIn(role)}
            >
              Sign in as {role}
            </PendingButton>
          </li>
        ))}
      </ul>
      <FormAlert title="Could not sign in" message={failure} />
    </section>
  )
}

/** The notices a sign-in provider links to, reachable before signing in. */
export function SignInFooter() {
  return (
    <p className="text-center text-xs text-muted-foreground">
      <Link className="underline underline-offset-4" to="/privacy">
        Privacy
      </Link>
      {" · "}
      <Link className="underline underline-offset-4" to="/terms">
        Terms
      </Link>
    </p>
  )
}

/** Google's "G", which people look for on this button. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className="size-4">
      <path
        fill="#4285F4"
        d="M23.5 12.27c0-.85-.08-1.67-.22-2.45H12v4.64h6.45a5.52 5.52 0 0 1-2.4 3.62v3h3.88c2.27-2.09 3.57-5.17 3.57-8.81Z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.96-1.07 7.94-2.91l-3.88-3.01c-1.07.72-2.45 1.15-4.06 1.15-3.13 0-5.78-2.11-6.72-4.95H1.27v3.11A12 12 0 0 0 12 24Z"
      />
      <path
        fill="#FBBC05"
        d="M5.28 14.28a7.2 7.2 0 0 1 0-4.56V6.61H1.27a12 12 0 0 0 0 10.78l4.01-3.11Z"
      />
      <path
        fill="#EA4335"
        d="M12 4.77c1.76 0 3.34.61 4.59 1.8l3.44-3.44A11.5 11.5 0 0 0 12 0 12 12 0 0 0 1.27 6.61l4.01 3.11C6.22 6.88 8.87 4.77 12 4.77Z"
      />
    </svg>
  )
}
