.PHONY: install test test-fast lint format typecheck typecheck-record typecheck-report build check

install:
	uv sync --extra dev

test:
	uv run python -m pytest -vv

test-fast:
	uv run python -m pytest -q

lint:
	uv run ruff check src tests scripts

format:
	uv run ruff format src tests scripts

# Enforced against a frozen baseline: the known errors pass, anything new fails. mypy is not yet
# clean over the dynamic query evaluator (union comparisons, TypedDict key-narrowing), and waiting
# for that would leave the annotations unchecked meanwhile. See .claude/status.md, Stream L.
typecheck:
	uv run python scripts/typecheck.py

# Re-record the baseline. Run this with the change that earns it, never on its own.
typecheck-record:
	uv run python scripts/typecheck.py --record

# The full error list, for reading rather than gating. --no-incremental for the reason in L6:
# an incremental run reported 66 errors against a tree a clean run reported 58 for.
typecheck-report:
	uv run python -m mypy --no-incremental

build:
	uv build

# The enforced gate: lint -> typecheck -> test.
check: lint typecheck test
