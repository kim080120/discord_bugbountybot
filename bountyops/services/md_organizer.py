from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .workspace_folders import init_program_folder


FINDING_HINTS = [
    "finding", "vulnerability", "idor", "bola", "pii", "token", "secret",
    "auth bypass", "authorization", "xss", "csrf", "ssrf", "open redirect",
    "cors", "exposure", "leak", "impact",
]
REPORT_HINTS = ["steps to reproduce", "impact", "recommended fix", "summary", "affected asset"]
EVIDENCE_HINTS = ["evidence", "request", "response", "burp", "screenshot", "reproduction"]
POLICY_HINTS = ["scope", "out of scope", "policy", "restriction", "prohibited"]


@dataclass(slots=True)
class MarkdownSummary:
    title: str
    category: str
    sha256: str
    candidates: list[str]
    summary: str


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def extract_title(text: str, fallback: str = "analysis.md") -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean.startswith("#"):
            title = clean.lstrip("#").strip()
            if title:
                return title[:160]
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean[:160]
    return fallback


def classify_markdown(text: str) -> str:
    low = text.lower()
    if any(h in low for h in FINDING_HINTS) and any(h in low for h in ["impact", "reproduce", "evidence", "candidate"]):
        return "finding-analysis"
    if sum(1 for h in REPORT_HINTS if h in low) >= 3:
        return "report-draft"
    if sum(1 for h in POLICY_HINTS if h in low) >= 2:
        return "policy-review"
    if any(h in low for h in EVIDENCE_HINTS):
        return "evidence-review"
    if "endpoint" in low or "api" in low:
        return "endpoint-review"
    return "general-analysis"


def extract_candidates(text: str, limit: int = 12) -> list[str]:
    candidates: list[str] = []
    for line in text.splitlines():
        clean = line.strip(" -*\t")
        low = clean.lower()
        if len(clean) < 15 or len(clean) > 240:
            continue
        if any(h in low for h in FINDING_HINTS):
            if clean not in candidates:
                candidates.append(clean)
        if len(candidates) >= limit:
            break
    return candidates


def summarize_markdown(text: str, fallback: str) -> MarkdownSummary:
    title = extract_title(text, fallback=fallback)
    category = classify_markdown(text)
    digest = sha256_text(text)
    candidates = extract_candidates(text)

    paragraphs = []
    for line in text.splitlines():
        clean = line.strip()
        if not clean or clean.startswith("```"):
            continue
        if clean.startswith("#"):
            continue
        paragraphs.append(clean)
        if len(" ".join(paragraphs)) > 500:
            break

    summary = " ".join(paragraphs)[:700] if paragraphs else "No summary extracted."
    return MarkdownSummary(
        title=title,
        category=category,
        sha256=digest,
        candidates=candidates,
        summary=summary,
    )


def category_target_subdir(category: str) -> str:
    if category == "finding-analysis":
        return "findings"
    if category == "report-draft":
        return "reports"
    if category == "policy-review":
        return "policy"
    if category == "evidence-review":
        return "evidence"
    if category == "endpoint-review":
        return "ai/results"
    return "ai/results"


def import_markdown_text(
    *,
    db,
    program,
    workspace_root: str | Path,
    source_name: str,
    text: str,
    provider: str = "codex",
    mode: str = "analysis",
    create_findings: bool = False,
) -> dict:
    root = init_program_folder(workspace_root)
    info = summarize_markdown(text, fallback=source_name)

    existing = db.get_ai_markdown_by_hash(program.id, info.sha256)
    if existing:
        return {
            "skipped": True,
            "reason": "duplicate sha256",
            "markdown_id": existing["id"],
            "summary": info,
            "stored_path": existing["stored_path"],
            "ai_result_id": None,
            "findings": [],
        }

    target_dir = root / category_target_subdir(info.category)
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in source_name)[:120] or "analysis.md"
    if not safe_name.lower().endswith(".md"):
        safe_name += ".md"
    stored = target_dir / safe_name

    # Avoid overwrite
    counter = 1
    base = stored
    while stored.exists():
        stored = base.with_name(f"{base.stem}_{counter}{base.suffix}")
        counter += 1

    stored.write_text(text, encoding="utf-8")

    md_id = db.add_ai_markdown_file(
        program_id=program.id,
        source_path=source_name,
        stored_path=str(stored),
        title=info.title,
        category=info.category,
        provider=provider,
        mode=mode,
        sha256=info.sha256,
        status="imported",
    )

    ai_result_id = db.add_ai_result(
        program_id=program.id,
        provider=provider,
        mode=mode,
        title=info.title,
        body=text,
    )

    created_findings = []
    if create_findings:
        for cand in info.candidates:
            fid = db.add_finding(
                program_id=program.id,
                title=cand[:120],
                vuln_type="AI-md-candidate",
                severity="unknown",
                endpoint_id=None,
                summary=f"Parsed from markdown `{source_name}`: {cand}",
                impact="Needs human validation.",
            )
            created_findings.append(fid)

    return {
        "skipped": False,
        "markdown_id": md_id,
        "summary": info,
        "stored_path": str(stored),
        "ai_result_id": ai_result_id,
        "findings": created_findings,
    }


def scan_markdown_folder(
    *,
    db,
    program,
    workspace_root: str | Path,
    scan_dir: str | Path,
    provider: str = "codex",
    mode: str = "analysis",
    create_findings: bool = False,
    move_processed: bool = True,
    limit: int = 50,
) -> list[dict]:
    root = init_program_folder(workspace_root)
    scan_path = Path(scan_dir).expanduser()
    if not scan_path.is_absolute():
        scan_path = root / scan_path

    if not scan_path.exists():
        raise FileNotFoundError(f"scan_dir not found: {scan_path}")
    if not scan_path.is_dir():
        raise NotADirectoryError(f"scan_dir is not a directory: {scan_path}")

    results = []
    for md in sorted(scan_path.glob("*.md"))[: max(1, min(limit, 200))]:
        text = md.read_text(encoding="utf-8", errors="replace")
        result = import_markdown_text(
            db=db,
            program=program,
            workspace_root=root,
            source_name=str(md),
            text=text,
            provider=provider,
            mode=mode,
            create_findings=create_findings,
        )
        results.append(result)

        if move_processed and not result.get("skipped"):
            processed = root / "ai" / "processed"
            processed.mkdir(parents=True, exist_ok=True)
            dest = processed / md.name
            counter = 1
            base = dest
            while dest.exists():
                dest = base.with_name(f"{base.stem}_{counter}{base.suffix}")
                counter += 1
            try:
                shutil.move(str(md), str(dest))
            except Exception:
                pass

    return results
