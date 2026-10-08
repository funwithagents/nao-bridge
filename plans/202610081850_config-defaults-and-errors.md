# Config defaults and errors

**Status:** Done

Implements `specs/config.md` ("Constructors and validation"): a default is declared once, on the dataclass field, and a block's validation error carries its key instead of relying on the message starting with the field name.

## Scope

- `src/nao_bridge/config.py` — `read_*` helpers take no default and fall back to the dataclass field's default (`dataclasses.fields`), or omit the keyword so the dataclass applies it; `ConfigError(message, key=...)`; `build()` prefixes `key`, never the message.
- `src/nao_bridge/nao_mcp_server.py`, `src/nao_bridge/nao_websocket_server.py` — their `parse` methods follow.
- `tests/test_config.py` — a default changed on a dataclass is the one JSON loading uses; error key paths unchanged.

## Steps

1. `ConfigError.key`; `_require(condition, key, message)`; `build()` composes `key_path(path, e.key)`.
2. A `read_field(cls, obj, name, path)` style reader that dispatches on the field's type and default; drop the default arguments from the `parse` methods.
3. Tests.

## Verification

`uv run ruff check .`, `uv run pyright`, `uv run pytest` clean; every existing `ConfigError` message in `tests/test_config.py` still matches.
