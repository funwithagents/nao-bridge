# Broader ruff rules

**Status:** Done

Implements `specs/project.md` ("Linting/formatting"). Ruff 0.16's default rule set is already broad (bugbear, simplify, pyupgrade, ruff's own, async, pylint errors…), so this extends it with what the review found missing — pycodestyle (`E`, `W`), performance (`PERF`) and annotations (`ANN`) for `src/` — rather than replacing it.

## Scope

- `pyproject.toml` — `[tool.ruff.lint] extend-select = ["E", "W", "PERF", "ANN"]`, `ignore = ["E501"]` (the formatter owns line length), `ANN` applied to `src/` only via `per-file-ignores` for `tests/` and `tests-e2e/`.
- `src/nao_bridge/*.py`, `tests/**` — whatever the new rules flag.

## Steps

1. Add the config; run `uv run ruff check .`.
2. Fix findings by hand (unannotated signatures in `src/`, `not in`, manual list comprehensions); keep `noqa` only with a reason.

## Verification

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, `uv run pytest` clean.
