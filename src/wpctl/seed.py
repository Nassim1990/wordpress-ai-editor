"""Seed the site registry from a CSV (spec open-decision #2)."""

from __future__ import annotations

import csv
import sys

from .context import AppContext
from .models import Site


def seed_from_csv(ctx: AppContext, path: str) -> int:
    n = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ctx.store.upsert_site(Site(
                slug=row["slug"].strip(),
                domain=row["domain"].strip(),
                wp_path=row["wp_path"].strip(),
                ssh_host=row.get("ssh_host") or None,
                ssh_user=row.get("ssh_user") or None,
                ssh_port=int(row.get("ssh_port") or 22),
                ssh_key_ref=row.get("ssh_key_ref") or None,
                app_user=row.get("app_user") or None,
                app_password_ref=row.get("app_password_ref") or None,
                da_host=row.get("da_host") or None,
                da_account=row.get("da_account") or None,
                dns_provider=(row.get("dns_provider") or "directadmin").strip(),
                active=(row.get("active", "true").strip().lower() != "false"),
                notes=row.get("notes") or None,
            ))
            n += 1
    return n


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m wpctl.seed <sites.csv>", file=sys.stderr)
        raise SystemExit(2)
    ctx = AppContext.build()
    n = seed_from_csv(ctx, sys.argv[1])
    print(f"seeded {n} sites into {ctx.cfg.store} store")


if __name__ == "__main__":
    main()
