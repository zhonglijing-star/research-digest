#!/usr/bin/env python3
"""Generate the public JSON snapshot used by the Netlify hosted frontend."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import server


OUTPUT = server.SITE / "digest.json"


def write_digest(pending_first_run: bool = False) -> None:
    digest = server.get_digest()
    digest["hosted"] = True
    digest["pending_first_run"] = pending_first_run
    digest["generated_at"] = dt.datetime.now(server.CHINA_TZ).isoformat()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(digest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-only", action="store_true", help="write an empty first-deploy snapshot")
    args = parser.parse_args()

    server.connect().close()
    if not args.seed_only:
        server.do_refresh()
        source_counts = server.refresh_state.get("sources", {})
        if server.refresh_state.get("error") and not any(source_counts.values()):
            raise SystemExit("所有论文来源均未能返回数据；本次不覆盖线上简报。")
        with server.connect() as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        digest = server.get_digest()
        if not digest["articles"]:
            raise SystemExit("检索未生成论文记录；为保留线上旧简报，本次不覆盖 digest.json。")
    write_digest(pending_first_run=args.seed_only)
    print(f"已生成 {OUTPUT}，共 {len(server.get_digest()['articles'])} 篇论文。")


if __name__ == "__main__":
    main()
