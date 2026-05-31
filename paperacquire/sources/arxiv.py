from dataclasses import dataclass


@dataclass
class ArxivInfo:
    canonical_url: str
    pdf_url: str


def canonical_abs_url(paper_id: str) -> str:
    return f"https://arxiv.org/abs/{paper_id}"


def canonical_pdf_url(paper_id: str) -> str:
    return f"https://arxiv.org/pdf/{paper_id}.pdf"


def get_arxiv_info(paper_id: str) -> ArxivInfo:
    return ArxivInfo(canonical_url=canonical_abs_url(paper_id), pdf_url=canonical_pdf_url(paper_id))
