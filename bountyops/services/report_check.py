from __future__ import annotations

from .redaction import scan_text


def check_report_text(text: str) -> list[str]:
    issues = []

    required = [
        ("Summary", ["summary"]),
        ("Affected Asset", ["affected asset", "asset"]),
        ("Steps to Reproduce", ["steps to reproduce", "reproduce"]),
        ("Evidence", ["evidence"]),
        ("Impact", ["impact"]),
        ("Scope", ["scope"]),
    ]

    low = text.lower()
    for label, keys in required:
        if not any(k in low for k in keys):
            issues.append(f"Missing or weak section: {label}")

    findings = scan_text(text)
    for name, count in findings.items():
        issues.append(f"Potential sensitive data: {name} x{count}")

    risky_words = ["guaranteed", "critical impact", "all users", "full takeover", "definitely"]
    for word in risky_words:
        if word in low:
            issues.append(f"Potentially exaggerated wording: `{word}`")

    if len(text.strip()) < 500:
        issues.append("Report draft is very short; reproduction/evidence may be insufficient.")

    return issues
