# paperacquire

Project-scoped paper acquisition and citation-graph tooling, with first-class
tagging. Forked from AgentRG's `paper_acquisition` and improved to fix two real
pain points found while building a literature base for a research paper:

1. **No project isolation.** The original hard-wired a single global library
   (`AgentRG/alphaxiv_papers`), so papers from every project piled into one
   index. This fork resolves the storage home per project.
2. **No way to slice the library by your own dimensions.** The only metadata was
   auto-generated `source_topics` (e.g. `agents`, `continual-learning`) that tag
   nearly every memory paper identically. This fork adds first-class `tags` and
   `collection` fields plus CLI commands to set and filter them.

## Storage resolution

The library home is resolved at call time, first match wins:

1. `PAPER_ACQUIRE_HOME` environment variable.
2. Nearest ancestor of the current directory with a `.paperacquire.toml` marker
   (uses its `home = "..."` key; relative to the marker; defaults to the marker
   dir if no key).
3. Nearest ancestor with a `.paperacquire/` directory.
4. Fallback: `~/.paperacquire`.

Papers live under `<home>/library/` (`overview/`, `abs/`, `index.json`,
`graph.json`, `index.html`).

Run `pa where` to print the active home, how it was resolved, and the paper
count — so the storage location is never a guess.

### Per-project setup

```bash
# In a project root, pin a local library:
printf 'home = "papers"\n' > .paperacquire.toml
pa where   # confirms home = <project>/papers
```

## Commands

Acquisition / graph (unchanged from upstream): `acquire`, `search`,
`ingest-feeds`, `extract-refs`, `acquire-refs`, `references`, `citations`,
`expand`, `backfill`, `reclassify`, `enrich-hf`, `verify`, `preview-build`,
`pdf-link`, `list`, `show`.

New in this fork:

```bash
pa where                                   # show active library + paths
pa tag <id> --add C6-evolution,method      # add tags
pa tag <id> --remove method                # remove tags
pa untag <id> tagA,tagB                     # remove tags (shorthand)
pa collection <id> memevo-related          # set a collection
pa list --tag C6-evolution                  # filter (comma = AND)
pa list --collection memevo-related         # filter by collection
```

Tags and collection survive re-acquisition (`acquire` merges, it never wipes
manual metadata).

## Suggested tagging scheme

For positioning a paper against related work, tag along orthogonal axes, e.g.:

- role: `method` / `benchmark` / `survey` / `baseline-system`
- claim overlap: `C2-hierarchy` / `C3-forgetting` / `C6-evolution` / ...
- competition: `direct-competitor` / `related` / `cite-only`

## Development

```bash
PYTHONPATH=. python3 -m unittest discover tests   # offline tests, no network
```

Install the `pa` command globally:

```bash
pipx install -e ~/agent/tools/paperacquire
```

## Codex skill distribution

This repo includes a portable Codex skill:

```text
skills/paper-acquire/
```

Install it with Codex's GitHub skill installer:

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo junjiezhou1122/paperacquire \
  --path skills/paper-acquire \
  --method git
```

Then restart Codex so the skill is discovered.

This project is distributed as a CLI plus a thin wrapper skill, not a plugin.
That is intentional: `paperacquire` does not need an MCP server, browser app, or
multi-skill plugin bundle. The skill tells agents how to use `pa`; the Python
package remains the source of truth for acquisition, search, workspace, and graph
logic.
