# Convenience wrapper. Everything here is a plain docker/compose command --
# on Windows without make, run the command shown under each target.

.PHONY: up down logs migrate seed test lint fmt loadtest

up:            ## Build and run API + PostGIS + Redis
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f api

migrate:
	docker compose run --rm api alembic upgrade head

seed:          ## Load data/places/*.yaml into the database
	docker compose run --rm api python -m ingestion.load

build-seed:    ## Re-fetch OSM coords + Wikipedia stories, rewrite data/places
	python -m ingestion.build_seed

test:
	docker compose up -d db cache
	TEST_DATABASE_URL=postgresql+asyncpg://places:places@localhost:55432/places_test \
	TEST_REDIS_URL=redis://localhost:56379/1 \
	pytest -q

lint:
	ruff check .
	ruff format --check .

fmt:
	ruff format .
	ruff check --fix .

loadtest:
	python scripts/loadtest.py
