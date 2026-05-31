import re
from pathlib import Path

from .models import PaperRecord
from .normalize import strip_version
from .paths import abs_dir, overview_dir, to_repo_relative


TITLE_PREFIXES = ("###", "##", "#")


def _clean_title(text: str) -> str:
    text = text.strip()
    for prefix in TITLE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    text = re.sub(r"^Detailed Report:\s*", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text)


def infer_title_from_overview(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("#"):
            return _clean_title(line)
    return ""


def infer_title_from_abs(path: Path) -> str:
    lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:8] if line.strip()]
    if not lines:
        return ""
    title_lines: list[str] = []
    for line in lines:
        if re.fullmatch(r"\d+", line):
            continue
        if "@" in line:
            break
        title_lines.append(line)
        if len(title_lines) >= 2:
            break
    return _clean_title(" ".join(title_lines))


def build_backfill_records() -> list[PaperRecord]:
    grouped: dict[str, dict[str, Path]] = {}
    for path in overview_dir().glob("*.overview.md"):
        paper_id = strip_version(path.name.replace(".overview.md", ""))
        grouped.setdefault(paper_id, {})["overview"] = path
    for path in abs_dir().glob("*.abs.md"):
        paper_id = strip_version(path.name.replace(".abs.md", ""))
        grouped.setdefault(paper_id, {})["abs"] = path

    records: list[PaperRecord] = []
    for paper_id, files in sorted(grouped.items()):
        overview_path = files.get("overview")
        abs_path = files.get("abs")
        title = ""
        if overview_path:
            title = infer_title_from_overview(overview_path)
        if not title and abs_path:
            title = infer_title_from_abs(abs_path)
        records.append(
            PaperRecord(
                paper_id=paper_id,
                title=title,
                source="alphaxiv",
                sources=["alphaxiv"],
                source_input=paper_id,
                canonical_url=f"https://arxiv.org/abs/{paper_id}",
                overview_path=to_repo_relative(overview_path),
                abs_path=to_repo_relative(abs_path),
                identifiers={"arxiv_id": paper_id},
                pdf_url=f"https://arxiv.org/pdf/{paper_id}.pdf",
                landing_page_url=f"https://arxiv.org/abs/{paper_id}",
                status={
                    "overview": "present" if overview_path else "missing",
                    "abs": "present" if abs_path else "missing",
                },
                source_topics=[],
            )
        )
    return records
