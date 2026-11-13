# backport

Lineage import of existing spreadsheets and traces into store.

Part of [Lineage](https://github.com/line-age/controlplane). What this component takes in,
what it puts out, and what it depends on are described in the controlplane's
[components.md](https://github.com/line-age/controlplane/blob/main/components.md#backport).

Work is tracked in the [Backport](https://github.com/orgs/line-age/projects/6) project. The
team lead is [@gregariouspanda](https://github.com/gregariouspanda). If that changes, the
[controlplane's table](https://github.com/line-age/controlplane#projects-and-leads) is updated first.

## Imports

| Import | Doc | Command |
| --- | --- | --- |
| The natural gas traces | [docs/natural-gas-traces.md](docs/natural-gas-traces.md) | `backport-natural-gas`, then `backport-natural-gas-check` |

Each import writes through the `store` API with a pipeline token, and every row it writes
carries an external key, so an import can run again without duplicating anything. The
research partner's data never goes in this repo (controlplane L-0009); the commands take
paths. The tests use made-up data in the same shape.

Every import runs as a container (`Dockerfile`): one job per run, data mounted read-only.
The import docs show the commands. For working on the code:

```sh
uv sync
uv run pytest
```
