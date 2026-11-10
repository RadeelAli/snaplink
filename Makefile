.PHONY: install run test lint format typecheck check docker

install:
	pip install -e ".[dev]"

run:
	uvicorn app.main:create_app --factory --reload

test:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check .

format:
	ruff format . && ruff check --fix .

typecheck:
	mypy

check: lint typecheck test

docker:
	docker compose up --build
