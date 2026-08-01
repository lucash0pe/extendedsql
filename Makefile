.PHONY: install test test-fast lint format typecheck build check

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

# Enforced, and clean: any error at all fails. --no-incremental because an incremental run reported
# 66 errors against a tree a clean run reported 58 for, and nothing in the output tells the two
# apart. A clean run costs about 2.5 seconds. See .claude/status.md, Stream L.
typecheck:
	uv run python -m mypy --no-incremental

build:
	uv build

# The enforced gate: lint -> typecheck -> test.
check: lint typecheck test
