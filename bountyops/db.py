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
    discord_category_id INTEGER,
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


CREATE TABLE IF NOT EXISTS site_crawls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    input_value TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    suggested_name TEXT NOT NULL DEFAULT '',
    reward_max INTEGER NOT NULL DEFAULT 0,
    source_code INTEGER NOT NULL DEFAULT 0,
    has_time_limit INTEGER NOT NULL DEFAULT 0,
    time_limit_note TEXT NOT NULL DEFAULT '',
    in_scope_json TEXT NOT NULL DEFAULT '[]',
    out_scope_json TEXT NOT NULL DEFAULT '[]',
    restrictions_json TEXT NOT NULL DEFAULT '[]',
    notices_json TEXT NOT NULL DEFAULT '[]',
    raw_path TEXT NOT NULL DEFAULT '',
    parsed_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    applied_program_id INTEGER,
    created_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    evidence_type TEXT NOT NULL DEFAULT 'note',
    note TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS report_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    vuln_type TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate',
    severity TEXT NOT NULL DEFAULT 'unknown',
    endpoint_id INTEGER,
    summary TEXT NOT NULL DEFAULT '',
    impact TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS finding_evidence (
    finding_id INTEGER NOT NULL,
    evidence_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(finding_id, evidence_id),
    FOREIGN KEY(finding_id) REFERENCES findings(id) ON DELETE CASCADE,
    FOREIGN KEY(evidence_id) REFERENCES evidence(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS policy_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    source_type TEXT NOT NULL DEFAULT '',
    source_name TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL DEFAULT '',
    extracted_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);


CREATE TABLE IF NOT EXISTS endpoint_tags (
    endpoint_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY(endpoint_id, tag),
    FOREIGN KEY(endpoint_id) REFERENCES endpoints(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS seen_requests (
    program_id INTEGER NOT NULL,
    request_hash TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT '',
    host TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(program_id, request_hash),
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS system_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS program_folders (
    program_id INTEGER PRIMARY KEY,
    folder_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_markdown_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id INTEGER NOT NULL,
    source_path TEXT NOT NULL DEFAULT '',
    stored_path TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'general',
    provider TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'imported',
    created_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
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
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(programs)").fetchall()}
        if "discord_category_id" not in cols:
            self.conn.execute("ALTER TABLE programs ADD COLUMN discord_category_id INTEGER")

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

    def set_program_category(self, program_id: int, category_id: int, primary_channel_id: int | None = None) -> None:
        self.conn.execute(
            "UPDATE programs SET discord_category_id=?, discord_thread_id=COALESCE(?, discord_thread_id) WHERE id=?",
            (category_id, primary_channel_id, program_id),
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


    def get_program_by_category_id(self, category_id: int) -> Program | None:
        row = self.conn.execute(
            "SELECT * FROM programs WHERE discord_category_id=?",
            (category_id,),
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



    def iter_endpoints_for_program(self, program_id: int):
        rows = self.conn.execute(
            "SELECT * FROM endpoints WHERE program_id=? ORDER BY id ASC",
            (program_id,),
        ).fetchall()
        return [self._row_to_endpoint(row) for row in rows]

    def update_endpoint_scope(self, endpoint_id: int, scope_status: str) -> None:
        self.conn.execute(
            "UPDATE endpoints SET scope_status=? WHERE id=?",
            (scope_status, endpoint_id),
        )

    def update_burp_import_counts(self, import_id: int) -> None:
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN scope_status='in' THEN 1 ELSE 0 END) AS in_count,
                SUM(CASE WHEN scope_status='out' THEN 1 ELSE 0 END) AS out_count,
                SUM(CASE WHEN scope_status='unknown' THEN 1 ELSE 0 END) AS unknown_count
            FROM endpoints
            WHERE import_id=?
            """,
            (import_id,),
        ).fetchone()

        self.conn.execute(
            """
            UPDATE burp_imports
            SET total_items=?, in_scope_items=?, out_scope_items=?, unknown_scope_items=?
            WHERE id=?
            """,
            (
                int(row["total"] or 0),
                int(row["in_count"] or 0),
                int(row["out_count"] or 0),
                int(row["unknown_count"] or 0),
                import_id,
            ),
        )

    def update_all_burp_import_counts_for_program(self, program_id: int) -> None:
        rows = self.conn.execute(
            "SELECT id FROM burp_imports WHERE program_id=?",
            (program_id,),
        ).fetchall()
        for row in rows:
            self.update_burp_import_counts(int(row["id"]))
        self.conn.commit()

    def delete_burp_import(self, import_id: int) -> None:
        self.conn.execute("DELETE FROM burp_imports WHERE id=?", (import_id,))
        self.conn.commit()

    def dedupe_endpoints(self, program_id: int) -> int:
        """
        Remove duplicate endpoint rows in the same program.
        Keeps the newest/highest-score row for each semantic key.
        """
        rows = self.conn.execute(
            """
            SELECT id
            FROM endpoints
            WHERE program_id=?
              AND id NOT IN (
                SELECT MAX(id)
                FROM endpoints
                WHERE program_id=?
                GROUP BY method, scheme, host, port, path, query_keys, scope_status
              )
            """,
            (program_id, program_id),
        ).fetchall()

        ids = [int(r["id"]) for r in rows]
        if not ids:
            return 0

        self.conn.executemany("DELETE FROM endpoints WHERE id=?", [(x,) for x in ids])
        self.update_all_burp_import_counts_for_program(program_id)
        self.conn.commit()
        return len(ids)

    def endpoint_host_stats(self, program_id: int, scope_filter: str = "all", limit: int = 30):
        where = "program_id=?"
        params: list = [program_id]
        if scope_filter != "all":
            where += " AND scope_status=?"
            params.append(scope_filter)

        params.append(max(1, min(limit, 100)))
        return self.conn.execute(
            f"""
            SELECT
                host,
                COUNT(*) AS total,
                SUM(CASE WHEN scope_status='in' THEN 1 ELSE 0 END) AS in_count,
                SUM(CASE WHEN scope_status='out' THEN 1 ELSE 0 END) AS out_count,
                SUM(CASE WHEN scope_status='unknown' THEN 1 ELSE 0 END) AS unknown_count,
                MAX(interesting_score) AS max_score,
                SUM(CASE WHEN auth_present=1 THEN 1 ELSE 0 END) AS auth_count,
                SUM(CASE WHEN state_changing=1 THEN 1 ELSE 0 END) AS state_count
            FROM endpoints
            WHERE {where}
            GROUP BY host
            ORDER BY max_score DESC, total DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

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


    def add_site_crawl(
        self,
        *,
        platform: str,
        input_value: str,
        source_url: str,
        suggested_name: str,
        reward_max: int,
        source_code: bool,
        has_time_limit: bool,
        time_limit_note: str,
        in_scope_json: str,
        out_scope_json: str,
        restrictions_json: str,
        notices_json: str,
        raw_path: str,
        parsed_path: str,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO site_crawls
            (platform, input_value, source_url, suggested_name, reward_max, source_code,
             has_time_limit, time_limit_note, in_scope_json, out_scope_json,
             restrictions_json, notices_json, raw_path, parsed_path, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                platform,
                input_value,
                source_url,
                suggested_name,
                max(0, int(reward_max or 0)),
                int(bool(source_code)),
                int(bool(has_time_limit)),
                time_limit_note,
                in_scope_json,
                out_scope_json,
                restrictions_json,
                notices_json,
                raw_path,
                parsed_path,
                now_iso(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_site_crawl(self, crawl_id: int):
        return self.conn.execute(
            "SELECT * FROM site_crawls WHERE id=?",
            (crawl_id,),
        ).fetchone()

    def list_site_crawls(self, limit: int = 10):
        return self.conn.execute(
            "SELECT * FROM site_crawls ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 25)),),
        ).fetchall()


    def delete_site_crawl(self, crawl_id: int) -> None:
        self.conn.execute("DELETE FROM site_crawls WHERE id=?", (crawl_id,))
        self.conn.commit()

    def mark_site_crawl_applied(self, crawl_id: int, program_id: int) -> None:
        self.conn.execute(
            "UPDATE site_crawls SET status='applied', applied_program_id=? WHERE id=?",
            (program_id, crawl_id),
        )
        self.conn.commit()


    def delete_program(self, program_id: int) -> None:
        self.conn.execute("DELETE FROM programs WHERE id=?", (program_id,))
        self.conn.commit()

    def add_evidence(
        self,
        *,
        program_id: int,
        title: str,
        evidence_type: str,
        note: str,
        file_name: str,
        file_path: str,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO evidence
            (program_id, title, evidence_type, note, file_name, file_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                program_id,
                title.strip(),
                evidence_type.strip() or "note",
                note.strip(),
                file_name.strip(),
                file_path.strip(),
                now_iso(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_evidence(self, program_id: int, limit: int = 20):
        return self.conn.execute(
            "SELECT * FROM evidence WHERE program_id=? ORDER BY id DESC LIMIT ?",
            (program_id, max(1, min(limit, 100))),
        ).fetchall()

    def get_evidence(self, evidence_id: int):
        return self.conn.execute(
            "SELECT * FROM evidence WHERE id=?",
            (evidence_id,),
        ).fetchone()

    def add_report_draft(
        self,
        *,
        program_id: int,
        title: str,
        body: str,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO report_drafts
            (program_id, title, body, status, created_at)
            VALUES (?, ?, ?, 'draft', ?)
            """,
            (program_id, title.strip(), body, now_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_report_drafts(self, program_id: int, limit: int = 10):
        return self.conn.execute(
            "SELECT * FROM report_drafts WHERE program_id=? ORDER BY id DESC LIMIT ?",
            (program_id, max(1, min(limit, 50))),
        ).fetchall()

    def get_report_draft(self, draft_id: int):
        return self.conn.execute(
            "SELECT * FROM report_drafts WHERE id=?",
            (draft_id,),
        ).fetchone()


    def add_finding(self, *, program_id: int, title: str, vuln_type: str, severity: str, endpoint_id: int | None, summary: str, impact: str) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO findings
            (program_id, title, vuln_type, status, severity, endpoint_id, summary, impact, created_at, updated_at)
            VALUES (?, ?, ?, 'candidate', ?, ?, ?, ?, ?, ?)
            """,
            (program_id, title.strip(), vuln_type.strip(), severity.strip() or "unknown", endpoint_id, summary.strip(), impact.strip(), now_iso(), now_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_findings(self, program_id: int, status: str = "all", limit: int = 30):
        where = "program_id=?"
        params = [program_id]
        if status != "all":
            where += " AND status=?"
            params.append(status)
        params.append(max(1, min(limit, 100)))
        return self.conn.execute(
            f"SELECT * FROM findings WHERE {where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()

    def get_finding(self, finding_id: int):
        return self.conn.execute("SELECT * FROM findings WHERE id=?", (finding_id,)).fetchone()

    def update_finding(self, finding_id: int, *, status: str | None = None, severity: str | None = None, summary: str | None = None, impact: str | None = None) -> None:
        fields = []
        params = []
        if status is not None:
            fields.append("status=?")
            params.append(status)
        if severity is not None:
            fields.append("severity=?")
            params.append(severity)
        if summary is not None:
            fields.append("summary=?")
            params.append(summary)
        if impact is not None:
            fields.append("impact=?")
            params.append(impact)
        if not fields:
            return
        fields.append("updated_at=?")
        params.append(now_iso())
        params.append(finding_id)
        self.conn.execute(f"UPDATE findings SET {', '.join(fields)} WHERE id=?", params)
        self.conn.commit()

    def link_finding_evidence(self, finding_id: int, evidence_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO finding_evidence (finding_id, evidence_id, created_at) VALUES (?, ?, ?)",
            (finding_id, evidence_id, now_iso()),
        )
        self.conn.commit()

    def list_finding_evidence(self, finding_id: int):
        return self.conn.execute(
            """
            SELECT e.*
            FROM evidence e
            JOIN finding_evidence fe ON fe.evidence_id=e.id
            WHERE fe.finding_id=?
            ORDER BY e.id DESC
            """,
            (finding_id,),
        ).fetchall()

    def add_ai_result(self, *, program_id: int, provider: str, mode: str, title: str, body: str) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO ai_results (program_id, provider, mode, title, body, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (program_id, provider, mode, title, body, now_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_ai_results(self, program_id: int, limit: int = 20):
        return self.conn.execute(
            "SELECT * FROM ai_results WHERE program_id=? ORDER BY id DESC LIMIT ?",
            (program_id, max(1, min(limit, 100))),
        ).fetchall()

    def add_policy_snapshot(self, *, program_id: int, source_type: str, source_name: str, raw_text: str, extracted_json: str) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO policy_snapshots
            (program_id, source_type, source_name, raw_text, extracted_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (program_id, source_type, source_name, raw_text, extracted_json, now_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_policy_snapshots(self, program_id: int, limit: int = 5):
        return self.conn.execute(
            "SELECT * FROM policy_snapshots WHERE program_id=? ORDER BY id DESC LIMIT ?",
            (program_id, max(1, min(limit, 20))),
        ).fetchall()


    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO system_meta (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, now_iso()),
        )
        self.conn.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM system_meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def count_table(self, table_name: str) -> int:
        allowed = {
            "programs", "scope_items", "restrictions", "notices", "burp_imports",
            "endpoints", "evidence", "report_drafts", "findings", "ai_results",
            "policy_snapshots", "endpoint_tags", "seen_requests"
        }
        if table_name not in allowed:
            return 0
        row = self.conn.execute(f"SELECT COUNT(*) AS c FROM {table_name}").fetchone()
        return int(row["c"] or 0)

    def add_endpoint_tag(self, endpoint_id: int, tag: str, note: str = "") -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO endpoint_tags (endpoint_id, tag, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (endpoint_id, tag.strip().lower(), note.strip(), now_iso()),
        )
        self.conn.commit()

    def list_endpoint_tags(self, endpoint_id: int):
        return self.conn.execute(
            "SELECT * FROM endpoint_tags WHERE endpoint_id=? ORDER BY tag ASC",
            (endpoint_id,),
        ).fetchall()

    def list_endpoints_by_tag(self, program_id: int, tag: str, limit: int = 50):
        rows = self.conn.execute(
            """
            SELECT e.*
            FROM endpoints e
            JOIN endpoint_tags t ON t.endpoint_id=e.id
            WHERE e.program_id=? AND t.tag=?
            ORDER BY e.interesting_score DESC, e.id DESC
            LIMIT ?
            """,
            (program_id, tag.strip().lower(), max(1, min(limit, 200))),
        ).fetchall()
        return [self._row_to_endpoint(row) for row in rows]

    def finding_status_counts(self, program_id: int):
        return self.conn.execute(
            """
            SELECT status, COUNT(*) AS c
            FROM findings
            WHERE program_id=?
            GROUP BY status
            ORDER BY status
            """,
            (program_id,),
        ).fetchall()

    def list_all_report_drafts(self, program_id: int):
        return self.conn.execute(
            "SELECT * FROM report_drafts WHERE program_id=? ORDER BY id DESC",
            (program_id,),
        ).fetchall()

    def find_related_report_drafts(self, program_id: int, title: str):
        return self.conn.execute(
            "SELECT * FROM report_drafts WHERE program_id=? AND title LIKE ? ORDER BY id DESC",
            (program_id, f"%{title[:60]}%"),
        ).fetchall()

    def add_seen_request(self, *, program_id: int, request_hash: str, method: str, host: str, path: str) -> bool:
        row = self.conn.execute(
            "SELECT count FROM seen_requests WHERE program_id=? AND request_hash=?",
            (program_id, request_hash),
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE seen_requests SET count=?, last_seen=? WHERE program_id=? AND request_hash=?",
                (int(row["count"] or 0) + 1, now_iso(), program_id, request_hash),
            )
            self.conn.commit()
            return False
        self.conn.execute(
            """
            INSERT INTO seen_requests (program_id, request_hash, method, host, path, first_seen, last_seen, count)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (program_id, request_hash, method, host, path, now_iso(), now_iso()),
        )
        self.conn.commit()
        return True


    def set_program_folder(self, program_id: int, folder_path: str) -> None:
        row = self.conn.execute(
            "SELECT program_id FROM program_folders WHERE program_id=?",
            (program_id,),
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE program_folders SET folder_path=?, updated_at=? WHERE program_id=?",
                (folder_path, now_iso(), program_id),
            )
        else:
            self.conn.execute(
                "INSERT INTO program_folders (program_id, folder_path, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (program_id, folder_path, now_iso(), now_iso()),
            )
        self.conn.commit()

    def get_program_folder(self, program_id: int) -> str:
        row = self.conn.execute(
            "SELECT folder_path FROM program_folders WHERE program_id=?",
            (program_id,),
        ).fetchone()
        return str(row["folder_path"]) if row else ""

    def add_ai_markdown_file(
        self,
        *,
        program_id: int,
        source_path: str,
        stored_path: str,
        title: str,
        category: str,
        provider: str,
        mode: str,
        sha256: str,
        status: str = "imported",
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO ai_markdown_files
            (program_id, source_path, stored_path, title, category, provider, mode, sha256, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                program_id,
                source_path,
                stored_path,
                title,
                category,
                provider,
                mode,
                sha256,
                status,
                now_iso(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_ai_markdown_files(self, program_id: int, limit: int = 20):
        return self.conn.execute(
            "SELECT * FROM ai_markdown_files WHERE program_id=? ORDER BY id DESC LIMIT ?",
            (program_id, max(1, min(limit, 100))),
        ).fetchall()

    def get_ai_markdown_by_hash(self, program_id: int, sha256: str):
        return self.conn.execute(
            "SELECT * FROM ai_markdown_files WHERE program_id=? AND sha256=? ORDER BY id DESC LIMIT 1",
            (program_id, sha256),
        ).fetchone()

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
            discord_category_id=int(row["discord_category_id"]) if "discord_category_id" in row.keys() and row["discord_category_id"] else None,
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
