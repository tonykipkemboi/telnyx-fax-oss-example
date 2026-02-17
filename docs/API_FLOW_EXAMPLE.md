# API Flow Example (cURL)

## Prerequisites
- API is running on `http://localhost:8000`
- `jq` is installed
- Test document path is known

Set base URL:

```bash
export BASE_URL="http://localhost:8000"
```

## 1) Upload Document
```bash
UPLOAD_JSON=$(curl -s -X POST "$BASE_URL/v1/uploads" \
  -F "file=@/absolute/path/to/document.pdf")

echo "$UPLOAD_JSON" | jq
UPLOAD_ID=$(echo "$UPLOAD_JSON" | jq -r '.document_upload_id')
```

## 2) Create Fax Job (Sends Immediately)
```bash
JOB_JSON=$(curl -s -X POST "$BASE_URL/v1/fax/jobs" \
  -H "content-type: application/json" \
  -d "{\"document_upload_id\": \"$UPLOAD_ID\", \"destination_fax\": \"+13014001910\", \"destination_country\": \"US\"}")

echo "$JOB_JSON" | jq
FAX_JOB_ID=$(echo "$JOB_JSON" | jq -r '.fax_job_id')
```

## 3) Check Status
```bash
curl -s "$BASE_URL/v1/fax/jobs/$FAX_JOB_ID" | jq
```

Live poll every 3 seconds:
```bash
watch -n 3 "curl -s $BASE_URL/v1/fax/jobs/$FAX_JOB_ID | jq '{status,provider_status,failure_reason,progress_percent,progress_label,timeline}'"
```

## 4) Cancel Job (Optional)
```bash
curl -s -X POST "$BASE_URL/v1/fax/jobs/$FAX_JOB_ID/cancel" | jq
```
