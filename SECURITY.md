# Security Policy

## Reporting a Vulnerability
Do not open a public issue for sensitive vulnerabilities.

Report privately to the repository maintainer with:
- affected endpoint(s)
- reproduction steps
- impact assessment
- suggested remediation (if available)

## Secure Defaults
- `.env` is ignored by git and should remain local.
- Enable `TELNYX_FAX_TELNYX_WEBHOOK_PUBLIC_KEY` outside local testing.
- Rotate compromised credentials immediately.
- Avoid exposing local tunnels longer than needed.
