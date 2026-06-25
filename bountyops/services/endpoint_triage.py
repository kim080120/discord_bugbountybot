from __future__ import annotations

from dataclasses import dataclass

from .scope_matcher import classify_scope


@dataclass(slots=True)
class ReclassifyResult:
    total: int
    changed: int
    in_count: int
    out_count: int
    unknown_count: int


def reclassify_program_endpoints(db, program) -> ReclassifyResult:
    in_scopes = db.list_scope_items(program.id, "in")
    out_scopes = db.list_scope_items(program.id, "out")
    endpoints = db.iter_endpoints_for_program(program.id)

    changed = 0
    counts = {"in": 0, "out": 0, "unknown": 0}

    for ep in endpoints:
        new_status = classify_scope(ep.host, in_scopes, out_scopes)
        counts[new_status] += 1
        if new_status != ep.scope_status:
            db.update_endpoint_scope(ep.id, new_status)
            changed += 1

    db.update_all_burp_import_counts_for_program(program.id)
    db.conn.commit()

    return ReclassifyResult(
        total=len(endpoints),
        changed=changed,
        in_count=counts["in"],
        out_count=counts["out"],
        unknown_count=counts["unknown"],
    )
