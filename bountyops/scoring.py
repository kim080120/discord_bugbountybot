from __future__ import annotations

from dataclasses import dataclass

from .models import Program


@dataclass(slots=True)
class ProgramRank:
    program: Program
    in_scope_count: int
    score: float


def calculate_score(program: Program, in_scope_count: int) -> float:
    scope_score = min(in_scope_count * 5, 35)
    reward_score = min(program.reward_max / 100000, 35)
    source_score = 20 if program.source_code else 0
    time_limit_penalty = -10 if program.has_time_limit else 0
    return round(scope_score + reward_score + source_score + time_limit_penalty, 2)


def rank_programs(programs: list[Program], in_scope_counter: callable, sort_by: str) -> list[ProgramRank]:
    ranks = [
        ProgramRank(
            program=p,
            in_scope_count=in_scope_counter(p.id),
            score=calculate_score(p, in_scope_counter(p.id)),
        )
        for p in programs
    ]

    if sort_by == "scope":
        return sorted(ranks, key=lambda r: (r.in_scope_count, r.program.reward_max), reverse=True)

    if sort_by == "reward":
        return sorted(ranks, key=lambda r: (r.program.reward_max, r.in_scope_count), reverse=True)

    if sort_by == "source":
        return sorted(ranks, key=lambda r: (r.program.source_code, r.in_scope_count, r.program.reward_max), reverse=True)

    if sort_by == "time_limit":
        return sorted(ranks, key=lambda r: (r.program.has_time_limit, r.in_scope_count), reverse=True)

    return sorted(ranks, key=lambda r: r.score, reverse=True)
