from pathlib import Path
import tempfile

from bountyops.db import Database
from bountyops.services.importer import BurpImporter


raw = b"""GET /api/users/me?userId=123 HTTP/1.1
Host: api.example.com
Cookie: session=abcdef
Authorization: Bearer token

HTTP/1.1 200 OK
Content-Type: application/json

{"email":"test@example.com","access_token":"secret"}
"""

with tempfile.TemporaryDirectory() as td:
    base = Path(td)
    db = Database(base / "test.sqlite3")
    db.init()
    p = db.add_program(
        name="Example",
        platform="VDP",
        reward_min=0,
        reward_max=1000000,
        source_code=False,
        has_time_limit=False,
        time_limit_note="",
        policy_url="",
    )
    db.add_scope_item(program_id=p.id, type="in", value="*.example.com", note="", source_url="")
    importer = BurpImporter(db, base / "storage")
    result = importer.import_text(program=p, filename="sample.txt", content=raw, format_hint="auto")
    assert result.burp_import.total_items == 1
    assert result.burp_import.in_scope_items == 1
    assert "[REDACTED]" in result.sanitized_text
    eps = db.list_endpoints(program_id=p.id)
    assert eps[0].host == "api.example.com"
    assert eps[0].auth_present is True
    assert eps[0].interesting_score > 0
    db.close()

print("smoke ok")
