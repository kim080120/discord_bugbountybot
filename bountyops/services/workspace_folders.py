from __future__ import annotations

from pathlib import Path


DEFAULT_SUBDIRS = [
    "policy",
    "burp",
    "ai/inbox",
    "ai/processed",
    "ai/results",
    "findings",
    "evidence",
    "reports",
    "exports",
    "bundles",
    "notes",
]


def safe_folder_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in value.strip())[:120] or "program"


def default_program_folder(storage_dir: Path, program) -> Path:
    return storage_dir / "workspaces" / safe_folder_name(program.name)


def init_program_folder(folder: str | Path) -> Path:
    root = Path(folder).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    for sub in DEFAULT_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)

    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "\n".join(
                [
                    "# BountyOps Workspace",
                    "",
                    "Recommended workflow:",
                    "",
                    "- Put Codex/Claude markdown outputs into `ai/inbox/`.",
                    "- Run `/md scan_folder` to import and organize them.",
                    "- Use `findings/`, `evidence/`, and `reports/` for report preparation.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return root


def tree_text(root: str | Path, max_entries: int = 80) -> str:
    root = Path(root).expanduser()
    if not root.exists():
        return f"{root} does not exist."

    lines = [f"{root}/"]
    count = 0
    for path in sorted(root.rglob("*")):
        if count >= max_entries:
            lines.append("... truncated ...")
            break
        rel = path.relative_to(root)
        depth = len(rel.parts) - 1
        prefix = "  " * depth + ("├─ " if count < max_entries else "")
        suffix = "/" if path.is_dir() else ""
        lines.append(f"{prefix}{rel.name}{suffix}")
        count += 1
    return "\n".join(lines)
