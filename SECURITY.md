# Security Policy

## Supported code

The `main` branch is the only supported line. This repository is a non-PHI
demonstration until a deployment has passed documented security, privacy,
infrastructure, vendor, and compliance review.

## Report a vulnerability

Do not open a public issue. Report suspected vulnerabilities privately to
`cvassar@nehpsychiatry.com` or through GitHub private vulnerability reporting
when enabled.

Include the repository and commit, affected component, impact, safe
reproduction steps, and any proposed mitigation. Do not include PHI,
production credentials, tokens, private keys, corpus content, prompts,
responses, or sensitive logs. Use synthetic evidence and coordinate a secure
transfer if more material is required.

We aim to acknowledge a report within two business days and provide a triage
update within five business days.

## Production boundary

- Production must set `APP_ENV=production`; startup fails unless Cloudflare
  Access, a unique audit salt, an Anthropic key, and explicit HTTPS origins are
  configured.
- Do not process PHI until every vendor and host in the data path is covered by
  the required agreement and the deployment has written approval.
- Secrets belong in an approved secret manager, never Git, client-side code,
  build logs, corpus files, or workflow artifacts.
- Audit records must not contain raw prompts, responses, or source content.
- Passing tests does not constitute HIPAA, SOC 2, HITRUST, clinical, or
  production approval.
