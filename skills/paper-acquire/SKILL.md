---
name: paper-acquire
description: Use the paperacquire CLI (`pa`) whenever the user needs to find, acquire, organize, inspect, or expand research papers. This includes arXiv IDs, Hugging Face paper pages, AlphaXiv/OpenAlex/CrossRef/DBLP/OpenReview search, top-conference paper collection such as ICLR/NeurIPS/ACL/EMNLP/AAAI, bibliography/reference extraction, citation graphs, paper workspaces, reading state, notes, tags, collections, claim-to-paper maps, and local preview pages. Prefer this skill before inventing related work from memory.
argument-hint: <where|search|venue|ingest-feeds|acquire|list|show|tag|untag|collection|workspace|ws|references|citations|expand|extract-refs|acquire-refs|preview-build|verify|pdf-link> [args]
---

# Paper Acquire

Use `paperacquire` (`pa`) as the CLI source of truth for building a research
paper library. Do not hand-roll paper search, metadata normalization,
bibliography parsing, or citation expansion in prompts when `pa` can do it.

## First Check

Start by checking storage and CLI availability:

```bash
pa where
pa --help
```

If `pa` is missing, install it from this repo. Use the install script bundled
with this skill wherever the skill was installed:

```bash
bash .agents/skills/paper-acquire/scripts/install-paperacquire.sh
# or:
bash ~/.agents/skills/paper-acquire/scripts/install-paperacquire.sh
# or:
bash ~/.codex/skills/paper-acquire/scripts/install-paperacquire.sh
```

Manual install:

```bash
pipx install "git+https://github.com/junjiezhou1122/paperacquire.git"
```

## What This Skill Can Do

Use this skill for these tasks:

- Search papers by topic/query across multiple sources.
- Collect top-conference papers by conference and year.
- Acquire arXiv-backed papers and local markdown artifacts.
- Ingest high-signal paper feeds.
- Parse references from local paper markdown.
- Acquire papers cited by a local bibliography.
- Fetch reference and citation graphs.
- Tag papers, assign collections, and filter the local library.
- Create project workspaces with reading state, notes, and claim-to-paper maps.
- Build a local HTML preview page.
- Verify local index and file consistency.
- Return PDF preview links when known.

## Source Map

`pa search` supports query search:

```text
alphaxiv, openalex, crossref, dblp, huggingface, openreview
```

Example:

```bash
pa search "long-term memory agents" --limit 10
pa search "retrieval augmented memory" --sources openalex,huggingface,openreview --limit 20
pa search "ICLR memory agent" --sources openreview,dblp --limit 20
```

`pa venue` supports conference/year search:

```text
openreview, dblp, all
```

OpenReview is the preferred source for ICLR/NeurIPS-style venue collection.
DBLP is useful for clean CS venue metadata when its public API is available.

`pa ingest-feeds` supports high-signal feeds:

```text
alphaxiv, huggingface
```

## Top-Conference Paper Workflow

When the user asks for "top conference papers", "ICLR 2025 papers",
"NeurIPS accepted papers", "get ACL/EMNLP papers", or similar, use `pa venue`
first.

Inspect conference/year results:

```bash
pa venue ICLR 2024 --source openreview --limit 20
pa venue NeurIPS 2024 --source openreview --limit 20
pa venue ACL 2025 --source all --limit 20
```

Store metadata-only records in the active local library:

```bash
pa venue ICLR 2024 --source openreview --limit 100 --ingest
```

Then inspect:

```bash
pa list
pa show openreview:<openreview_id>
pa preview-build
```

If the user wants a venue-specific local slice, tag the ingested records:

```bash
pa tag openreview:<openreview_id> --add iclr-2024
pa list --tag iclr-2024
```

Important: OpenReview venue search can include submitted, rejected, poster,
spotlight, oral, and accepted labels depending on the venue metadata. Inspect
the `venue` field and OpenReview page before claiming a paper is accepted.
If the task needs only accepted papers, filter/verify against the returned
venue labels or the OpenReview decision page.

If an ingested venue paper has an arXiv ID or Hugging Face/AlphaXiv page, acquire
local markdown artifacts:

```bash
pa acquire <arxiv_id>
```

## Acquire One Paper

Use `pa acquire` when the user provides an arXiv ID or supported paper URL and
wants the paper added to the local library:

```bash
pa acquire 2403.06801
pa acquire "https://huggingface.co/papers/2606.06492"
pa acquire "https://www.alphaxiv.org/abs/2606.06492"
```

`pa acquire` is for arXiv-backed acquisition. OpenReview-only papers can be
stored as metadata via `pa venue ... --ingest`; they may not have local markdown
artifacts unless an arXiv/Hugging Face/AlphaXiv source exists.

## Feed Ingestion

Use feed ingestion when the user asks for recent/high-signal AI papers or wants
to seed a reading list:

```bash
pa ingest-feeds --sources alphaxiv,huggingface --limit 20
pa ingest-feeds --sources huggingface --limit 10
```

## Bibliography And Reference Expansion

Use this when starting from a paper already in the local library:

```bash
pa extract-refs 2403.06801
pa acquire-refs 2403.06801 --limit 12
pa acquire-refs 2403.06801 --min-year 2024 --limit 20
```

Use graph expansion when the user asks for related work, citations,
predecessors, follow-up papers, or citation neighborhoods:

```bash
pa references 2403.06801 --limit 25
pa citations 2403.06801 --limit 25
pa expand 2403.06801 --limit 25
```

## Library Organization

Use tags for conceptual axes and collections for project buckets:

```bash
pa tag 2403.06801 --add method,memory,baseline
pa tag 2403.06801 --remove baseline
pa untag 2403.06801 old-tag
pa collection 2403.06801 memory-systems
pa list --tag memory
pa list --collection memory-systems
```

Suggested tag axes:

```text
role: method, benchmark, survey, baseline-system
claim: C1-retrieval, C2-memory-update, C3-evaluation
status: must-read, cite, reject, maybe
venue: iclr-2024, neurips-2025, acl-2025
```

## Workspaces

Use workspaces for multi-project paper tracking, reading state, notes, and
claim-to-paper maps:

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

## Inspect, Preview, And Verify

Use these before reporting results:

```bash
pa where
pa list
pa show <paper_id>
pa verify
pa preview-build
pa pdf-link <paper_id>
```

## Storage Model

The active library home is resolved in this order:

```text
PAPER_ACQUIRE_HOME
.paperacquire.toml nearest ancestor
.paperacquire/ nearest ancestor
~/.paperacquire
```

Run `pa where` whenever location matters.

## Reporting Rules

When reporting results to the user:

- Say which command was used.
- Distinguish search results from acquired local records.
- Distinguish metadata-only records from arXiv-backed acquired records.
- Mention source limitations, especially OpenReview accepted/submitted labels
  and DBLP API availability.
- Do not claim a paper is accepted or SOTA unless the evidence field/page
  supports that claim.
- If a command fails because a public source is down, report the source failure
  and continue with another source when possible.
