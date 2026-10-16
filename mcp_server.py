"""Read-only SQLite tools following the MCP tool-boundary pattern.

This module is intentionally in-process (as specified by the assignment): the
FastAPI agent can only access SQLite through these narrow, read-only methods.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any


class MCPDatabaseServer:
    """Expose safe schema discovery and SELECT-only query execution."""

    ALLOWED_TABLES = {"customers", "orders", "products", "order_items"}

    def __init__(self, database_url: str | None = None) -> None:
        database_url = database_url or os.getenv("DATABASE_URL", "sqlite:///./data/sales.db")
        if not database_url.startswith("sqlite:///"):
            raise ValueError("Only SQLite DATABASE_URL values are supported")
        raw_path = database_url[len("sqlite:///"):]
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        self.db_path = path.resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(
                f"SQLite database not found at {self.db_path}. Ensure data/sales.db exists."
            )

    def _connect(self) -> sqlite3.Connection:
        # SQLite URI mode=ro enforces read-only access at the database layer too.
        uri = self.db_path.as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    def list_tables(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE ? ORDER BY name",
                ("table", "sqlite_%"),
            ).fetchall()
        return [row["name"] for row in rows]

    def describe_schema(self, table_name: str) -> dict[str, Any]:
        if table_name not in self.ALLOWED_TABLES:
            raise ValueError(f"Unknown or disallowed table: {table_name}")
        with self._connect() as conn:
            rows = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        if not rows:
            raise ValueError(f"Table does not exist: {table_name}")
        return {
            "table": table_name,
            "columns": [
                {"name": row["name"], "type": row["type"], "nullable": not bool(row["notnull"])}
                for row in rows
            ],
        }

    @staticmethod
    def _validate_select(sql: str) -> str:
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("SQL query must be a non-empty string")
        # Remove leading SQL comments before validating the first keyword.
        cleaned = sql.strip()
        cleaned = re.sub(r"\A(?:\s|--[^\n]*(?:\n|$)|/\*.*?\*/)*", "", cleaned, flags=re.S)
        if not re.match(r"(?is)^SELECT\b", cleaned):
            raise PermissionError("Security violation: only SELECT statements are allowed")
        # Permit one optional trailing semicolon, never multiple statements.
        body = cleaned[:-1].rstrip() if cleaned.endswith(";") else cleaned
        if ";" in body:
            raise PermissionError("Security violation: multiple SQL statements are not allowed")
        # Block dangerous or side-effecting SQLite constructs defensively.
        if re.search(r"(?is)\b(ATTACH|DETACH|PRAGMA|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|VACUUM|LOAD_EXTENSION)\b", body):
            raise PermissionError("Security violation: unsafe SQL keyword detected")
        return body

    def execute_query(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[dict[str, Any]]:
        safe_sql = self._validate_select(sql)
        with self._connect() as conn:
            cursor = conn.execute(safe_sql, params)
            return [dict(row) for row in cursor.fetchall()]
