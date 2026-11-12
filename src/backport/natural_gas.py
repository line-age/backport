"""Import the stitched natural gas traces into store (docs/natural-gas-traces.md).

Input is the GeoPackage `trace/groundtruth/natural_gas/stitch.py` writes, the folder of
trace files it was stitched from (to read back lines the stitch split), and a tracer file
naming the people behind the tracer codes. The tracer file and the traces are the research
partner's and stay outside this org:

    # natural_gas_tracers.yaml: every tracer code in the traces, with a name and, when
    # known, a GitHub login. Codes that are the same person as a GitHub user become one agent.
    alex:  {name: Alex Example, github: alexexample}
    sofia: {name: Sofia Example}

    uv run backport-natural-gas natural_gas.gpkg "Natural Gas Traces" natural_gas_tracers.yaml \\
        --store http://localhost:8000 --token "$LINEAGE_TOKEN" --stitch-version a318e90

The token needs `--assert-for-others`, because the claims are the tracers', not backport's.
Every row carries an external key, so running it again changes nothing.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import shapely
import yaml
from lineage_model import began_between, by
from shapely.geometry import MultiLineString, mapping
from ulid import ULID

from .store import Store

SYSTEM = "natural_gas_traces"
BATCH = 100


def key(k: str) -> dict:
    return {"system": SYSTEM, "key": k}


def ulid_uuid(lgd_id: str) -> str:
    """`lgd:edge:<ULID>` from the GeoPackage -> the same id as a UUID (plan.md: keep the ids)."""
    return str(ULID.from_str(lgd_id.rsplit(":", 1)[1]).to_uuid())


def valid(v) -> dict:
    return {k: (str(x) if x is not None and not isinstance(x, str) else x) for k, x in v.model_dump().items()}


def as_multi(geom):
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "LineString":
        return MultiLineString([geom])
    if geom.geom_type == "MultiLineString":
        return geom
    lines = [g for g in getattr(geom, "geoms", []) if g.geom_type in ("LineString", "MultiLineString")]
    merged = shapely.line_merge(shapely.union_all(lines)) if lines else None
    return as_multi(merged) if merged is not None and not merged.is_empty else None


# Reading ------------------------------------------------------------------------------------

@dataclass
class Trace:
    """One traced line as the tracer drew it: a section in store."""
    key: str                  # source/layer/fid
    feature_id: str
    geometry: Any
    tracer: str
    sheet_year: int
    rows: list[str]           # GeoPackage row ids that came from it (several if the stitch split it)
    split: bool


@dataclass
class Removal:
    key: str
    feature_id: str
    geometry: Any
    tracer: str
    year_before: int
    year_after: int
    score: float | None
    ends: list[str]           # GeoPackage row ids the stitch ended


@dataclass
class Data:
    sheets: pd.DataFrame
    traces: list[Trace]
    removals: list[Removal]
    row_trace: dict[str, Trace] = field(default_factory=dict)


def trace_key(row) -> str:
    return f"{row['source']}/{row['source_layer']}/{int(row['source_fid'])}"


def read(gpkg: Path, traces_dir: Path) -> Data:
    pipes = gpd.read_file(gpkg, layer="pipelines")
    rems = gpd.read_file(gpkg, layer="removals")
    sheets = gpd.read_file(gpkg, layer="sheets")

    traces = []
    for k, group in pipes.groupby(pipes.apply(trace_key, axis=1), sort=True):
        first = group.iloc[0]
        split = group.split_from.notna().any()
        if split:
            # The stitch cut this line; store keeps it whole (plan.md), so read it back as traced.
            # The earliest ULID it was split from is the line's own id.
            fid = ulid_uuid(min(group.split_from.dropna()))
            geom = as_multi(gpd.read_file(traces_dir / first.source, layer=first.source_layer, fid_as_index=True)
                            .loc[int(first.source_fid)].geometry)
        else:
            fid, geom = ulid_uuid(first.id), first.geometry
        traces.append(Trace(k, fid, geom, first.tracer, int(first.period_end_year), list(group.id), bool(split)))

    removals = []
    for _, r in rems.sort_values("id").iterrows():
        y0, y1 = (int(x) for x in r.period.split("_"))
        removals.append(Removal(trace_key(r), ulid_uuid(r.id), r.geometry, r.tracer, y0, y1,
                                None if pd.isna(r.match_score) else float(r.match_score),
                                [] if pd.isna(r.ends) or not r.ends else r.ends.split("; ")))
    data = Data(sheets, traces, removals)
    data.row_trace = {row: t for t in traces for row in t.rows}
    return data


# Planning -----------------------------------------------------------------------------------

def plan(data: Data, tracer_agents: dict[str, str], stitch_agent: str) -> list[dict]:
    """The bundles to send, in order. Pure: no store needed, so it can be tested."""
    sheet = {int(s.year): s for _, s in data.sheets.iterrows()}
    bundles = [{"sources": [
        {"ref": f"sheet:{y}", "kind": "map_sheet", "title": s.evidence, "as_of_edtf": s.date,
         "identifier": s.files, "external_key": key(f"sheet:{y}")} for y, s in sorted(sheet.items())]}]

    def section_rows(t: Trace) -> tuple[list, list, list]:
        cite = {"ref": f"{t.key}#cite", "source": f"sheet:{t.sheet_year}",
                "locator": f"traced in {t.key}", "external_key": key(f"{t.key}#cite")}
        feat = {"ref": t.key, "id": t.feature_id, "kind": "section", "network": "gas", "external_key": key(t.key)}
        shown = [{"citation": cite["ref"], "role": "map_shows"}]
        when = valid(by(sheet[t.sheet_year].date))
        common = {"feature": t.key, "asserted_by": tracer_agents[t.tracer], "citations": shown, **when}
        claims = [
            {**common, "ref": f"{t.key}#route", "attribute": "route", "value_geom": mapping(t.geometry),
             "external_key": key(f"{t.key}#route")},
            {**common, "ref": f"{t.key}#commodity", "attribute": "commodity", "value_text": "natural_gas",
             "external_key": key(f"{t.key}#commodity")},
            {**common, "ref": f"{t.key}#status", "attribute": "status", "value_text": "operational",
             "external_key": key(f"{t.key}#status")},
        ]
        return [cite], [feat], claims

    for i in range(0, len(data.traces), BATCH):
        b = {"citations": [], "features": [], "claims": []}
        for t in data.traces[i:i + BATCH]:
            c, f, k = section_rows(t)
            b["citations"] += c
            b["features"] += f
            b["claims"] += k
        bundles.append(b)

    for i in range(0, len(data.removals), BATCH):
        b = {"citations": [], "features": [], "claims": [], "links": []}
        for r in data.removals[i:i + BATCH]:
            before, after = sheet[r.year_before], sheet[r.year_after]
            b["citations"] += [
                {"ref": f"{r.key}#shown", "source": f"sheet:{r.year_before}", "locator": f"traced in {r.key}",
                 "external_key": key(f"{r.key}#shown")},
                {"ref": f"{r.key}#absent", "source": f"sheet:{r.year_after}",
                 "locator": f"not on this sheet; traced in {r.key}", "external_key": key(f"{r.key}#absent")},
            ]
            b["features"].append({"ref": r.key, "id": r.feature_id, "kind": "section", "network": "gas",
                                  "external_key": key(r.key)})
            who = tracer_agents[r.tracer]
            b["claims"] += [
                {"ref": f"{r.key}#route", "feature": r.key, "attribute": "route", "value_geom": mapping(r.geometry),
                 "asserted_by": who, **valid(by(before.date)),
                 "citations": [{"citation": f"{r.key}#shown", "role": "map_shows"}],
                 "external_key": key(f"{r.key}#route")},
                {"ref": f"{r.key}#status", "feature": r.key, "attribute": "status", "value_text": "decommissioned",
                 "asserted_by": who, **valid(began_between(before.date, after.date)),
                 "citations": [{"citation": f"{r.key}#absent", "role": "map_omits"}],
                 "external_key": key(f"{r.key}#status")},
            ]
            # One link per traced line the stitch ended: same_as where the whole line ended,
            # overlaps where the stitch cut it (docs/natural-gas-traces.md, step 5).
            seen = set()
            for row in r.ends:
                t = data.row_trace[row]
                if t.key in seen:
                    continue
                seen.add(t.key)
                b["links"].append({
                    "from": r.key, "to": t.feature_id, "relation": "overlaps" if t.split else "same_as",
                    "score": r.score, "asserted_by": stitch_agent,
                    "external_key": key(f"link:{r.key}->{t.key}")})
        bundles.append(b)
    return bundles


# Running ------------------------------------------------------------------------------------

REF_FIELDS = ("source", "parent", "feature", "value_feature", "citation", "from", "to")


def resolve_earlier(bundle: dict, known: dict[str, str]) -> dict:
    """Refs only reach within one bundle; a ref made by an earlier bundle becomes its id."""
    def fix(row: dict) -> dict:
        row = dict(row)
        for f in REF_FIELDS:
            if isinstance(row.get(f), str) and row[f] in known:
                row[f] = known[row[f]]
        if "citations" in row:
            row["citations"] = [fix(c) for c in row["citations"]]
        return row
    return {section: [fix(r) for r in rows] for section, rows in bundle.items()}


def register_agents(store: Store, tracers: dict[str, dict], codes: set[str], stitch_version: str) -> tuple[dict, str]:
    missing = sorted(codes - tracers.keys())
    if missing:
        raise SystemExit(f"the tracer file has no entry for: {', '.join(missing)}")
    agents = {}
    for code in sorted(codes):
        t = tracers[code]
        agents[code] = str(store.post("/agents", {"kind": "person", "name": t["name"], "github_login": t.get("github"),
                                                  "external_key": key(f"tracer:{code}")})["id"])
    stitch = str(store.post("/agents", {"kind": "pipeline", "name": "stitch",
                                        "pipeline": f"trace/groundtruth/natural_gas/stitch.py@{stitch_version}",
                                        "external_key": key(f"stitch@{stitch_version}")})["id"])
    return agents, stitch


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gpkg", type=Path, help="the stitched GeoPackage")
    ap.add_argument("traces", type=Path, help='the "Natural Gas Traces" folder it was stitched from')
    ap.add_argument("tracers", type=Path, help="tracer codes -> names and GitHub logins")
    ap.add_argument("--store", default=os.environ.get("LINEAGE_STORE_URL", "http://localhost:8000"))
    ap.add_argument("--token", default=os.environ.get("LINEAGE_TOKEN"))
    ap.add_argument("--stitch-version", required=True, help="the trace commit that built the GeoPackage")
    args = ap.parse_args(argv)
    if not args.token:
        raise SystemExit("needs --token or LINEAGE_TOKEN: a store pipeline token with --assert-for-others")

    data = read(args.gpkg, args.traces)
    store = Store(args.store, args.token)
    tracers = yaml.safe_load(args.tracers.read_text())
    codes = {t.tracer for t in data.traces} | {r.tracer for r in data.removals}
    agents, stitch = register_agents(store, tracers, codes, args.stitch_version)

    bundles = plan(data, agents, stitch)
    made = kept = 0
    known: dict[str, str] = {}
    for i, b in enumerate(bundles, 1):
        res = store.post("/bundles", resolve_earlier(b, known))
        known.update({k: str(v) for k, v in res["ids"].items()})
        made += sum(res["created"].values())
        kept += sum(not v for v in res["created"].values())
        print(f"\rbundle {i}/{len(bundles)}", end="", file=sys.stderr)
    print(file=sys.stderr)
    n_links = sum(len(b.get("links", [])) for b in bundles)
    print(f"{len(data.traces)} sections ({sum(t.split for t in data.traces)} read back whole after a split), "
          f"{len(data.removals)} removals, {n_links} proposed links")
    print(f"rows created {made}, already there {kept}")


if __name__ == "__main__":
    main()
