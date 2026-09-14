# Poll Brief

A personal daily VoteHub digest: EventBridge Scheduler → Python Lambda → VoteHub,
S3 state, and one multipart SES email. No server, frontend, or LLM is required.

## Local setup

Use Python 3.13+ and run these PowerShell commands from the repository root:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e . -r requirements-dev.txt
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/ruff check src tests
.venv/Scripts/ruff format --check src tests
.venv/Scripts/cfn-lint template.yaml
```

`src/poll_brief/` separates fetching (`api.py`), normalization (`polls.py`), S3
state (`state.py`), rendering (`render.py`), SES delivery (`email.py`), and
orchestration/preview (`app.py`). Tests and explicitly synthetic data live in
`tests/`. Four-space Python indentation, snake_case names, and Ruff formatting
apply. No coverage percentage is mandated.

`config/.env.example` lists settings without secrets; it is a reference, not an
automatically loaded dotenv file. Deployment uses the SAM parameters below.

## Preview without AWS or email

```powershell
# Offline synthetic examples, including an old poll and HTML-sensitive text:
.venv/Scripts/python -m poll_brief.app --fixture tests/fixtures/synthetic-polls.json --all
# Live public API, default first-run seven-day window:
.venv/Scripts/python -m poll_brief.app --output preview-live.html
```

Open `preview.html` or `preview-live.html`; a plain-text `.txt` companion is also
written. Preview never calls S3, SES, or SSM. Optional `--state path/to/state.local.json`
reads a local state snapshot without changing it. `--api-url` selects an equivalent
endpoint without query filters. `--first-run-days 14` changes the initial window.

## Newsletter presentation

The HTML digest uses a centered, fluid 640px table layout, inline styles, white
poll cards, compact field dates/sample labels, and prominent results and margins.
Race headings expand known office and district codes (for example, California
40th · U.S. House). Full candidate names remain in result rows; an unambiguous
surname is used in the margin. LV/RV/A retain the API's population classifications.
Election years remain above the race heading. Unknown labels are preserved.
Race sections appear in this order: U.S. Senate, governor, U.S. House, generic
ballot, then other topics. Within each category, newer election years come first,
followed by geography/name alphabetically. Polls within a race retain their
existing pollster/date order. The same order is used in HTML and plain text.

The layout requires no JavaScript, web fonts, images, or frontend dependencies.
An Outlook conditional table supplies the desktop width; cosmetic features such
as rounded corners can fall back to square borders. Desktop and phone browser
previews have been checked; delivery in actual email clients has not been tested.
Regenerate the previews after changing the renderer with the commands above.

## Candidate party labels

VoteHub supplies answer names and percentages, but no candidate-party field.
`src/poll_brief/candidate_parties.json` is a **partial, static** local registry
of 1,007 names for 2026 Senate, governor, and House races. Its entries were
derived from [ElectIndex's 2026 forecast race CSV](https://github.com/ElectIndex/26_us_forecast_data/blob/main/races.csv),
which is a third-party roster, not an official election record. The marker in
the HTML email links to that source. The roster is not complete or
automatically updated; party labels and candidacies should be reviewed before
relying on them, especially as races change.

To add a candidate, copy an existing JSON entry and set `year`, `poll_type`
(`governor`, `us-senator`, or `us-representative`), the displayed `race` heading,
full `name` exactly as VoteHub spells it, `party` (`R`, `D`, `I`, or `O`), and an
HTTPS source. Prefer an official election record for individually reviewed
additions. Run the tests, preview again, then run `sam build` and
`sam deploy` to update the deployed Lambda. The match includes year, office, race,
and full answer name, so a reused surname cannot assign a party in another race.
Unknown or unmatched names remain unlabeled. Generic-ballot `Dem` and `Rep`
answers use those API labels directly.

The newsletter shows the configured elephant image with `R` or donkey image
with `D` beside mapped answers. Unknown and third-party answers use a yellow
square. It uses red or blue on the existing poll margin when its leading answer
has a mapped party, and a neutral color for ties or unknown parties. Image alt
text and the party letter remain readable if a mail client blocks images.
These colors report the poll's published answers; they are not a forecast.

## API contract and selection

Verified on September 13, 2026 using the [VoteHub documentation](https://votehub.com/polls/api/)
and live HTTPS requests to `https://api.votehub.com/polls`:

- No authentication was required. The full response was a JSON list of 5,605 polls;
  documentation shows an envelope with a `polls` list, which is also supported.
- No pagination is documented or exposed in response headers. A request with
  `page=2&per_page=1` returned the same full collection. The adapter makes one
  unfiltered request; it does not fabricate page numbers. Unexpected envelope
  metadata or a `Link` header aborts the run pending adapter review.
- The response includes `id`, `created_at`, field dates, pollster, subject,
  `poll_type`, `seat_name`, sample size, population, `answers` (`choice`, `pct`),
  and `url`. Geography is displayed when present in subject/seat; none is inferred.
  Unrecognized population codes are retained verbatim.

Every run compares the entire collection against persisted IDs, so late additions
are included even with old fieldwork or creation dates. Revisions to an existing
ID are not emailed again. The initial run uses `created_at` as the publication
proxy: today plus six previous UTC calendar dates. Missing creation dates are
included regardless of field dates. `FirstRunDays` changes the window;
`FirstRunAll=true` includes all polls. Older initial records are baselined after
successful delivery so they do not flood the next digest.

State `ids` therefore contains emailed IDs plus intentionally baselined initial
IDs. It is never pruned. If an ID is absent, a SHA-256 fingerprint uses normalized
pollster, subject/type/seat, field dates, sample/population, sorted answers, and URL;
creation/retrieval timestamps are excluded. Changes to those fields can produce a
new fingerprint. Corrupt data/state causes failure, not an empty digest.

HTML and text group every selected poll by topic/race. Decimal arithmetic supplies
Dem-versus-Rep generic-ballot margins and two-candidate governor/Senate/House
margins. Unknown types, residual answers, and approval/favorability omit candidate
margins. VoteHub attribution and its CC BY 4.0 license accompany each digest.

## SES setup (run when ready to use AWS)

Use AWS CLI credentials for your account and keep SES and the stack in the same
region. These commands initiate verification emails; they are not part of tests:

```powershell
aws ses verify-email-identity --email-address sender@example.com --region us-east-1
aws ses verify-email-identity --email-address recipient@example.com --region us-east-1
aws ses get-identity-verification-attributes --identities sender@example.com recipient@example.com --region us-east-1
```

Click the verification links before deployment. Both identities must show
`Success` while in the [SES sandbox](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html).
Personal use with one verified recipient can remain in the sandbox. Sender and
recipient can be the same verified address. The template scopes SES permissions
to that verified sender email identity and exactly one recipient.

## Build and deploy

Install AWS SAM CLI and Python 3.13 (or Docker for `sam build --use-container`).
Use a stack name no longer than 57 characters because the function adds `-digest`.
The following commands create AWS resources; deployment is an explicit operator step:

```powershell
sam validate --template-file template.yaml --region us-east-1
sam build --template-file template.yaml
sam deploy --guided --stack-name poll-brief --region us-east-1 --capabilities CAPABILITY_IAM --parameter-overrides Sender=sender@example.com Recipient=recipient@example.com
```

The guided deployment saves local choices in ignored `samconfig.toml`. For later
updates run `sam build` and `sam deploy`. Default `ScheduleExpression` is
`cron(0 8 * * ? *)`, `ScheduleTimezone` is `America/New_York`, and the flexible
window is off. [Scheduler's timezone handling](https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html)
accounts for daylight saving time. Set `ScheduleState=DISABLED` to provision without
scheduled sends; manual invocation still sends email.

`ApiUrl`, `FirstRunDays`, and `FirstRunAll` are optional SAM parameters. Public
VoteHub needs no credential. `ApiTokenParameter` optionally names an existing
SSM **SecureString** path (for example `/poll-brief/api-token`) in this region;
its decrypted value is used as a Bearer header for an explicitly configured
compatible service. This is not a claim that VoteHub requires Bearer authentication.
Create the secret in the AWS console, never in committed configuration. If using
a customer-managed key, also set `ApiTokenKmsKeyArn` and allow this role in the key
policy. SSM/KMS permissions are included only when configured.

## Manual invocation and operations

This command sends one real email and advances state after SES acceptance:

```powershell
aws lambda invoke --function-name poll-brief-digest --region us-east-1 --cli-binary-format raw-in-base64-out --payload '{}' response.json
Get-Content response.json
aws logs tail /aws/lambda/poll-brief-digest --since 1d --region us-east-1
```

Inspect both the CLI response for `FunctionError` and `response.json`. Logs show
fetch counts, SES acceptance, state completion, and failure types without secrets.
Logs expire after 14 days. Monitor Lambda Errors/Throttles in CloudWatch; no alert
email or extra monitoring service is provisioned.

The function has reserved concurrency 1 and an S3 conditional-write lease. Normal
completion/failure expires the lease; a hard timeout leaves it for at most ten
minutes. Wait ten minutes before retrying a timed-out run. Keep the 180-second
Lambda timeout shorter than the lease. Scheduler retries delivery twice;
Lambda function-error retries and SES SDK retries are disabled to reduce duplicate
sends. A successful scheduled invocation records its scheduled-time key so a
repeated delivery is skipped. Manual invocations intentionally have no such key.

API requests use 15-second timeouts and at most four attempts, with exponential
backoff/jitter and `Retry-After` support. Long rate-limit waits fail for a later run.
All fetch/validation/render failures occur before sending. S3 digest state is saved
only after SES returns a message ID. **SES and S3 are not one transaction:** an
accepted email followed by a failed state write, timeout, or ambiguous SES network
response can cause a duplicate on a later run. SES acceptance also does not
promise inbox delivery. A later successful run includes any polls missed during
failed days.

The S3 bucket is private, encrypted, versioned, and retained on stack deletion;
old versions expire after 30 days. State and leases use conditional writes to
avoid overwriting concurrent changes. Keep the bucket when redeploying to preserve
deduplication; a new bucket starts a new initial digest. Daily invocation, a few S3
operations, and one email keep usage small without always-running resources.

