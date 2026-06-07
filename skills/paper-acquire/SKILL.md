---
name: paper-acquire
description: Use the paperacquire CLI (`pa`) to search, acquire, inspect, tag, organize, and preview research papers. Use when working with arXiv IDs, Hugging Face paper pages, AlphaXiv/OpenAlex/CrossRef/DBLP search, bibliographies, citation/reference graphs, paper workspaces, claim-to-paper maps, or reference packets.
argument-hint: <search|acquire|list|show|where|tag|collection|workspace|ws|references|citations|expand|extract-refs|acquire-refs|preview-build> [args]
---

# Paper Acquire

Use the `paperacquire` CLI as the source of truth for paper ingestion,
literature search, bibliography expansion, and workspace-based paper tracking.

Entrypoint:

```bash
pa <command>
```

If `pa` is missing, install the CLI from the GitHub repo:

```bash
bash ~/.codex/skills/paper-acquire/scripts/install-paperacquire.sh
```

Or install manually:

```bash
pipx install "git+https://github.com/junjiezhou1122/paperacquire.git"
```

## Common Commands

Acquire one paper:

```bash
pa acquire 2403.06801
pa acquire "https://huggingface.co/papers/2606.06492"
```

Search papers:

```bash
pa search "long-term memory agents" --limit 10
pa search "temporal memory retrieval" --sources huggingface,openalex
```

Inspect local library:

```bash
pa where
pa list
pa show 2403.06801
pa verify
```

Tag and collect:

```bash
pa tag 2403.06801 --add method,memory
pa collection 2403.06801 memevo
pa list --tag memory
```

Reference/citation graph:

```bash
pa references 2403.06801
pa citations 2403.06801
pa expand 2403.06801 --limit 25
```

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

## Storage

The library home is resolved in this order:

```text
PAPER_ACQUIRE_HOME
.paperacquire.toml nearest ancestor
.paperacquire/ nearest ancestor
~/.paperacquire
```

Use:

```bash
pa where
```

to see the active storage root.

## Working Rules

- Prefer `pa search` or `pa ingest-feeds` before inventing related work.
- Prefer `pa workspace` for multi-project paper tracking.
- Prefer `pa references`, `pa citations`, and `pa expand` for graph growth.
- Prefer `pa acquire-refs` when expanding from a local bibliography.
- Do not reimplement acquisition logic inside prompts; use the CLI.
- Treat search results as routing signals, not truth. Verify important claims.

