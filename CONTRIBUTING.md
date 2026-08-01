# Contributing

Create a focused branch and pull request for each change.

## Validation

```bash
python -m pip install -r backend/requirements-test.txt
python -m pytest backend/tests tests -q

cd frontend
npm ci
npm run lint
npm test
npm run build
```

## Security and regulated data

- Use synthetic data only. Never commit PHI, credentials, tokens, private
  keys, production logs, corpus exports, prompts, responses, or screenshots.
- Authentication, authorization, audit, corpus ingestion, model/provider,
  external data-flow, and deployment changes require code-owner and security
  review.
- Document configuration, deployment, rollback, privacy impact, and residual
  risk in the pull request.
- Do not make compliance or clinical claims without current evidence, defined
  scope, and owner approval.

Automated checks are required but do not replace security, privacy, clinical,
or compliance review.
