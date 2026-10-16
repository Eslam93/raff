---
title: Running the live demo - what it was made of, how it was managed, and how it was taken down
status: superseded
as_of: 2026-09-20
last_verified: 2026-10-16
verification_method: Written on 2026-09-20 from the deployment as it was built that day, and checked against the running system: the health check, the sign-in page, demo and Google sign-in, and three Copilot turns through the public address
scope: The demonstration deployment of this application: its pieces, how it is reached, how it is managed and changed, what it costs, and the order to remove it. Identifiers of the individual resources are kept with the owner, not here
confidence: High for the shape and the commands, which were run. Medium for the cost, which is an estimate from published prices rather than a bill
known_gaps: One instance with its database on the same disk, so a stop loses the data; no backups; no application liveness probe; nothing measured under real traffic
reverify_when: Raff is hosted again; that deployment gets its own page, and this one stays as history
---

# Running the live demo

**Historical since 2026-10-16.** This deployment was torn down at the owner's request and every
resource was checked gone (D-25). The page stays as the record of how the first deployment was built
and run; where Raff is hosted next is open.

The demonstration runs on one small virtual machine in a single region, with the same Docker
Compose stack a laptop runs: PostgreSQL, a one-shot migration, and the application. A content
delivery network sits in front of it and serves the public address over HTTPS.

## The pieces, and why each one is there

| Piece | Why |
|---|---|
| One virtual machine (2 virtual CPUs, 1 GB of memory, 16 GB disk, 3 GB swap) | runs the stack; the swap exists because the web build needs more memory than the machine has |
| A fixed public address | so the network in front always finds the machine, even after a restart |
| The content delivery network | gives HTTPS and a certificate. The session cookie is marked Secure, so a plain HTTP address could not carry a sign-in at all. Caching is off and every header, cookie and query string is forwarded, so the Copilot's event stream arrives as it is sent |
| A certificate for the subdomain, and two records at the owner's registrar | one proves the name, one points it at the network. Nothing about the owner's other sites changed |
| A firewall rule | the machine accepts traffic only from the delivery network's own address ranges. There is no SSH key |
| A machine role and four encrypted parameters | the model key, the Google client id and secret, and the staff address list. The machine reads them at start; they are never written into its start-up script |

## How it is managed

There is no SSH. Commands run through the cloud's own agent, which the machine role allows, so
the machine has no open management port. The start-up script clones the published repository,
builds the image, starts the stack and fills the demo library, so rebuilding the machine from
nothing is one action, and taking a new version of the code is a pull, a build and a restart.

## What a visitor can change

The demo sign-in buttons are turned on here deliberately, so a reviewer can see both roles without
an account (D-05). That means anyone who opens the address can act as staff: add, edit, archive or
delete books, and borrow or return copies. That is the point of a demonstration, and the library is
generated data, but it means the demo can be left untidy by a visitor.

Restoring it is not the ordinary seed command: `--reset` refuses to run when the application is in
production, by design, so the restore runs the seed with the application's environment overridden
for that one command, which empties the library data and generates it again. Sign-ins, including
Google accounts, are not part of that data and survive.

## What it costs, and how to remove it

Roughly eight to ten dollars a month while it runs: the machine, its disk and its address. The
delivery network's free tier covers this traffic, and the certificate is free.

To remove it, in this order: terminate the machine, release the address, disable the delivery
network's distribution and then delete it, delete the firewall rule, delete the four parameters,
remove the machine role and its profile, delete the certificate, and remove the two records at the
registrar. The last two are easy to forget: without them the subdomain points at a distribution
that no longer exists.

The exact identifiers, the management commands and the teardown commands are kept with the owner
rather than in this repository.
