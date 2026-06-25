from __future__ import annotations

from dataclasses import dataclass


MODE_DESCRIPTIONS = {
    "endpoint-inventory": "Endpoint inventory and interesting target triage",
    "idor-review": "IDOR/BOLA candidate analysis",
    "pii-review": "PII/token/secret exposure review",
    "source-review": "Source-code target review",
    "report-review": "False-positive and report quality review",
}


def build_ai_prompt(
    *,
    provider: str,
    mode: str,
    program_name: str,
    platform: str,
    policy_url: str,
    in_scope: list,
    out_scope: list,
    restrictions: list,
    endpoints: list,
    evidence: list,
) -> str:
    mode_title = MODE_DESCRIPTIONS.get(mode, mode)

    in_scope_text = "\n".join(f"- {x.value} ({x.note})" for x in in_scope[:60]) or "- None"
    out_scope_text = "\n".join(f"- {x.value} ({x.note})" for x in out_scope[:60]) or "- None"
    restrictions_text = "\n".join(f"- {x.text}" for x in restrictions[:50]) or "- None"

    endpoints_text = "\n".join(
        f"- #{ep.id} {ep.scope_status.upper()} score={ep.interesting_score} {ep.method} {ep.host}{ep.path} "
        f"status={ep.status_code or '-'} auth={ep.auth_present} state={ep.state_changing} query={ep.query_keys or '-'}"
        for ep in endpoints[:80]
    ) or "- No endpoints imported yet"

    evidence_text = "\n".join(
        f"- #{ev['id']} [{ev['evidence_type']}] {ev['title']}: {ev['note']}"
        for ev in evidence[:40]
    ) or "- No evidence added yet"

    provider_note = {
        "codex": "You are Codex acting as a security analysis assistant.",
        "claude": "You are Claude acting as a careful security analysis assistant.",
        "generic": "You are a careful security analysis assistant.",
    }.get(provider, "You are a careful security analysis assistant.")

    return f"""# BountyOps AI Analysis Prompt

{provider_note}

## Task

Mode: {mode}
Mode description: {mode_title}

Analyze the bug bounty workspace below. Do not invent findings. Separate confirmed facts from hypotheses.
Prefer conservative reportability decisions.

## Safety Rules

- Only consider explicitly in-scope targets.
- Do not suggest destructive testing, DoS, brute force, spam, phishing, or persistence.
- Do not suggest accessing data that the researcher does not own.
- If evidence is insufficient, mark the item as "Needs validation" or "Not reportable".
- Redact cookies, tokens, Authorization headers, secrets, emails, phone numbers, and private user data.
- Active testing must be low-impact and should require explicit human approval.

## Program

- Program: {program_name}
- Platform: {platform}
- Policy URL: {policy_url or "Unknown"}

## In-scope Targets

{in_scope_text}

## Out-of-scope Targets

{out_scope_text}

## Restrictions

{restrictions_text}

## Imported Endpoints

{endpoints_text}

## Evidence

{evidence_text}

## Requested Output

Return the result in this structure:

1. Scope decision
2. Top candidate findings
3. Endpoint inventory observations
4. IDOR/BOLA candidates
5. PII/token/secret exposure candidates
6. False-positive risks
7. Safe validation plan
8. Evidence still needed
9. Reportability: Reportable / Needs validation / Not reportable
10. Next actions

Keep the wording concise and practical for bug bounty triage.
"""
