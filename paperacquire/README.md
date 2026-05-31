# Paper Acquisition

Repo-local, code-driven paper acquisition and browsing workflow for the AgentRG project.

## What this package does

This package supports four main workflows:

1. **Acquire one paper**
   - Fetch and store AlphaXiv `overview` markdown when available
   - Fetch and store AlphaXiv `abs` markdown when available
   - Use Hugging Face paper pages as a fallback for metadata / markdown
   - Update the local paper inventory automatically

2. **Search papers by query**
   - Search across:
     - AlphaXiv
     - OpenAlex
     - CrossRef
     - Hugging Face Papers
   - Merge and deduplicate results
   - Return normalized paper metadata

3. **Expand a paper through references and citations**
   - `references`: backward tracing
   - `citations`: forward tracing
   - `expand`: both directions
   - Graph expansion uses OpenAlex and Semantic Scholar

4. **Build a local preview page**
   - Generate a static HTML browser for locally indexed papers
   - Show title, basic metadata, local markdown links, landing page, and PDF preview link

## Current storage layout

The package writes repo-local artifacts under `alphaxiv_papers/`:

- `overview/` — AlphaXiv overview markdown
- `abs/` — paper markdown / abstract-style content
- `index.json` — lightweight local paper inventory with source metadata like `source_topics`
- `graph.json` — reference / citation graph store
- `index.html` — generated static preview page

The important design rule is:
- `index.json` stays lightweight and preview-friendly
- `index.json` keeps `source_topics` as the main topic-oriented metadata field
- `graph.json` stores graph edges and graph-oriented metadata

## CLI entrypoint

Run from the repo root:

```bash
python3 -m paper_acquisition.cli <command>
```

## Commands

### Acquire and index

```bash
python3 -m paper_acquisition.cli acquire 2403.06801
```

Acquire one paper and update `alphaxiv_papers/index.json`.
External IDs such as OpenAlex, DOI, or Semantic Scholar inputs are also accepted when they can be resolved to an arXiv-backed paper.

### Backfill from existing local files

```bash
python3 -m paper_acquisition.cli backfill
```

Rebuild index records from existing `overview/` and `abs/` files.

### Inspect local index

```bash
python3 -m paper_acquisition.cli list
python3 -m paper_acquisition.cli list --source-topic "Agent Systems"
python3 -m paper_acquisition.cli show 2403.06801
python3 -m paper_acquisition.cli verify
```

### Search by topic/query

```bash
python3 -m paper_acquisition.cli search "chest CT report generation"
python3 -m paper_acquisition.cli search "medical agent radiology" --limit 10
python3 -m paper_acquisition.cli search "grounded report generation" --sources alphaxiv,openalex
```

### Graph expansion

```bash
python3 -m paper_acquisition.cli references 2403.06801
python3 -m paper_acquisition.cli citations 2403.06801
python3 -m paper_acquisition.cli expand 2403.06801 --limit 25
```

### Refresh stored source metadata

```bash
python3 -m paper_acquisition.cli reclassify
```

This refreshes source-derived metadata such as title, authors, published date, and `source_topics` for indexed papers. It no longer builds rule-based taxonomy fields.

### Local preview page

```bash
python3 -m paper_acquisition.cli preview-build
```

Builds:

```text
alphaxiv_papers/index.html
```

### PDF preview link

```bash
python3 -m paper_acquisition.cli pdf-link 2403.06801
```

This returns a preview-oriented PDF URL when known.

## PDF policy

PDF support is currently **preview-only**.

That means:
- the system may store `pdf_url` in metadata
- the CLI can expose a PDF link
- the package does **not** bulk-download PDFs by default
- local PDF files are **not** part of the normal acquisition workflow

## Main modules

- `cli.py` — CLI command wiring
- `search.py` — multi-source query search orchestration
- `graph.py` — reference/citation expansion and graph persistence
- `preview.py` — static HTML preview generation
- `index.py` — local paper inventory read/write/verify
- `normalize.py` — input normalization for IDs, URLs, and queries
- `models.py` — normalized record / search / graph schemas
- `paths.py` — repo-local path definitions
- `sources/` — source adapters

## Source adapters

- `sources/alphaxiv.py`
  - paper overview / abs / metadata
  - topic search
- `sources/huggingface.py`
  - paper page metadata / markdown fallback
  - topic search
- `sources/openalex.py`
  - search
  - metadata
  - references / citations
- `sources/crossref.py`
  - search
  - DOI metadata normalization
- `sources/semantic_scholar.py`
  - graph expansion support
- `sources/arxiv.py`
  - canonical arXiv abs / pdf URLs

## Notes

- This package is meant to be the **code-driven source of truth** for paper acquisition in this repo.
- Skills can wrap it, but normal usage should go through the repo code and CLI.
- The package currently focuses on acquisition, search, graph growth, and preview — not full paper analysis/profiling.
