# Repository Guidelines

## Project Structure

This Python 3.13+ AWS SAM application sends a daily VoteHub poll digest. Code is
in `src/poll_brief/`: `api.py` fetches data, `polls.py` normalizes and selects
polls, `state.py` manages S3 state and leases, `render.py` creates HTML/text
email, `email.py` sends via SES, and `app.py` coordinates Lambda and previews.
Party metadata is `candidate_parties.json`. Tests and synthetic fixtures are in
`tests/`; deployment is `template.yaml`; configuration examples are in `config/`.

## Setup, Build, and Run

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e . -r requirements-dev.txt
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/ruff check src tests
.venv/Scripts/ruff format --check src tests
sam validate --template-file template.yaml --region us-east-1
sam build --template-file template.yaml
```

For a read-only fixture preview, run
`.venv/Scripts/python -m poll_brief.app --fixture tests/fixtures/synthetic-polls.json --all`.
Use `--output preview-live.html` for the live public API. Preview writes a `.txt`
companion and never calls S3 or SES.

## Style and Testing

Use four-space indentation, `snake_case` names, standard Python typing, and Ruff's
100-character limit. Add focused `unittest` cases for API errors, normalization,
selection/state behavior, party matching, and email escaping. Keep fixtures
synthetic and free of credentials or recipient data.

## Commits and Pull Requests

Use concise imperative subjects such as `Improve race ordering`. Keep commits
focused. Pull requests should explain behavior changes, link an issue when one
exists, list validation commands, and include preview screenshots for newsletter
layout changes.

## Security and Operations

Do not commit secrets, `.env` files, generated previews, `.aws-sam/`, or virtual
environments. Verify SES sender and recipient identities in the deployment region;
store optional API tokens as SSM SecureString parameters. Do not deploy AWS
resources or send real email during development. Read `README.md` before
`sam deploy` or manual Lambda invocation.
