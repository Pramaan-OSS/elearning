[![CI](https://github.com/Pramaan-OSS/elearning/actions/workflows/ci.yml/badge.svg)](https://github.com/Pramaan-OSS/elearning/actions/workflows/ci.yml)

# eLearning

An open source learning management system: publish courses, run live batches,
assess learners with quizzes, assignments and programming exercises, and issue
certificates.

## Quick start

You need Docker with Compose and Python 3. Then:

```sh
cp .env.example .env    # paste your PRAMAAN_API_KEY into .env
./start
```

The first run takes a few minutes. When it finishes, open the address the
command prints and sign in as `Administrator`; the password is in
`.env` as `ELEARNING_ADMIN_PASSWORD`.

`./start` uses the production server and built assets. Use `./start --dev` for
source editing, or `./start --production` to switch back on the same stack.

Stop with `docker compose --env-file .env -f docker/docker-compose.yml down`.

## What is included

- Courses, chapters and lessons with video, quizzes, assignments and
  programming exercises.
- Live classes on your own connected meeting app, with calendar invites.
- Batches with schedules, certificates and evaluations.
- Paid courses and batches through the platform's hosted checkout.
- Local search, local file storage and local certificates.

## Configuration

Only `PRAMAAN_API_KEY` is required. Everything else in `.env` has a working
default or is generated on first start. Optional features are off until
configured:

- Live class conferencing and calendar invites: set the meeting app and
  calendar inbox in Settings > Connected Services.
- Sign-in uses local accounts. Connected sign-in is unavailable until a hosted
  authorization start can support this session backend; see `GAPS.md`.
- Paid courses: works out of the box once your platform account can take
  charges; set the outgoing sender email in Settings for mail.
- Email sending uses the platform; mailboxes, attendance data and image search
  are not available yet.

## Connected accounts

Connecting an outside account, such as a mailbox, calendar or meeting app, carries a monthly Pramaan charge for each
connected account, billed to the Pramaan account behind `PRAMAAN_API_KEY`. Signing in is free. Disconnecting an account
ends its charge.

## Built on

eLearning is built on [Frappe Learning](https://github.com/frappe/lms) by
Frappe Technologies Pvt Ltd and contributors, licensed AGPL-3.0. The original
licence text and copyright notices are preserved in `LICENSE-ORIGINAL`.

Course checkout and reminder payment links use `PRAMAAN_TAX_CATEGORY` from `.env`,
defaulting to `edtech`. This is the single tax classification setting for payments.

### Adopted capabilities (not yet live-verified)

Local password access remains available. To offer hosted connected sign-in, set
`pramaan_social_providers` in the site's private configuration to an array of the
connected sign-in keys (`google`, `microsoft`). Register the exact HTTPS callback
`/api/method/lms.integrations.social.callback` on the connected sign-in account.
A local HTTP installation cannot start hosted sign-in.

Staff with the System Manager or Moderator role can send account invitations
from Members → Send an account invitation (`/invitations`). Configure the site's
public HTTPS address and the builder's verified sending domain first. Recipients
accept at `/invitation`, then use local Forgot password to set their password.
Existing accounts receive no extra roles from an invitation retry.

Class instructors can refresh attendance from the existing attendance dialog;
the hourly job also records completed reports. Reports contain unverified display
names and completed sessions, not learner identity or absence decisions. Every
class calendar write requires a hidden guest list. Cover-image search now returns
licensed stock photos with visible photographer, source and licence credits.

Offline checks use `PRAMAAN_FAKE=1`; the default fixture answers unavailable.
`PRAMAAN_FAKE_ADOPTION=success`, `refused`, `no_data` or `processing` selects an
explicit adoption fixture. An empty key still prevents outside requests. Never
use fixture settings as evidence of live availability.
