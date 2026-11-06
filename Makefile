.PHONY: install db test-db migrate dev dispatcher worker test lint stop

install:
	uv sync --locked

db:
	docker compose -f infra/docker-compose.yml up -d --wait postgres redis

test-db:
	docker compose -f infra/docker-compose.yml --profile test up -d --wait postgres-test redis-test

migrate:
	uv run alembic upgrade head

dev:
	uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000 --reload

dispatcher:
	uv run python -m apps.worker.app.main dispatcher

worker:
	uv run python -m apps.worker.app.main worker

test: test-db
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

stop:
	docker compose -f infra/docker-compose.yml --profile test stop
