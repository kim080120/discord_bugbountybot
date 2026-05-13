from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..db import Database
from ..models import Program, BurpImport, Endpoint
from .parser import ParsedEndpoint, parse_auto, interesting_score
from .sanitizer import sanitize_text
from .scope_matcher import classify_scope


@dataclass(slots=True)
class ImportResult:
    burp_import: BurpImport
    endpoints: list[Endpoint]
    sanitized_text: str


class BurpImporter:
    def __init__(self, db: Database, storage_dir: Path):
        self.db = db
        self.storage_dir = storage_dir
        self.raw_dir = storage_dir / "raw"
        self.sanitized_dir = storage_dir / "sanitized"
        self.parsed_dir = storage_dir / "parsed"
        for d in [self.raw_dir, self.sanitized_dir, self.parsed_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def import_text(
        self,
        *,
        program: Program,
        filename: str,
        content: bytes,
        format_hint: str = "auto",
    ) -> ImportResult:
        uid = uuid4().hex[:12]
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)[:120] or "import.txt"

        raw_path = self.raw_dir / f"{program.id}_{uid}_{safe_name}"
        raw_path.write_bytes(content)

        text = content.decode("utf-8", errors="replace")
        detected_format, parsed = parse_auto(filename=safe_name, text=text, format_hint=format_hint)

        in_scopes = self.db.list_scope_items(program.id, "in")
        out_scopes = self.db.list_scope_items(program.id, "out")

        sanitized_parts: list[str] = []
        parsed_json: list[dict] = []
        endpoint_rows: list[Endpoint] = []

        counts = {"in": 0, "out": 0, "unknown": 0}

        # Insert import row first, endpoints below.
        # Counts are updated after endpoint insertion with a direct SQL update.
        burp_import = self.db.add_burp_import(
            program_id=program.id,
            filename=safe_name,
            format=detected_format,
            raw_path=str(raw_path),
            sanitized_path="",
            total_items=0,
            in_scope_items=0,
            out_scope_items=0,
            unknown_scope_items=0,
        )

        for item in parsed:
            scope_status = classify_scope(item.host, in_scopes, out_scopes)
            counts[scope_status] += 1
            score = interesting_score(item)

            endpoint = self.db.add_endpoint(
                program_id=program.id,
                import_id=burp_import.id,
                method=item.method,
                scheme=item.scheme,
                host=item.host,
                port=item.port,
                path=item.path,
                query_keys=",".join(item.query_keys),
                status_code=item.status_code,
                content_type=item.content_type,
                auth_present=item.auth_present,
                state_changing=item.state_changing,
                scope_status=scope_status,
                interesting_score=score,
            )
            endpoint_rows.append(endpoint)

            sanitized_req = sanitize_text(item.raw_request)
            sanitized_res = sanitize_text(item.raw_response)

            sanitized_parts.append(
                "\n".join(
                    [
                        "=" * 80,
                        f"Endpoint #{endpoint.id} | {scope_status.upper()} | score={score}",
                        f"{item.method} {item.host}{item.path}",
                        "-" * 80,
                        sanitized_req,
                        "-" * 80,
                        sanitized_res,
                    ]
                )
            )

            parsed_json.append(
                {
                    "endpoint_id": endpoint.id,
                    "method": item.method,
                    "scheme": item.scheme,
                    "host": item.host,
                    "port": item.port,
                    "path": item.path,
                    "query_keys": item.query_keys,
                    "status_code": item.status_code,
                    "content_type": item.content_type,
                    "auth_present": item.auth_present,
                    "state_changing": item.state_changing,
                    "scope_status": scope_status,
                    "interesting_score": score,
                }
            )

        sanitized_text = "\n\n".join(sanitized_parts) if sanitized_parts else sanitize_text(text[:200000])
        sanitized_path = self.sanitized_dir / f"{program.id}_{uid}_{safe_name}.sanitized.txt"
        parsed_path = self.parsed_dir / f"{program.id}_{uid}_{safe_name}.parsed.json"

        sanitized_path.write_text(sanitized_text, encoding="utf-8")
        parsed_path.write_text(json.dumps(parsed_json, ensure_ascii=False, indent=2), encoding="utf-8")

        self.db.conn.execute(
            """
            UPDATE burp_imports
            SET sanitized_path=?, total_items=?, in_scope_items=?, out_scope_items=?, unknown_scope_items=?
            WHERE id=?
            """,
            (
                str(sanitized_path),
                len(endpoint_rows),
                counts["in"],
                counts["out"],
                counts["unknown"],
                burp_import.id,
            ),
        )
        self.db.conn.commit()

        burp_import = self.db.get_burp_import(burp_import.id)

        return ImportResult(
            burp_import=burp_import,
            endpoints=endpoint_rows,
            sanitized_text=sanitized_text,
        )
