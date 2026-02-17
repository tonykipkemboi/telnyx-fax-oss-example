# Live Runbook

## 1) Start the API
```bash
git clone https://github.com/tonykipkemboi/telnyx-fax-oss-example.git
cd telnyx-fax-oss-example
uv sync --extra dev
cp .env.example .env
make run HOST=0.0.0.0 PORT=8000
```

## 2) Tunnel local service (if running locally)
```bash
cloudflared tunnel --url http://localhost:8000
```

## 3) Set live environment
```bash
TELNYX_FAX_MOCK_PROVIDERS=false
TELNYX_FAX_BASE_URL=https://<active-tunnel>.trycloudflare.com
TELNYX_FAX_TELNYX_API_KEY=<api-key>
TELNYX_FAX_TELNYX_CONNECTION_ID=<application-id>
TELNYX_FAX_TELNYX_FROM_NUMBER=+1XXXXXXXXXX
```

Optional signature verification:
```bash
TELNYX_FAX_TELNYX_WEBHOOK_PUBLIC_KEY=<public-key>
```

## 4) Configure Telnyx webhook URL
Set to:
- `https://<active-tunnel>.trycloudflare.com/v1/webhooks/telnyx`

## 5) Execute fax flow
1. `POST /v1/uploads`
2. `POST /v1/fax/jobs`
3. Poll `GET /v1/fax/jobs/{id}`

## 6) Status meanings
- `queued_for_send`
- `sending`
- `delivered`
- `failed`
- `canceled`

## 7) Cancel if needed
- `POST /v1/fax/jobs/{id}/cancel`
