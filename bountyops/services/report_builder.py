from __future__ import annotations


def build_report_draft(
    *,
    program_name: str,
    platform: str,
    policy_url: str,
    in_scope: list,
    restrictions: list,
    evidence: list,
    finding_title: str,
    vuln_type: str,
    affected_asset: str,
    summary: str,
    impact: str,
) -> str:
    in_scope_text = "\n".join(f"- {x.value}" for x in in_scope[:30]) or "- None recorded"
    restrictions_text = "\n".join(f"- {x.text}" for x in restrictions[:30]) or "- None recorded"
    evidence_text = "\n".join(
        f"- Evidence #{ev['id']} [{ev['evidence_type']}]: {ev['title']} — {ev['note']}"
        for ev in evidence[:30]
    ) or "- No evidence attached yet"

    return f"""# {finding_title}

## Summary

{summary or "TODO: Describe the vulnerability in one or two clear paragraphs."}

## Program

- Platform: {platform}
- Program: {program_name}
- Policy URL: {policy_url or "Unknown"}

## Vulnerability Type

{vuln_type or "TODO"}

## Affected Asset

{affected_asset or "TODO"}

## Scope Check

The affected asset should be checked against the current in-scope list.

Known in-scope targets:

{in_scope_text}

## Relevant Restrictions

{restrictions_text}

## Steps to Reproduce

1. TODO: Prepare a researcher-controlled account or test data.
2. TODO: Send the minimum required request.
3. TODO: Observe the vulnerable behavior.
4. TODO: Repeat with a control case to rule out false positives.

## Evidence

{evidence_text}

## Impact

{impact or "TODO: Explain realistic security impact without exaggeration."}

## Why This Is Security-Relevant

TODO: Explain why the behavior violates an authorization, confidentiality, integrity, or availability expectation.

## False Positive Checks

- Confirm the target is in scope.
- Confirm the behavior is not documented or intended.
- Confirm the result is reproducible.
- Confirm no out-of-scope systems or third-party services were tested.
- Confirm no private user data was accessed or stored.

## Recommended Fix

TODO: Suggest a practical remediation.

## Notes / Limitations

TODO: Mention any constraints, assumptions, or incomplete validation.
"""
