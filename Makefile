.PHONY: install test test-fast lint typecheck build check

install:
	uv sync --extra dev

test:
	uv run python -m pytest -vv

test-fast:
	uv run python -m pytest -q

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

# Advisory: mypy is configured for parity but not yet clean over the dynamic
# query evaluator (union comparisons, TypedDict key-narrowing). See BACKLOG.md.
typecheck:
	uv run mypy

build:
	uv build

# The enforced gate: lint -> test.
check: lint test
