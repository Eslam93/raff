import type { ReactNode } from "react"
import { Link } from "react-router"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

/**
 * The two pages a sign-in provider asks for, readable without signing in:
 * what this deployment does with a person's data, and the terms of using a
 * demonstration.
 */
function Notice({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="flex min-h-dvh justify-center px-4 py-10">
      <div className="w-full max-w-2xl space-y-6">
        <h1 className="text-2xl font-semibold">{title}</h1>
        <Card>
          <CardContent className="space-y-4 text-sm leading-relaxed">{children}</CardContent>
        </Card>
        <Button asChild variant="outline" size="sm">
          <Link to="/sign-in">Back to sign in</Link>
        </Button>
      </div>
    </main>
  )
}

export function PrivacyPage() {
  return (
    <Notice title="Privacy">
      <p>
        This is a demonstration of a library catalog and circulation system. It is not a real
        library, and its books, members and loans are generated data.
      </p>
      <p>
        <strong>Signing in with Google.</strong> The app receives your name, your email address and
        your Google account id, and stores them so that you have an account here and so that the
        activity history can show who acted. Nothing is shared with anyone else, nothing is sold,
        and there is no advertising or tracking.
      </p>
      <p>
        <strong>The demo accounts.</strong> "Sign in as staff" and "Sign in as member" use shared
        accounts that belong to nobody and hold no personal data.
      </p>
      <p>
        <strong>Cookies.</strong> One cookie, which keeps you signed in. It expires after 12 idle
        hours, or 7 days at the latest.
      </p>
      <p>
        <strong>Other services.</strong> Questions you type into the assistant, and the results it
        looks up, are sent to OpenRouter, which passes them to the model that answers; the
        conversation is also stored in this demonstration's database. Book covers are requested by
        your browser from Open Library, and looking up an ISBN asks Open Library from the server.
      </p>
      <p>
        <strong>Keeping and deleting.</strong> The database is reset from time to time, and
        everything in it goes when the demonstration is taken down. To have your account removed
        sooner, ask whoever gave you the link.
      </p>
    </Notice>
  )
}

export function TermsPage() {
  return (
    <Notice title="Terms">
      <p>
        This deployment exists to demonstrate a piece of software. It is provided as it is, with no
        warranty and no promise that it will keep working, and it may change or disappear at any
        time.
      </p>
      <p>
        Please do not enter real personal data, and do not use it to keep anything you need. Its
        data is generated, and the database is reset from time to time.
      </p>
      <p>
        The source code is public at{" "}
        <a
          className="underline underline-offset-4"
          href="https://github.com/Eslam93/raff"
        >
          github.com/Eslam93/raff
        </a>
        .
      </p>
    </Notice>
  )
}
