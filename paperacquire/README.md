# paperacquire

`paperacquire` is a project-scoped CLI for building and maintaining research
paper libraries.

It supports:

- single-paper acquisition for arXiv-backed papers
- multi-source query search
- conference/year search for top-conference papers
- high-signal feed ingestion
- local bibliography parsing and reference acquisition
- reference/citation graph expansion
- tags, collections, workspaces, notes, reading state, and claim-to-paper maps
- static HTML preview generation

## CLI

```bash
pa <command>
python3 -m paperacquire <command>
```

## Storage

The library home is resolved at runtime:

```text
PAPER_ACQUIRE_HOME
.paperacquire.toml nearest ancestor
.paperacquire/ nearest ancestor
~/.paperacquire
```

Papers and metadata live under:

```text
<home>/library/
```

Use `pa where` to inspect the active storage root and paths.

## Search

```bash
pa search "long-term memory agents" --limit 10
pa search "retrieval augmented memory" --sources openalex,dblp,openreview
```

Supported `pa search` sources:

```text
alphaxiv, openalex, crossref, dblp, huggingface, openreview
```

## Conference Papers

```bash
pa venue ICLR 2025 --source openreview --limit 50
pa venue NeurIPS 2024 --source all --ingest
```

Supported `pa venue` sources:

```text
openreview, dblp, all
```

Without `--ingest`, `pa venue` prints normalized search results. With
`--ingest`, it stores metadata-only records in the local index. Papers with
arXiv IDs can then be acquired with `pa acquire <arxiv_id>` when local markdown
artifacts are needed.

## Acquisition

```bash
pa acquire 2403.06801
pa acquire https://huggingface.co/papers/2606.06492
pa acquire https://www.alphaxiv.org/abs/2606.06492
```

`pa acquire` writes local markdown artifacts when available and updates the
index.

## Graph and Bibliography

```bash
pa references 2403.06801
pa citations 2403.06801
pa expand 2403.06801 --limit 25
pa extract-refs 2403.06801
pa acquire-refs 2403.06801 --limit 12
```

Graph expansion uses normalized graph metadata and persists it beside the local
index.

## Organization

```bash
pa tag 2403.06801 --add method,memory
pa collection 2403.06801 memory-systems
pa list --tag memory
pa workspace new project-name --title "Project Name"
pa workspace use project-name
pa workspace position --claim C1 --papers 2403.06801
pa workspace note 2403.06801 --write "# Notes"
```

`pa ws <cmd>` is an alias for `pa workspace <cmd>`.

## Preview and Verification

```bash
pa preview-build
pa verify
pa pdf-link 2403.06801
```
