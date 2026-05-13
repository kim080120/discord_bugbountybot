from pathlib import Path

from bountyops.db import Database


db = Database(Path("./data/bountyops.sqlite3"))
db.init()

samples = [
    {
        "name": "Nexon",
        "platform": "FinderGap",
        "reward_min": 0,
        "reward_max": 3000000,
        "source_code": False,
        "has_time_limit": True,
        "time_limit_note": "Weekly maintenance/testing-prohibited window exists.",
        "policy_url": "",
        "scopes": ["*.nexon.com", "*.nexon.co.kr"],
    },
    {
        "name": "Vercel OSS",
        "platform": "HackerOne",
        "reward_min": 0,
        "reward_max": 5000,
        "source_code": True,
        "has_time_limit": False,
        "time_limit_note": "",
        "policy_url": "",
        "scopes": ["github.com/vercel/*", "*.vercel.app"],
    },
]

for s in samples:
    existing = db.get_program_by_name(s["name"])
    if existing:
        continue
    p = db.add_program(
        name=s["name"],
        platform=s["platform"],
        reward_min=s["reward_min"],
        reward_max=s["reward_max"],
        source_code=s["source_code"],
        has_time_limit=s["has_time_limit"],
        time_limit_note=s["time_limit_note"],
        policy_url=s["policy_url"],
    )
    for scope in s["scopes"]:
        db.add_scope_item(
            program_id=p.id,
            type="in",
            value=scope,
            note="sample",
            source_url="",
        )

print("sample data inserted")
