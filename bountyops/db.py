from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Program, ScopeItem, Notice, Restriction, BurpImport, Endpoint, now_iso


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL DEFAULT '',
    reward_min INTEGER NOT NULL DEFAULT 0,
    reward_max INTEGER NOT NULL DEFAULT 0,
    source_code INTEGER NOT NULL DEFAULT 0,
    has_time_limit INTEGER NOT NULL DEFAULT 0,
    time_limit_note TEXT NOT NULL DEFAULT '',
    policy_url TEXT NOT NULL DEFAULT '',
    discord_thread_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scope_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('in', 'out')),
    value TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(program_id, type, value),
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS restrictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    text TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS burp_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    format TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    sanitized_path TEXT NOT NULL,
    total_items INTEGER NOT NULL DEFAULT 0,
    in_scope_items INTEGER NOT NULL DEFAULT 0,
    out_scope_items INTEGER NOT NULL DEFAULT 0,
    unknown_scope_items INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS endpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    import_id INTEGER NOT NULL,
    method TEXT NOT NULL,
    scheme TEXT NOT NULL DEFAULT '',
    host TEXT NOT NULL,
    port INTEGER,
    path TEXT NOT NULL DEFAULT '/',
    query_keys TEXT NOT NULL DEFAULT '',
    status_code INTEGER,
    content_type TEXT NOT NULL DEFAULT '',
    auth_present INTEGER NOT NULL DEFAULT 0,
    state_changing INTEGER NOT NULL DEFAULT 0,
    scope_status TEXT NOT NULL CHECK(scope_status IN ('in', 'out', 'unknown')),
    interesting_score INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE,
    FOREIGN KEY(import_id) REFERENCES burp_imports(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_endpoints_program_scope ON endpoints(program_id, scope_status);
CREATE INDEX IF NOT EXISTS idx_endpoints_host_path ON endpoints(host, path);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def init(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def add_program(
        self,
        *,
        name: str,
        platform: str,
        reward_min: int,
        reward_max: int,
        source_code: bool,
        has_time_limit: bool,
        time_limit_note: str,
        policy_url: str,
    ) -> Program:
        cur = self.conn.execute(
            """
            INSERT INTO programs
            (name, platform, reward_min, reward_max, source_code, has_time_limit, time_limit_note, policy_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                platform.strip(),
                max(0, reward_min),
                max(0, reward_max),
                int(source_code),
                int(has_time_limit),
                time_limit_note.strip(),
                policy_url.strip(),
                now_iso(),
            ),
        )
        self.conn.commit()
        return self.get_program_by_id(cur.lastrowid)

    def set_program_thread(self, program_id: int, thread_id: int) -> None:
        self.conn.execute(
            "UPDATE programs SET discord_thread_id=? WHERE id=?",
            (thread_id, program_id),
        )
        self.conn.commit()

    def get_program_by_id(self, program_id: int) -> Program:
        row = self.conn.execute("SELECT * FROM programs WHERE id=?", (program_id,)).fetchone()
        if not row:
            raise KeyError(f"program id not found: {program_id}")
        return self._row_to_program(row)

    def get_program_by_name(self, name: str) -> Program | None:
        row = self.conn.execute(
            "SELECT * FROM programs WHERE lower(name)=lower(?)",
            (name.strip(),),
        ).fetchone()
        return self._row_to_program(row) if row else None

    def list_programs(self) -> list[Program]:
        rows = self.conn.execute("SELECT * FROM programs ORDER BY name COLLATE NOCASE ASC").fetchall()
        return [self._row_to_program(row) for row in rows]

    def add_scope_item(
        self,
        *,
        program_id: int,
        type: str,
        value: str,
        note: str,
        source_url: str,
    ) -> ScopeItem:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO scope_items
            (program_id, type, value, note, source_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (program_id, type, value.strip(), note.strip(), source_url.strip(), now_iso()),
        )
        self.conn.commit()

        row = self.conn.execute(
            """
            SELECT * FROM scope_items
            WHERE program_id=? AND type=? AND value=?
            """,
            (program_id, type, value.strip()),
        ).fetchone()
        return self._row_to_scope(row)

    def list_scope_items(self, program_id: int, type: str | None = None) -> list[ScopeItem]:
        if type:
            rows = self.conn.execute(
                "SELECT * FROM scope_items WHERE program_id=? AND type=? ORDER BY value ASC",
                (program_id, type),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM scope_items WHERE program_id=? ORDER BY type ASC, value ASC",
                (program_id,),
            ).fetchall()
        return [self._row_to_scope(row) for row in rows]

    def count_in_scope(self, program_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM scope_items WHERE program_id=? AND type='in'",
            (program_id,),
        ).fetchone()
        return int(row["c"])

    def add_notice(self, *, program_id: int, title: str, summary: str, source_url: str) -> Notice:
        cur = self.conn.execute(
            """
            INSERT INTO notices
            (program_id, title, summary, source_url, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (program_id, title.strip(), summary.strip(), source_url.strip(), now_iso()),
        )
        self.conn.commit()
        return self.get_notice(cur.lastrowid)

    def list_notices(self, program_id: int, limit: int = 5) -> list[Notice]:
        rows = self.conn.execute(
            "SELECT * FROM notices WHERE program_id=? ORDER BY id DESC LIMIT ?",
            (program_id, limit),
        ).fetchall()
        return [self._row_to_notice(row) for row in rows]

    def get_notice(self, notice_id: int) -> Notice:
        row = self.conn.execute("SELECT * FROM notices WHERE id=?", (notice_id,)).fetchone()
        if not row:
            raise KeyError(f"notice id not found: {notice_id}")
        return self._row_to_notice(row)

    def add_restriction(self, *, program_id: int, severity: str, text: str, source_url: str) -> Restriction:
        cur = self.conn.execute(
            """
            INSERT INTO restrictions
            (program_id, severity, text, source_url, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (program_id, severity.strip().lower(), text.strip(), source_url.strip(), now_iso()),
        )
        self.conn.commit()
        return self.get_restriction(cur.lastrowid)

    def list_restrictions(self, program_id: int, limit: int = 10) -> list[Restriction]:
        rows = self.conn.execute(
            "SELECT * FROM restrictions WHERE program_id=? ORDER BY id DESC LIMIT ?",
            (program_id, limit),
        ).fetchall()
        return [self._row_to_restriction(row) for row in rows]

    def get_restriction(self, restriction_id: int) -> Restriction:
        row = self.conn.execute("SELECT * FROM restrictions WHERE id=?", (restriction_id,)).fetchone()
        if not row:
            raise KeyError(f"restriction id not found: {restriction_id}")
        return self._row_to_restriction(row)

    def add_burp_import(
        self,
        *,
        program_id: int,
        filename: str,
        format: str,
        raw_path: str,
        sanitized_path: str,
        total_items: int,
        in_scope_items: int,
        out_scope_items: int,
        unknown_scope_items: int,
    ) -> BurpImport:
        cur = self.conn.execute(
            """
            INSERT INTO burp_imports
            (program_id, filename, format, raw_path, sanitized_path, total_items, in_scope_items, out_scope_items, unknown_scope_items, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                program_id,
                filename,
                format,
                raw_path,
                sanitized_path,
                total_items,
                in_scope_items,
                out_scope_items,
                unknown_scope_items,
                now_iso(),
            ),
        )
        self.conn.commit()
        return self.get_burp_import(cur.lastrowid)

    def get_burp_import(self, import_id: int) -> BurpImport:
        row = self.conn.execute("SELECT * FROM burp_imports WHERE id=?", (import_id,)).fetchone()
        if not row:
            raise KeyError(f"import id not found: {import_id}")
        return self._row_to_burp_import(row)

    def list_burp_imports(self, program_id: int, limit: int = 10) -> list[BurpImport]:
        rows = self.conn.execute(
            "SELECT * FROM burp_imports WHERE program_id=? ORDER BY id DESC LIMIT ?",
            (program_id, limit),
        ).fetchall()
        return [self._row_to_burp_import(row) for row in rows]

    def add_endpoint(
        self,
        *,
        program_id: int,
        import_id: int,
        method: str,
        scheme: str,
        host: str,
        port: int | None,
        path: str,
        query_keys: str,
        status_code: int | None,
        content_type: str,
        auth_present: bool,
        state_changing: bool,
        scope_status: str,
        interesting_score: int,
    ) -> Endpoint:
        cur = self.conn.execute(
            """
            INSERT INTO endpoints
            (program_id, import_id, method, scheme, host, port, path, query_keys, status_code, content_type,
             auth_present, state_changing, scope_status, interesting_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                program_id,
                import_id,
                method,
                scheme,
                host,
                port,
                path,
                query_keys,
                status_code,
                content_type,
                int(auth_present),
                int(state_changing),
                scope_status,
                interesting_score,
                now_iso(),
            ),
        )
        self.conn.commit()
        return self.get_endpoint(cur.lastrowid)

    def get_endpoint(self, endpoint_id: int) -> Endpoint:
        row = self.conn.execute("SELECT * FROM endpoints WHERE id=?", (endpoint_id,)).fetchone()
        if not row:
            raise KeyError(f"endpoint id not found: {endpoint_id}")
        return self._row_to_endpoint(row)

    def list_endpoints(
        self,
        *,
        program_id: int,
        scope_filter: str = "all",
        limit: int = 20,
    ) -> list[Endpoint]:
        if scope_filter in {"in", "out", "unknown"}:
            rows = self.conn.execute(
                """
                SELECT * FROM endpoints
                WHERE program_id=? AND scope_status=?
                ORDER BY interesting_score DESC, id DESC
                LIMIT ?
                """,
                (program_id, scope_filter, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM endpoints
                WHERE program_id=?
                ORDER BY interesting_score DESC, id DESC
                LIMIT ?
                """,
                (program_id, limit),
            ).fetchall()
        return [self._row_to_endpoint(row) for row in rows]

    def count_endpoints(self, program_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM endpoints WHERE program_id=?",
            (program_id,),
        ).fetchone()
        return int(row["c"])

    def count_imports(self, program_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM burp_imports WHERE program_id=?",
            (program_id,),
        ).fetchone()
        return int(row["c"])

    @staticmethod
    def _row_to_program(row: sqlite3.Row) -> Program:
        return Program(
            id=int(row["id"]),
            name=str(row["name"]),
            platform=str(row["platform"]),
            reward_min=int(row["reward_min"]),
            reward_max=int(row["reward_max"]),
            source_code=bool(row["source_code"]),
            has_time_limit=bool(row["has_time_limit"]),
            time_limit_note=str(row["time_limit_note"]),
            policy_url=str(row["policy_url"]),
            discord_thread_id=int(row["discord_thread_id"]) if row["discord_thread_id"] else None,
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_to_scope(row: sqlite3.Row) -> ScopeItem:
        return ScopeItem(
            id=int(row["id"]),
            program_id=int(row["program_id"]),
            type=str(row["type"]),
            value=str(row["value"]),
            note=str(row["note"]),
            source_url=str(row["source_url"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_to_notice(row: sqlite3.Row) -> Notice:
        return Notice(
            id=int(row["id"]),
            program_id=int(row["program_id"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            source_url=str(row["source_url"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_to_restriction(row: sqlite3.Row) -> Restriction:
        return Restriction(
            id=int(row["id"]),
            program_id=int(row["program_id"]),
            severity=str(row["severity"]),
            text=str(row["text"]),
            source_url=str(row["source_url"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_to_burp_import(row: sqlite3.Row) -> BurpImport:
        return BurpImport(
            id=int(row["id"]),
            program_id=int(row["program_id"]),
            filename=str(row["filename"]),
            format=str(row["format"]),
            raw_path=str(row["raw_path"]),
            sanitized_path=str(row["sanitized_path"]),
            total_items=int(row["total_items"]),
            in_scope_items=int(row["in_scope_items"]),
            out_scope_items=int(row["out_scope_items"]),
            unknown_scope_items=int(row["unknown_scope_items"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _row_to_endpoint(row: sqlite3.Row) -> Endpoint:
        return Endpoint(
            id=int(row["id"]),
            program_id=int(row["program_id"]),
            import_id=int(row["import_id"]),
            method=str(row["method"]),
            scheme=str(row["scheme"]),
            host=str(row["host"]),
            port=int(row["port"]) if row["port"] is not None else None,
            path=str(row["path"]),
            query_keys=str(row["query_keys"]),
            status_code=int(row["status_code"]) if row["status_code"] is not None else None,
            content_type=str(row["content_type"]),
            auth_present=bool(row["auth_present"]),
            state_changing=bool(row["state_changing"]),
            scope_status=str(row["scope_status"]),
            interesting_score=int(row["interesting_score"]),
            created_at=str(row["created_at"]),
        )
