.PHONY: install lint format typecheck test check

install:
	uv sync --all-extras

lint:
	uv run ruff check . && uv run ruff format --check .

format:
	uv run ruff format . && uv run ruff check --fix .

typecheck:
	uv run mypy src

test:
	uv run pytest --cov=scout

check: lint typecheck test
