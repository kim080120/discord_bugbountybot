from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from pathlib import Path


REQUEST_RE = re.compile(rb"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+\S+\s+HTTP/\d(?:\.\d)?", re.I)
RESPONSE_RE = re.compile(rb"HTTP/\d(?:\.\d)?\s+\d{3}\b", re.I)
HTTP_RE = re.compile(rb"HTTP/\d(?:\.\d)?", re.I)
HAR_HINT_RE = re.compile(rb'"log"\s*:\s*\{|"entries"\s*:\s*\[', re.I)
HOST_RE = re.compile(rb"(?im)^Host:\s*([^\r\n]+)")

CHUNK_SIZE = 1024 * 1024
OVERLAP = 8192
MAX_SCAN_FILES = 3000
MAX_HOSTS = 20


@dataclass(slots=True)
class TempCandidate:
    path: str
    size: int
    kind: str
    score: int
    hosts: list[str]
    request_count: int = 0
    response_count: int = 0


def parse_host_patterns(value: str | None) -> list[str]:
    if not value:
        return []
    return [x.strip().lower() for x in value.split(",") if x.strip()]


def host_matches(host: str, pattern: str) -> bool:
    host = (host or "").lower().strip().split(":")[0]
    pattern = (pattern or "").lower().strip()
    if not host or not pattern:
        return False
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return host == suffix or host.endswith("." + suffix)
    if "*" in pattern:
        return fnmatch.fnmatch(host, pattern)
    return host == pattern or host.endswith("." + pattern)


def host_allowed(hosts: list[str], include_hosts: list[str], exclude_hosts: list[str]) -> bool:
    normalized = [h.lower().split(":")[0].strip() for h in hosts if h]
    if exclude_hosts and any(host_matches(h, p) for h in normalized for p in exclude_hosts):
        return False
    if include_hosts:
        return any(host_matches(h, p) for h in normalized for p in include_hosts)
    return True


def _safe_decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _hosts_from_bytes(data: bytes, hosts: list[str] | None = None) -> list[str]:
    if hosts is None:
        hosts = []
    for match in HOST_RE.finditer(data):
        host = match.group(1).decode("utf-8", errors="replace").strip()
        if host and host not in hosts:
            hosts.append(host)
        if len(hosts) >= MAX_HOSTS:
            break
    return hosts


def _iter_chunks(path: Path, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP):
    prev = b""
    offset = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            data = prev + chunk
            data_offset = offset - len(prev)
            yield data_offset, data
            prev = data[-overlap:] if overlap > 0 else b""
            offset += len(chunk)


def analyze_file(path: Path) -> TempCandidate | None:
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size <= 0:
            return None
    except Exception:
        return None

    request_count = 0
    response_count = 0
    http_count = 0
    har_hint = False
    hosts: list[str] = []

    try:
        for idx, (_, data) in enumerate(_iter_chunks(path)):
            if idx == 0 and HAR_HINT_RE.search(data[:500000]):
                har_hint = True
            request_count += len(REQUEST_RE.findall(data))
            response_count += len(RESPONSE_RE.findall(data))
            http_count += len(HTTP_RE.findall(data))
            _hosts_from_bytes(data, hosts)
            if idx >= 96 and (request_count >= 50 or response_count >= 50 or len(hosts) >= 8):
                break
    except Exception:
        return None

    score = 0
    kind = "unknown"
    if har_hint:
        score += 50
        kind = "har-json"
    if request_count:
        score += min(request_count * 10, 80)
        kind = "raw-http"
    if response_count:
        score += min(response_count * 3, 30)
        if kind == "unknown":
            kind = "response-fragments"
    if http_count:
        score += min(http_count, 20)
    if hosts:
        score += min(len(hosts) * 5, 25)
    if path.suffix.lower() in {".cont", ".tmp"} and (request_count or response_count or hosts):
        score += 20
        if kind == "unknown":
            kind = "burp-container-fragments"
    if score <= 0:
        return None

    return TempCandidate(
        path=str(path),
        size=size,
        kind=kind,
        score=score,
        hosts=hosts,
        request_count=request_count,
        response_count=response_count,
    )


def scan_burp_temp_folder(folder_path: str, *, max_files: int = 500) -> list[TempCandidate]:
    root = Path(folder_path).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"Path does not exist: {root}")

    if root.is_file():
        cand = analyze_file(root)
        return [cand] if cand else []

    if not root.is_dir():
        raise NotADirectoryError(f"Path is not a directory or file: {root}")

    all_paths = [p for p in root.rglob("*") if p.is_file()]
    all_paths.sort(key=lambda p: (
        0 if p.suffix.lower() in {".cont", ".tmp", ".har", ".txt"} else 1,
        -p.stat().st_size if p.exists() else 0,
        str(p).lower(),
    ))

    candidates: list[TempCandidate] = []
    for idx, path in enumerate(all_paths[: max(1, min(max_files, MAX_SCAN_FILES))]):
        cand = analyze_file(path)
        if cand:
            candidates.append(cand)

    candidates.sort(key=lambda c: (c.score, c.request_count, c.response_count, c.size), reverse=True)
    return candidates


def _find_match_positions(path: Path, *, max_positions: int = 300) -> list[int]:
    positions: list[int] = []
    last_pos = -10**12
    for data_offset, data in _iter_chunks(path):
        for regex in (REQUEST_RE, RESPONSE_RE):
            for match in regex.finditer(data):
                pos = data_offset + match.start()
                if pos < 0:
                    pos = match.start()
                if pos - last_pos < 2048:
                    continue
                positions.append(pos)
                last_pos = pos
                if len(positions) >= max_positions:
                    return sorted(positions)
    return sorted(positions)


def _extract_snippets_from_file(
    path: Path,
    *,
    max_file_extract_bytes: int = 2 * 1024 * 1024,
    snippet_before: int = 0,
    snippet_after: int = 96 * 1024,
    include_hosts: list[str] | None = None,
    exclude_hosts: list[str] | None = None,
) -> bytes:
    include_hosts = include_hosts or []
    exclude_hosts = exclude_hosts or []
    positions = _find_match_positions(path)
    if not positions:
        return b""

    parts: list[bytes] = []
    used = 0
    with path.open("rb") as f:
        for pos in positions:
            if used >= max_file_extract_bytes:
                break
            start = max(0, pos - snippet_before)
            f.seek(start)
            data = f.read(min(snippet_after + snippet_before, max_file_extract_bytes - used))
            starts = [m.start() for m in [REQUEST_RE.search(data), RESPONSE_RE.search(data)] if m]
            if starts:
                data = data[min(starts):]
            snippet_hosts = _hosts_from_bytes(data, [])
            if not host_allowed(snippet_hosts, include_hosts, exclude_hosts):
                continue
            header = (
                f"\n{'=' * 80}\n"
                f"BountyOps recovered snippet: {path} @ offset {pos}\n"
                f"{'=' * 80}\n"
            ).encode("utf-8")
            parts.append(header + data)
            used += len(header) + len(data)
    return b"\n".join(parts)


def build_combined_import_text(
    candidates: list[TempCandidate],
    *,
    max_total_bytes: int = 10 * 1024 * 1024,
    candidate_limit: int = 1,
    include_hosts: str | None = None,
    exclude_hosts: str | None = None,
) -> tuple[str, int]:
    include = parse_host_patterns(include_hosts)
    exclude = parse_host_patterns(exclude_hosts)
    filtered = [c for c in candidates if host_allowed(c.hosts, include, exclude)]
    if candidate_limit > 0:
        filtered = filtered[:candidate_limit]

    parts: list[bytes] = []
    total = 0
    used_files = 0
    for cand in filtered:
        path = Path(cand.path)
        remaining = max_total_bytes - total
        if remaining <= 0:
            break
        try:
            if cand.size <= 2 * 1024 * 1024 and cand.kind in {"har-json", "raw-http"}:
                data = path.read_bytes()
                if include or exclude:
                    if not host_allowed(_hosts_from_bytes(data, []), include, exclude):
                        continue
                data = data[:remaining]
            else:
                data = _extract_snippets_from_file(
                    path,
                    max_file_extract_bytes=min(2 * 1024 * 1024, remaining),
                    include_hosts=include,
                    exclude_hosts=exclude,
                )
        except Exception:
            continue
        if not data:
            continue
        header = (
            f"\n{'#' * 80}\n"
            f"BountyOps recovered candidate file: {path}\n"
            f"kind={cand.kind} score={cand.score} size={cand.size} "
            f"requests={cand.request_count} responses={cand.response_count}\n"
            f"{'#' * 80}\n"
        ).encode("utf-8")
        part = header + data
        if total + len(part) > max_total_bytes:
            part = part[: max_total_bytes - total]
        parts.append(part)
        total += len(part)
        used_files += 1
        if total >= max_total_bytes:
            break

    return _safe_decode(b"\n".join(parts)), used_files


def candidates_to_json(candidates: list[TempCandidate]) -> str:
    return json.dumps(
        [
            {
                "path": c.path,
                "size": c.size,
                "kind": c.kind,
                "score": c.score,
                "hosts": c.hosts,
                "request_count": c.request_count,
                "response_count": c.response_count,
            }
            for c in candidates
        ],
        ensure_ascii=False,
        indent=2,
    )
