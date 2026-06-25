from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Program:
    id: int
    name: str
    platform: str
    reward_min: int
    reward_max: int
    source_code: bool
    has_time_limit: bool
    time_limit_note: str
    policy_url: str
    discord_thread_id: int | None
    discord_category_id: int | None
    created_at: str


@dataclass(slots=True)
class ScopeItem:
    id: int
    program_id: int
    type: str
    value: str
    note: str
    source_url: str
    created_at: str


@dataclass(slots=True)
class Notice:
    id: int
    program_id: int
    title: str
    summary: str
    source_url: str
    created_at: str


@dataclass(slots=True)
class Restriction:
    id: int
    program_id: int
    severity: str
    text: str
    source_url: str
    created_at: str


@dataclass(slots=True)
class BurpImport:
    id: int
    program_id: int
    filename: str
    format: str
    raw_path: str
    sanitized_path: str
    total_items: int
    in_scope_items: int
    out_scope_items: int
    unknown_scope_items: int
    created_at: str


@dataclass(slots=True)
class Endpoint:
    id: int
    program_id: int
    import_id: int
    method: str
    scheme: str
    host: str
    port: int | None
    path: str
    query_keys: str
    status_code: int | None
    content_type: str
    auth_present: bool
    state_changing: bool
    scope_status: str
    interesting_score: int
    created_at: str


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
