# Contributing

## Development Setup
```bash
cp .env.example .env
uv sync --extra dev
uv run alembic upgrade head
```

## Run Locally
```bash
make run HOST=0.0.0.0 PORT=8000
```

## Quality Gates
```bash
make lint
make test
```

## Pull Requests
- Keep changes focused and small.
- Add or update tests for behavior changes.
- Update docs when endpoint behavior or configuration changes.
- Never include secrets, API keys, or local runtime data.
