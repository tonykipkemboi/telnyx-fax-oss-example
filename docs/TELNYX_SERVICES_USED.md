# Telnyx Services Used

## 1) Fax-Capable Number
A Telnyx number with fax capability is required as the outbound sender.

Mapped setting:
- `TELNYX_FAX_TELNYX_FROM_NUMBER`

## 2) Programmable Fax API Application
Create a Fax API Application in the Telnyx portal.

Mapped setting:
- `TELNYX_FAX_TELNYX_CONNECTION_ID`

## 3) Outbound Fax API
Outbound faxes are sent through the Telnyx Programmable Fax endpoint using the configured API key.

Mapped setting:
- `TELNYX_FAX_TELNYX_API_KEY`

## 4) Webhooks
Telnyx posts status callbacks to the project webhook handler:
- `POST /v1/webhooks/telnyx`

Typical outbound event chain:
- `fax.queued`
- `fax.media.processed`
- `fax.sending.started`
- `fax.delivered` or `fax.failed`

## 5) Optional Webhook Signature Verification
If enabled, incoming webhook signatures are verified using:
- `telnyx-timestamp`
- `telnyx-signature-ed25519`

Mapped setting:
- `TELNYX_FAX_TELNYX_WEBHOOK_PUBLIC_KEY`

## 6) Media Retrieval
Telnyx fetches upload files from generated public URLs.

Requirement:
- `TELNYX_FAX_BASE_URL` must be reachable and stable while a job is active.
