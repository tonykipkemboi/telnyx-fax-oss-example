# Implementation Steps (Simple)

This guide is the shortest path from zero to a real fax send.

## 1) Telnyx Prerequisites
1. Buy or assign one fax-capable Telnyx number.
2. Create one Telnyx Fax API Application.
3. Copy:
- API key
- Fax API Application ID
- Fax-capable sender number

## 2) Local Project Setup
1. Create env file:
```bash
cp .env.example .env
```
2. Add required live values to `.env`:
```bash
TELNYX_FAX_MOCK_PROVIDERS=false
TELNYX_FAX_TELNYX_API_KEY=<telnyx-api-key>
TELNYX_FAX_TELNYX_CONNECTION_ID=<fax-api-application-id>
TELNYX_FAX_TELNYX_FROM_NUMBER=+1XXXXXXXXXX
```
3. Install dependencies and migrate database:
```bash
uv sync --extra dev
uv run alembic upgrade head
```

## 3) Make Service Public (Local Testing)
If API is running on a laptop/local machine, expose it with a tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

Set in `.env`:
```bash
TELNYX_FAX_BASE_URL=https://<active-tunnel>.trycloudflare.com
```

Set the Telnyx webhook URL to:
```text
https://<active-tunnel>.trycloudflare.com/v1/webhooks/telnyx
```

## 4) Start Service
```bash
make run HOST=0.0.0.0 PORT=8000
```

## 5) Send a Fax
Run the exact cURL sequence in `docs/API_FLOW_EXAMPLE.md`:
1. Upload document
2. Create fax job
3. Poll status
4. Cancel (optional)

## 6) Confirm Result
Treat as delivered when all are true:
- Job status is `delivered`
- Provider status chain includes `fax.delivered`
- `provider_job_id` is present

## 7) Common Errors
- `unverified_destination_not_allowed`: destination restrictions on account.
- `file_download_failed`: Telnyx cannot fetch file URL (tunnel down or unreachable base URL).
