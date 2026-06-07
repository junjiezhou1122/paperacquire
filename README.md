# paperacquire

[![skills.sh](https://skills.sh/b/junjiezhou1122/paperacquire)](https://skills.sh/junjiezhou1122/paperacquire)

Project-scoped paper acquisition, conference-paper search, citation-graph
expansion, and workspace tracking for research projects.

The CLI keeps paper metadata, notes, local markdown, tags, collections,
claim-to-paper maps, and graph metadata in a project-local library. It is useful
for building a literature base that an agent can search, expand, verify, and
reuse across long research tasks.

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

Core commands:

```bash
pa acquire 2403.06801                              # acquire one arXiv-backed paper
pa search "long-term memory agents" --limit 10     # query search
pa venue ICLR 2025 --source openreview --limit 50  # conference/year search
pa venue NeurIPS 2024 --source all --ingest        # store venue metadata in index
pa ingest-feeds --sources alphaxiv,huggingface     # ingest high-signal feeds
pa references 2403.06801                           # fetch references
pa citations 2403.06801                            # fetch citations
pa expand 2403.06801 --limit 25                    # fetch both directions
pa extract-refs 2403.06801                         # parse local bibliography
pa acquire-refs 2403.06801 --limit 12              # acquire resolved references
pa preview-build                                   # build local HTML preview
pa verify                                          # verify index and files
```

Library organization:

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

Workspace tracking:

```bash
pa workspace new memevo --title "MemEvo Paper"
pa workspace use memevo
pa workspace acquire 2403.06801 2502.12110
pa workspace papers
pa workspace state --paper-id 2403.06801 --new-state read
pa workspace position --claim C6-evolution --papers 2403.06801,2502.12110
pa workspace note 2403.06801 --write "# Notes"
```

`pa ws <cmd>` is an alias for `pa workspace <cmd>`.

## Search sources

`pa search` supports:

```text
alphaxiv, openalex, crossref, dblp, huggingface, openreview
```

`pa venue` supports:

```text
openreview, dblp, all
```

`pa ingest-feeds` supports:

```text
alphaxiv, huggingface
```

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

Install through the skills.sh / Vercel skills CLI:

```bash
npx skills add junjiezhou1122/paperacquire --skill paper-acquire
```

This project is distributed as a CLI plus a thin wrapper skill, not a plugin.
That is intentional: `paperacquire` does not need an MCP server, browser app, or
multi-skill plugin bundle. The skill tells agents how to use `pa`; the Python
package remains the source of truth for acquisition, search, workspace, and graph
logic.
