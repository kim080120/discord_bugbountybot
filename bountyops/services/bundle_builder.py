from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path


def safe_filename(value: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in value)[:120] or "bundle"


def build_finding_bundle(db, storage_dir: Path, finding_id: int) -> Path:
    finding = db.get_finding(finding_id)
    if not finding:
        raise KeyError(f"Finding not found: {finding_id}")

    program = db.get_program_by_id(finding["program_id"])
    base = storage_dir / "bundles" / f"finding_{finding_id}_{safe_filename(finding['title'])}"
    if base.exists():
        # keep old bundle but overwrite files
        pass
    base.mkdir(parents=True, exist_ok=True)

    evidence = [dict(r) for r in db.list_finding_evidence(finding_id)]
    endpoints = []
    if finding["endpoint_id"]:
        try:
            endpoints.append(db.get_endpoint(int(finding["endpoint_id"])))
        except Exception:
            pass

    draft_rows = db.find_related_report_drafts(program.id, finding["title"])
    report_body = draft_rows[0]["body"] if draft_rows else ""

    (base / "finding.json").write_text(json.dumps(dict(finding), ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        f"# Finding Bundle #{finding_id}: {finding['title']}",
        "",
        f"- Program: {program.name}",
        f"- Platform: {program.platform}",
        f"- Status: {finding['status']}",
        f"- Severity: {finding['severity']}",
        f"- Vulnerability Type: {finding['vuln_type']}",
        f"- Endpoint ID: {finding['endpoint_id'] or '-'}",
        "",
        "## Summary",
        finding["summary"] or "TODO",
        "",
        "## Impact",
        finding["impact"] or "TODO",
        "",
        "## Evidence",
    ]
    if evidence:
        for e in evidence:
            md.append(f"- Evidence #{e['id']} [{e['evidence_type']}]: {e['title']} — {e['note']}")
    else:
        md.append("- No linked evidence yet.")
    (base / "evidence.md").write_text("\n".join(md), encoding="utf-8")

    with (base / "endpoints.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "scope_status", "score", "method", "host", "path", "query_keys", "status_code", "auth_present", "state_changing"])
        for ep in endpoints:
            writer.writerow([ep.id, ep.scope_status, ep.interesting_score, ep.method, ep.host, ep.path, ep.query_keys, ep.status_code, ep.auth_present, ep.state_changing])

    if report_body:
        (base / "report_draft.md").write_text(report_body, encoding="utf-8")
    else:
        (base / "report_draft.md").write_text("# Report Draft\n\nNo related draft found yet.\n", encoding="utf-8")

    zip_path = base.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in base.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(base))

    return zip_path


def build_program_report_bundle(db, storage_dir: Path, program_name: str) -> Path:
    program = db.get_program_by_name(program_name)
    if not program:
        raise KeyError(f"Program not found: {program_name}")

    base = storage_dir / "bundles" / f"program_{safe_filename(program.name)}"
    base.mkdir(parents=True, exist_ok=True)

    drafts = db.list_all_report_drafts(program.id)
    findings = db.list_findings(program.id, status="all", limit=200)
    evidence = db.list_evidence(program.id, limit=200)

    summary = [
        f"# Program Bundle: {program.name}",
        "",
        f"- Platform: {program.platform}",
        f"- Policy URL: {program.policy_url}",
        "",
        "## Findings",
    ]
    for f in findings:
        summary.append(f"- #{f['id']} {f['title']} [{f['status']}/{f['severity']}]")
    summary += ["", "## Evidence"]
    for e in evidence:
        summary.append(f"- #{e['id']} {e['title']} [{e['evidence_type']}] — {e['note']}")
    (base / "summary.md").write_text("\n".join(summary), encoding="utf-8")

    drafts_dir = base / "drafts"
    drafts_dir.mkdir(exist_ok=True)
    for d in drafts:
        (drafts_dir / f"draft_{d['id']}_{safe_filename(d['title'])}.md").write_text(d["body"], encoding="utf-8")

    zip_path = base.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in base.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(base))
    return zip_path
