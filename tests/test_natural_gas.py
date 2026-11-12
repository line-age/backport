"""The natural gas import, on a made-up GeoPackage with the stitch script's layout (no
research partner data here; controlplane L-0009)."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiLineString

from backport.natural_gas import key, plan, read, register_agents, resolve_earlier, ulid_uuid

A, B0, B1, B2 = ("lgd:edge:01M6MJ68M8FB4KRZ9189AX5RB" + c for c in "ABCD")
R1, R2 = "lgd:edge:01M6MJ68S5PNDF7GRGXT0E2EPA", "lgd:edge:01M6MJ68S5PNDF7GRGXT0E2EPB"
LINE_A = LineString([(-100, 35), (-99, 35)])
LINE_B = LineString([(-100, 36), (-98, 36)])
BASE = "basemap/ngpipe_base_1929_NA_tst_us.gpkg"
SUB = "1929_1931/ngpipe_sub_1929_1931_tst_us.gpkg"


@pytest.fixture
def stitched(tmp_path):
    traces = tmp_path / "traces"
    (traces / "basemap").mkdir(parents=True)
    (traces / "1929_1931").mkdir()
    gpd.GeoDataFrame({"geometry": [LINE_A, LINE_B]}, crs=4326, index=[1, 2]).to_file(
        traces / BASE, layer="base", driver="GPKG")

    def pipe(id_, geom, fid, split_from=None, time_end=None):
        return {"id": id_, "kind": "base", "existed_from": "../1929-08", "time_start": pd.Timestamp("1929-08-01"),
                    "time_end": pd.Timestamp(time_end) if time_end else pd.NaT, "split_from": split_from,
                    "period": "1929", "period_end_year": 1929, "tracer": "tst", "source": BASE, "source_layer": "base",
                    "source_fid": fid, "geometry": MultiLineString([geom])}

    pipes = gpd.GeoDataFrame([
        pipe(A, LINE_A, 1, time_end="1931-12-31"),                          # ended whole by R1
        pipe(B1, LineString([(-100, 36), (-99, 36)]), 2, split_from=B0),     # the part that carries on
        pipe(B2, LineString([(-99, 36), (-98, 36)]), 2, split_from=B0, time_end="1931-12-31"),  # ended by R2
    ], crs=4326)
    rems = gpd.GeoDataFrame([
        {"id": R1, "period": "1929_1931", "tracer": "tst", "match_score": 1.0, "ends": A, "source": SUB, "source_layer": "sub",
             "source_fid": 1, "geometry": MultiLineString([LINE_A])},
        {"id": R2, "period": "1929_1931", "tracer": "tst", "match_score": 0.97, "ends": B2, "source": SUB, "source_layer": "sub",
             "source_fid": 2, "geometry": MultiLineString([LineString([(-99, 36), (-98, 36)])])},
    ], crs=4326)
    gpkg = tmp_path / "stitched.gpkg"
    pipes.to_file(gpkg, layer="pipelines", driver="GPKG")
    rems.to_file(gpkg, layer="removals", driver="GPKG")
    pd.DataFrame([{"year": 1929, "date": "1929-08", "files": "a.tif", "evidence": "Made-up sheet 1929"},
                  {"year": 1931, "date": "1931", "files": "b.tif", "evidence": "Made-up sheet 1931"}]
                 ).pipe(gpd.GeoDataFrame).to_file(gpkg, layer="sheets", driver="GPKG")
    return gpkg, traces


def test_plan(stitched):
    data = read(*stitched)
    assert len(data.traces) == 2 and len(data.removals) == 2
    b = next(t for t in data.traces if t.split)
    assert b.feature_id == ulid_uuid(B0)                  # the line keeps the id it was split from
    assert b.geometry.equals(MultiLineString([LINE_B]))   # read back whole from the trace file

    bundles = plan(data, {"tst": "agent-tst"}, "agent-stitch")
    sources = bundles[0]["sources"]
    assert [(s["as_of_edtf"], s["external_key"]) for s in sources] == [
        ("1929-08", key("sheet:1929")), ("1931", key("sheet:1931"))]

    claims = [c for x in bundles for c in x.get("claims", [])]
    status = {c["ref"]: c for c in claims if c["attribute"] == "status"}
    traced = status[f"{BASE}/base/1#status"]
    assert (traced["value_text"], traced["valid_edtf"], traced["start_latest"], traced["end_earliest"]) == (
        "operational", "../1929-08", "1929-08-31", "1929-08-01")
    gone = status[f"{SUB}/sub/1#status"]
    assert (gone["value_text"], gone["valid_edtf"], gone["start_earliest"], gone["start_latest"]) == (
        "decommissioned", "1929-08/1931", "1929-08-01", "1931-12-31")
    assert gone["citations"] == [{"citation": f"{SUB}/sub/1#absent", "role": "map_omits"}]
    assert {c["asserted_by"] for c in claims} == {"agent-tst"}

    links = [lk for x in bundles for lk in x.get("links", [])]
    assert sorted((lk["relation"], lk["to"], lk["score"]) for lk in links) == [
        ("overlaps", ulid_uuid(B0), 0.97), ("same_as", ulid_uuid(A), 1.0)]
    assert {lk["asserted_by"] for lk in links} == {"agent-stitch"}

    refs = [r.get("ref") for x in bundles for rows in x.values() for r in rows]
    keys = [r["external_key"]["key"] for x in bundles for rows in x.values() for r in rows]
    assert len(keys) == len(set(keys)) and len([r for r in refs if r]) == len({r for r in refs if r})


def test_refs_from_earlier_bundles_become_ids():
    b = {"citations": [{"ref": "c", "source": "sheet:1929"}],
         "claims": [{"feature": "f", "citations": [{"citation": "c", "role": "map_shows"}]}],
         "links": [{"from": "r", "to": "sheet:1929"}]}
    out = resolve_earlier(b, {"sheet:1929": "11111111-1111-1111-1111-111111111111"})
    assert out["citations"][0]["source"] == "11111111-1111-1111-1111-111111111111"
    assert out["claims"][0]["feature"] == "f"           # same-bundle refs stay refs


def test_every_tracer_needs_an_entry():
    class NoStore:
        def post(self, *_):
            raise AssertionError("should stop before writing")
    with pytest.raises(SystemExit, match="no entry for: sofia"):
        register_agents(NoStore(), {"alex": {"name": "Alex"}}, {"alex", "sofia"}, "abc")
