"""The Python column lists and the TypeScript module must declare the same tables and reducers.

The module cannot be run here without the `spacetime` CLI, so this reads spacetimedb/src/index.ts
and checks it against the Python side. A mismatch would silently misfile every column.
"""

import re
from pathlib import Path

from bellhop.adapters import spacetimedb_data as data
from bellhop.adapters import spacetimedb_store as core

from .stdb_fake import DELETE, UPSERT, columns

SOURCE = (Path(__file__).resolve().parents[3] / "spacetimedb" / "src" / "index.ts").read_text()
NAMES = re.compile(r"(\w+): t\.")


def balanced(text: str, start: int) -> tuple[str, int]:
    """The `{...}` object starting at `start` and the index after it (comments stripped)."""
    depth = 0
    for i in range(start, len(text)):
        depth += text[i] == "{"
        depth -= text[i] == "}"
        if depth == 0:
            return re.sub(r"//[^\n]*", "", text[start : i + 1]), i + 1
    raise AssertionError("unbalanced braces")


def declared_tables() -> dict[str, list[str]]:
    out = {}
    for m in re.finditer(r"table\(\s*\{ name: '(\w+)'", SOURCE):
        _, after_options = balanced(SOURCE, m.start() + SOURCE[m.start() :].index("{"))
        columns_obj, _ = balanced(SOURCE, SOURCE.index("{", after_options))
        out[m.group(1)] = NAMES.findall(columns_obj)
    return out


def declared_reducers() -> dict[str, list[str]]:
    out = {}
    for m in re.finditer(r"export const (\w+) = spacetimedb\.reducer\(\s*", SOURCE):
        args, _ = balanced(SOURCE, m.end())
        out[m.group(1)] = NAMES.findall(args)
    return out


def test_every_python_table_is_declared_with_the_same_columns_in_the_same_order():
    tables = declared_tables()
    for table in [*core.COLUMNS, *data.DATA_COLUMNS]:
        assert table in tables, f"table {table} missing from index.ts"
        assert tables[table] == list(columns(table)), table


def test_the_module_has_no_table_the_python_side_ignores():
    python = {*core.COLUMNS, *data.DATA_COLUMNS, "call_turn"}
    assert set(declared_tables()) == python


def test_every_save_reducer_takes_the_table_columns_in_order():
    reducers = declared_reducers()
    for reducer, table in UPSERT.items():
        assert reducer in reducers, f"reducer {reducer} missing from index.ts"
        assert reducers[reducer] == list(columns(table)), reducer


def test_every_delete_reducer_exists():
    reducers = declared_reducers()
    for reducer in [*DELETE, "delete_resident_memory", "append_turn"]:
        assert reducer in reducers, reducer
    assert reducers["delete_resident_memory"] == ["resident_id"]
