---
applyTo: ".github/workflows/**/*.yml,.github/workflows/**/*.yaml"
---

# GitHub Actions Rules

- Declare explicit least-privilege `permissions` on every workflow, or per job. Default deny; grant only what the job uses (`deploy-azure.yml` needs `packages: write` for GHCR; nothing else does).
- Pin every third-party action to a full-length commit SHA with a version comment, e.g. `uses: actions/checkout@8f4b7f84864484a7bf31766abe9204da3cbe65b3 # v4.1.1`. Dependabot (`.github/dependabot.yml`) bumps pins weekly; never revert a pin to a floating tag.
- Never use `pull_request_target` unless the task explicitly requires it and a human reviewer is named; never check out or execute untrusted PR code in a privileged context.
- Quote and validate all inputs interpolated into `run:` steps. Prefer environment variables over inline `${{ }}` interpolation in shell.
- Secrets (`AZURE_CREDENTIALS`, `ANTHROPIC_API_KEY`, `AUDIT_SALT`, `GHCR_PULL_TOKEN`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, PyPI publish credentials): reference only via `secrets.*` in protected environments with required reviewers. Never echo secrets; never write them to artifacts or logs.
- Prefer OIDC federation over long-lived cloud credentials (the PyPI publish workflow should use trusted publishing); the Azure service principal in `AZURE_CREDENTIALS` is the current exception — do not widen its scope beyond the resource group.
- Set `timeout-minutes` on every job. Add `concurrency` groups to cancel superseded runs on PR branches.
- Any workflow that deploys (Azure Container Apps via `deploy-azure.yml`, Cloudflare Pages via `deploy-pages.yml`, PyPI) requires environment protection rules and a rollback note in the PR. `deploy-azure.yml` deploys production and is gated by the `production` environment.
- CI (`ci.yml`) runs three jobs — Python (`pytest backend/tests tests`), workbench build, frontend lint/test/build; do not drop a job or make lint conditional (`--if-present`) to get a green run.
- New or changed workflows must be listed in the PR description with a one-line purpose statement.
