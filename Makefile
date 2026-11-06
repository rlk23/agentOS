.PHONY: install db test-db migrate dev test lint stop

install:
	uv sync --locked

db:
	docker compose -f infra/docker-compose.yml up -d --wait postgres

test-db:
	docker compose -f infra/docker-compose.yml --profile test up -d --wait postgres-test

migrate:
	uv run alembic upgrade head

dev:
	uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000 --reload

test: test-db
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

stop:
	docker compose -f infra/docker-compose.yml --profile test stop
