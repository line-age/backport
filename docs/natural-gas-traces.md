# Natural gas traces into store

The plan for `backport`'s first import: the research partner's natural gas traces, already
stitched into one GeoPackage. This is the first real data in `store` (controlplane L-0013),
and the data `review` starts iterating on.

How the GeoPackage maps onto the model is in `store`'s
[docs/plan.md](https://github.com/line-age/store/blob/main/docs/plan.md#how-the-geopackage-maps-onto-the-model);
this page is about the import itself.

## The input

One GeoPackage built in `trace` from the research partner's trace files. The data is
theirs, so it never goes in this repo (L-0009); the importer takes a path.

| Layer | Rows | What it is |
| --- | --- | --- |
| `pipelines` | 2,372 | 679 lines from the 1929 base trace and 1,693 added in sixteen sheet-to-sheet periods to 1997; 94 of the rows are pieces of 48 lines split where a removal was matched to part of them |
| `removals` | 182 | lines the tracers marked as gone between two sheets; 51 matched to a traced line, 33 partly, 98 not at all |
| `sheets` | 17 | the date used for each period boundary, and the text on the sheet it came from |

Every row in `pipelines` and `removals` carries `source`, `source_layer` and `source_fid`,
which lead back to the original trace file. The `basemap_1929` and `us_states_2018` layers
are context for QGIS and are not imported.

What the stitch left out, on purpose:

- 25 traced features with no geometry.
- Two "backdating" files whose meaning we don't know yet.

## Steps

1. **Sources.** One `map_sheet` source per `sheets` row, with the date as `as_of_edtf`.
2. **Agents.** One person agent per tracer code in the filenames, and one pipeline agent for
   the stitch script, at the commit that built the GeoPackage.
3. **Sections.** One section per traced line, rebuilt whole: split pieces are grouped by
   `split_from` and the original read from its `source_fid`. Each gets a `route`, a
   `commodity` and a `status: operational` claim with its `existed_from`, all cited to the
   sheet it first appears on.
4. **Removals.** One section per removal, with a `route` claim cited to the earlier sheet
   and an end of `status` cited to the later one.
5. **Proposed links.** Each match the stitch proposed becomes a `same_as` (matched) or
   `overlaps` (partial) link, status `proposed`, with its score. These are the first
   things a person reviews.
6. **External keys** for everything, so a second run updates and does not duplicate.

## How we know it worked

- Counts reconcile: 2,324 traced lines in, 2,324 sections out (2,372 rows less the 48
  extra pieces), 182 removals, 90 proposed links (from the 84 removals that matched something).
- Every claim has at least one citation, and every row has an audit entry naming the
  agent.
- `release` v0 rebuilds a GeoPackage that matches the input, split pieces included (rebuilt
  from the links). This is `store`'s first finish line.

## Waiting on the research partner

- What a `sub` file means exactly. The import assumes "on the earlier sheet, gone from the
  later one".
- Which of two same-year sheets was traced, where a year has two. Until then the date used
  is the one true of both.
- What the backdating files are. They are probably the first non-geometry claims in this
  data (an earlier start date for a line), which would make them the first real test of the
  loop.
