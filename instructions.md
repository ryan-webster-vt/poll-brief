# Task: Build a Daily VoteHub Poll Email Digest

## Objective
Build a personal Python application that emails me a daily summary of every new poll available through VoteHub’s API.

Use:
- **AWS Lambda:** Run the application.
- **EventBridge Scheduler:** Trigger the daily run.
- **S3:** Store persistent state.
- **Amazon SES:** Send the email.

Keep it simple and inexpensive: one recipient, no frontend, no always-running server, and no LLM dependency.

## Working Instructions
1. Inspect the repository and any `AGENTS.md` instructions.
2. Implement the application and deployment files, rather than only proposing a plan.
3. Run the available tests and fix failures.
4. Do not deploy AWS resources or send real email during development.

## API Integration
- Verify VoteHub’s actual API endpoint, documentation, authentication, response schema, and pagination. Do not invent endpoints or fields.
- If verification is impossible, ask me for documentation or a sample response. Meanwhile, implement independent components and isolate the API integration behind a clearly marked adapter.
- Support request timeouts, bounded retries with backoff for transient errors, and rate limits.
- Retrieve every relevant page before sending the digest.
- Never interpret an API failure as “no new polls.”

## Poll Tracking
- Include polls newly added since the last successful digest, regardless of when their fieldwork ended.
- Persist previously emailed poll IDs in S3.
- If stable IDs are unavailable, use a documented deterministic fingerprint.
- Account for late additions; do not rely solely on a last-24-hours field-date filter.
- Make first-run behavior configurable:
  - Default to polls published within the past seven days when publication timestamps exist.
  - Document the fallback when publication timestamps are unavailable.
- Save state only after SES accepts the email.
- Guard against overlapping runs.
- Document the remaining duplicate-email risk when sending succeeds but saving state fails.

## Email Content
Generate HTML and plain-text versions, grouped by race or topic.

Include every new poll with these fields when available:
- Pollster
- Geography and race or topic
- Field dates
- Sample size
- Surveyed population
- Candidate or response percentages
- Source link

Additional requirements:
- Calculate candidate margins deterministically when appropriate.
- Omit unavailable information without guessing.
- Escape API-provided text in HTML.
- Send a short “No new polls” email when a successful fetch finds none.
- Use one configurable recipient.

## AWS Infrastructure
Provide AWS SAM infrastructure for:
- Lambda
- EventBridge Scheduler
- A private S3 bucket
- Least-privilege IAM roles

### Schedule
- **Default time:** 8:00 a.m. daily
- **Timezone:** `America/New_York`
- **Cron expression:** `cron(0 8 * * ? *)`
- **Flexible time window:** Disabled
- Handle daylight saving time through the timezone setting.

### Configuration and Security
- Make sender, recipient, schedule, timezone, and API configuration configurable.
- Store API credentials securely, such as in SSM Parameter Store SecureString.
- Never commit or log secrets.
- Include useful CloudWatch logging and reasonable timeout/retry settings.
- Explain SES sender and recipient verification, including personal use within the SES sandbox.

## Deliverables
- Working Python source organized into:
  - API fetching
  - Poll normalization
  - State management
  - Digest rendering
  - Email delivery
- AWS SAM deployment template.
- Dependency configuration.
- `.gitignore`.
- Configuration examples without secrets.
- Clearly labeled sample fixtures for development without API access.
- A local dry-run command that fetches and renders a preview without sending email or changing production state.

## Testing
Write focused tests covering:
- Pagination
- Deduplication
- Late additions
- Empty results
- HTML escaping
- API failures
- Email send failures without advancing state

Run the tests and fix failures.

## README Requirements
Provide concise instructions with exact commands for:
1. Local setup and configuration
2. Running tests
3. Generating a local dry-run preview
4. Verifying SES identities
5. Deploying with AWS SAM
6. Manually invoking the deployed application

## Completion Report
State:
- What was implemented
- What was tested and the results
- Any API information or configuration still required

Keep the implementation proportionate to a small personal project.