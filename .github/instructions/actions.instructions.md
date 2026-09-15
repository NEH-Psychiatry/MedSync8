---
applyTo: ".github/workflows/**/*.yml,.github/workflows/**/*.yaml"
---

# GitHub Actions Rules

- Declare explicit least-privilege `permissions` on every workflow, or per job. Default deny; grant only what the job uses.
- Pin every new or changed third-party action to a full-length commit SHA with a version comment, e.g. `uses: actions/checkout@8f4b7f84864484a7bf31766abe9204da3cbe65b3 # v4.1.1`.
- Never use `pull_request_target` unless the task explicitly requires it and a human reviewer is named; never check out or execute untrusted PR code in a privileged context.
- Quote and validate all inputs interpolated into `run:` steps. Prefer environment variables over inline `${{ }}` interpolation in shell.
- Secrets: reference only via `secrets.*`. Deployment secrets (`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, PyPI publish credentials) belong in protected environments with required reviewers. Never echo secrets; never write them to artifacts or logs.
- Prefer OIDC federation over long-lived cloud credentials (the PyPI publish workflow should use trusted publishing).
- Set `timeout-minutes` on every job. Add `concurrency` groups to cancel superseded runs on PR branches.
- Any workflow that deploys (Cloudflare Pages, PyPI) requires environment protection rules and a rollback note in the PR.
- New or changed workflows must be listed in the PR description with a one-line purpose statement.
