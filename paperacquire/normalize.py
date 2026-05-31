import re
from dataclasses import dataclass


ARXIV_ID_RE = re.compile(r"(?P<id>\d{4}\.\d{4,5})(?P<version>v\d+)?$")
ARXIV_IN_TEXT_RE = re.compile(r"(?<!\d)(?P<id>\d{4}\.\d{4,5})(?P<version>v\d+)?(?!\d)")
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
OPENALEX_WORK_RE = re.compile(r"(?:https?://api\.openalex\.org/works/|https?://openalex\.org/)(W\d+)", re.IGNORECASE)
SEMANTIC_SCHOLAR_RE = re.compile(r"(?:https?://)?(?:www\.)?semanticscholar\.org/paper/(?:[^/]+/)?([a-f0-9]{40}|CorpusID:\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class NormalizedInput:
    paper_id: str = ""
    paper_id_input: str = ""
    source_hint: str = "auto"
    source_input: str = ""
    input_kind: str = "paper"
    doi: str = ""
    openalex_id: str = ""
    semantic_scholar_id: str = ""
    query: str = ""



def strip_version(paper_id: str) -> str:
    return re.sub(r"v\d+$", "", paper_id)



def extract_arxiv_id(value: str) -> str | None:
    value = value.strip()
    direct = ARXIV_ID_RE.match(value)
    if direct:
        return direct.group(0)

    match = ARXIV_IN_TEXT_RE.search(value)
    if match:
        return match.group(0)
    return None



def extract_doi(value: str) -> str | None:
    match = DOI_RE.search(value.strip())
    return match.group(0) if match else None



def extract_openalex_id(value: str) -> str | None:
    match = OPENALEX_WORK_RE.search(value.strip())
    return match.group(1).upper() if match else None



def extract_semantic_scholar_id(value: str) -> str | None:
    match = SEMANTIC_SCHOLAR_RE.search(value.strip())
    return match.group(1) if match else None



def detect_source_hint(value: str) -> str:
    lower = value.lower()
    if "alphaxiv.org" in lower:
        return "alphaxiv"
    if "huggingface.co/papers/" in lower:
        return "huggingface"
    if "openalex.org" in lower or "api.openalex.org/works/" in lower:
        return "openalex"
    if "semanticscholar.org" in lower:
        return "semantic_scholar"
    if "doi.org/" in lower:
        return "doi"
    if "arxiv.org" in lower:
        return "arxiv"
    return "auto"



def normalize_input(value: str) -> NormalizedInput:
    source_input = value.strip()
    source_hint = detect_source_hint(source_input)

    paper_id_input = extract_arxiv_id(source_input)
    doi = extract_doi(source_input) or ""
    openalex_id = extract_openalex_id(source_input) or ""
    semantic_scholar_id = extract_semantic_scholar_id(source_input) or ""

    if paper_id_input:
        return NormalizedInput(
            paper_id=strip_version(paper_id_input),
            paper_id_input=paper_id_input,
            source_hint=source_hint,
            source_input=source_input,
            input_kind="paper",
            doi=doi,
            openalex_id=openalex_id,
            semantic_scholar_id=semantic_scholar_id,
        )

    if doi or openalex_id or semantic_scholar_id:
        return NormalizedInput(
            source_hint=source_hint,
            source_input=source_input,
            input_kind="external_id",
            doi=doi,
            openalex_id=openalex_id,
            semantic_scholar_id=semantic_scholar_id,
        )

    if source_input:
        return NormalizedInput(
            source_hint=source_hint,
            source_input=source_input,
            input_kind="query",
            query=source_input,
        )

    raise ValueError("Input cannot be empty")
