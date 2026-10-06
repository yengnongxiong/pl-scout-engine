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

check: lint typecheck test web-check

.PHONY: web-install web-check api-types contract

web-install:
	cd web && npm ci

web-check:
	cd web && npm run lint && npm run typecheck && npm run test && npm run build

api-types:
	uv run scout export-openapi && cd web && npm run gen:api

contract: api-types
	git diff --exit-code -- web/openapi.json web/src/api/schema.d.ts
