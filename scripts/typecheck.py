"""Run mypy and compare it against a frozen baseline, so the annotations are bound today.

Stream L's premise is that until `typecheck` is clean nothing checks the type annotations, so they
drift exactly like prose does -- and L1, L2 and L4 all entered that way, as a claim on a surface
nothing was watching. Waiting for a clean run defers the binding indefinitely. A baseline binds it
now: the known errors pass, anything new fails, and `typecheck` can sit in `make check` and CI
without the model work being finished first.

Two rules, and the second matters as much as the first:

- A **new** error fails. That is the guard.
- A **fixed** error also fails, asking for the baseline to be re-recorded. This repo has now carried
  a wrong error count three times (`.claude/status.md`, L6), and a baseline that silently absorbs
  improvements would be the fourth mechanism for it. Re-recording is one command, and it makes the
  shrink visible in the diff, which is the evidence a model change was worth making.

An error's identity is its **file, code and message**, never its line number, so moving code around
does not churn the baseline. Two identical errors in one file count as two entries.

mypy runs with `--no-incremental`. An incremental run reported 66 errors against a tree a clean run
reported 58 for, including two against a signature that had already been fixed, and nothing in the
output distinguishes the two runs. The flag removes that failure mode rather than asking a reader
to remember it. A clean run of this project costs about 2.5 seconds.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "scripts" / "mypy-baseline.txt"

# `src/esql/parser/util.py:285: error: Need type annotation for "groups"  [var-annotated]`
ERROR_LINE = re.compile(r"^(?P<file>[^:]+):\d+: error: (?P<message>.*?)(?:\s+\[(?P<code>[a-z-]+)\])?$")


def _run_mypy() -> str:
    result = subprocess.run(
        ["python", "-m", "mypy", "--no-incremental", "--no-error-summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        # Anything other than "clean" or "found errors" is the tool failing to run, which is how the
        # count went stale for months before v1.5.0. It must not be read as zero errors.
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit(f"mypy exited {result.returncode} without checking. See above.")
    return result.stdout


def _signatures(mypy_output: str) -> Counter[str]:
    """One entry per error: file, code and message, with the line number dropped."""
    signatures: Counter[str] = Counter()
    for line in mypy_output.splitlines():
        match = ERROR_LINE.match(line.strip())
        if match:
            path = match["file"].replace("\\", "/")
            signatures[f"{path}\t{match['code'] or '-'}\t{match['message']}"] += 1
    return signatures


def _read_baseline() -> Counter[str]:
    if not BASELINE.exists():
        return Counter()
    lines = BASELINE.read_text(encoding="utf-8").splitlines()
    return Counter(line for line in lines if line and not line.startswith("#"))


def _write_baseline(signatures: Counter[str]) -> None:
    header = [
        "# Frozen mypy baseline. Every line is one known error: file, code, message.",
        "# Line numbers are deliberately absent, so moving code does not churn this file.",
        "# Regenerate with `make typecheck-record`, and only alongside the change that earns it.",
        f"# {sum(signatures.values())} errors.",
    ]
    body = sorted(line for line, count in signatures.items() for _ in range(count))
    BASELINE.write_text("\n".join([*header, *body]) + "\n", encoding="utf-8")


def _describe(signature: str) -> str:
    path, code, message = signature.split("\t")
    return f"  {path}  [{code}]  {message}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="rewrite the baseline from this run")
    args = parser.parse_args()

    current = _signatures(_run_mypy())

    if args.record:
        _write_baseline(current)
        print(f"Recorded {sum(current.values())} errors to {BASELINE.relative_to(REPO_ROOT)}.")
        return 0

    baseline = _read_baseline()
    added = current - baseline
    removed = baseline - current

    if added:
        print(f"{sum(added.values())} type error(s) not in the baseline:")
        for signature in sorted(added):
            print(_describe(signature))
    if removed:
        print(f"{sum(removed.values())} baselined type error(s) no longer reported:")
        for signature in sorted(removed):
            print(_describe(signature))
        print("\nFixed, or moved? Either way the baseline is now a wrong count. Run `make typecheck-record`.")

    if added or removed:
        return 1

    print(f"mypy: {sum(current.values())} known errors, none new. Baseline matches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
