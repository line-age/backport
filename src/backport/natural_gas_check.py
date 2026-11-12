"""Check an import against the GeoPackage it came from (docs/natural-gas-traces.md, "How we
know it worked"), through the store API:

- every traced line is a section, drawn from the year the GeoPackage starts it;
- every end the stitch proposed is drawn, marked proposed, in the same year;
- every removal match is a proposed link.

    uv run backport-natural-gas-check natural_gas.gpkg --store http://localhost:8000 --token "$LINEAGE_TOKEN"
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict
from pathlib import Path

import geopandas as gpd

from .natural_gas import trace_key, ulid_uuid
from .store import Store


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gpkg", type=Path)
    ap.add_argument("--store", default=os.environ.get("LINEAGE_STORE_URL", "http://localhost:8000"))
    ap.add_argument("--token", default=os.environ.get("LINEAGE_TOKEN"))
    args = ap.parse_args(argv)
    store = Store(args.store, args.token)

    pipes = gpd.read_file(args.gpkg, layer="pipelines")
    rems = gpd.read_file(args.gpkg, layer="removals")
    drawn = defaultdict(list)
    for f in store.get("/sections", network="gas", limit=10000)["features"]:
        drawn[f["properties"]["section_id"]].append(f["properties"])

    problems = []
    groups = pipes.groupby(pipes.apply(trace_key, axis=1))
    for k, g in groups:
        fid = ulid_uuid(min(g.split_from.dropna())) if g.split_from.notna().any() else ulid_uuid(g.iloc[0].id)
        rows = drawn.get(fid)
        if not rows:
            problems.append(f"{k}: not drawn")
            continue
        want_start = str(g.time_start.min().date())
        if {r["time_start"] for r in rows} != {want_start}:
            problems.append(f"{k}: starts {sorted({r['time_start'] for r in rows})}, GeoPackage {want_start}")
        want_ends = sorted({str(d.date()) for d in g.time_end.dropna()})
        got_ends = sorted({r["time_end"] for r in rows if r["time_end"]})
        if want_ends != got_ends:
            problems.append(f"{k}: ends {got_ends}, GeoPackage {want_ends}")
        if any(r["end_status"] == "confirmed" for r in rows):
            problems.append(f"{k}: has a confirmed end; the import should only propose")

    links = store.get("/links", status="proposed", limit=10000)
    row_key = {row.id: trace_key(row) for _, row in pipes.iterrows()}
    want_links = sum(len({row_key[e] for e in r.ends.split("; ")})
                     for _, r in rems.iterrows() if isinstance(r.ends, str) and r.ends)
    print(f"traced lines: {len(groups)} in the GeoPackage, {len(drawn)} drawn sections")
    print(f"rows: {len(pipes)} in the GeoPackage, {sum(len(v) for v in drawn.values())} drawn")
    print(f"proposed links: {want_links} expected, {len(links)} in store")
    if len(links) != want_links:
        problems.append("proposed link count differs")
    for p in problems[:50]:
        print("  " + p)
    if problems:
        raise SystemExit(f"{len(problems)} problems")
    print("ok")


if __name__ == "__main__":
    main()
