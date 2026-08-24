# Security and privacy boundary

## Implemented controls

- Input models reject unknown fields and constrain identifiers, list length and text length.
- Tools are server-owned and allowlisted. No endpoint accepts SQL, shell commands, Python, filesystem paths or destination URLs.
- Database statements are parameterized. The browser never receives a credential.
- High-risk or incomplete conclusions pause at a human gate.
- Citations must be members of evidence returned by the current run's tools.
- Unknown tool errors fail closed and expose only the error class, not a stack trace.
- `.env`, databases, raw datasets, generated outputs and common credential file types are ignored or blocked by the privacy scan.

## Demo identity warning

`X-Demo-User` is deliberately visible and switchable in the local UI. It is not authentication and must never be exposed on a shared or public deployment. A real service requires verified OIDC/OAuth2 tokens, organization membership, collection-level authorization and immutable security audit storage.

## Threats not solved in v1

- The local database is not encrypted at rest.
- SOP content is trusted project data; there is no document-ingestion quarantine or malware scan.
- There is no tenant boundary, row-level security, rate limit or WAF.
- The example Kubernetes deployment uses a single replica and local persistent volume semantics.
- Browser output is escaped in the UI, but a formal penetration test has not been performed.
