"""Storage path resolution for paperacquire.

Unlike the original AgentRG version, the storage root is NO LONGER hard-wired to
the package's parent directory. It is resolved at call time so each project can
keep its own isolated paper library. Resolution order (first match wins):

1. ``PAPER_ACQUIRE_HOME`` environment variable (explicit override).
2. The nearest ancestor of the current working directory containing a
   ``.paperacquire.toml`` marker (uses its ``home`` key, or the marker dir).
3. The nearest ancestor containing a ``.paperacquire/`` directory.
4. Fallback: ``~/.paperacquire`` (a single global library in the user home).

Within the resolved home, papers live under ``<home>/library/``::

    library/
      overview/<id>.overview.md
      abs/<id>.abs.md
      index.json
      graph.json
      index.html

Resolution is intentionally lazy: callers use the accessor functions
(``papers_root()``, ``index_path()`` ...) rather than module-level constants, so
changing ``PAPER_ACQUIRE_HOME`` or the working directory between calls is
respected.
"""

from __future__ import annotations

import os
from pathlib import Path

MARKER_FILE = ".paperacquire.toml"
MARKER_DIR = ".paperacquire"
LIBRARY_SUBDIR = "library"
DEFAULT_GLOBAL_HOME = Path.home() / ".paperacquire"


def _read_marker_home(marker: Path) -> Path | None:
    """Return the library home declared in a ``.paperacquire.toml`` marker.

    Parses with stdlib ``tomllib`` when available, else a minimal ``home = "..."``
    line scan. A relative ``home`` resolves against the marker's own directory.
    A marker with no ``home`` key means "use the marker's directory".
    """
    home_value: str | None = None
    try:
        import tomllib  # Python 3.11+

        with marker.open("rb") as fh:
            data = tomllib.load(fh)
        raw = data.get("home")
        if isinstance(raw, str) and raw.strip():
            home_value = raw.strip()
    except ModuleNotFoundError:
        try:
            for line in marker.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("home") and "=" in stripped:
                    home_value = stripped.split("=", 1)[1].strip().strip("\"'")
                    break
        except OSError:
            home_value = None
    except (OSError, ValueError):
        home_value = None

    if not home_value:
        return marker.parent
    candidate = Path(home_value).expanduser()
    if not candidate.is_absolute():
        candidate = (marker.parent / candidate).resolve()
    return candidate


def _discover_home(start: Path) -> Path | None:
    """Walk up from ``start`` looking for a project-local marker."""
    for parent in [start, *start.parents]:
        marker_file = parent / MARKER_FILE
        if marker_file.is_file():
            resolved = _read_marker_home(marker_file)
            if resolved is not None:
                return resolved
        marker_dir = parent / MARKER_DIR
        if marker_dir.is_dir():
            return marker_dir
    return None


def resolve_home() -> Path:
    """Resolve the active paperacquire home directory (uncached)."""
    env = os.environ.get("PAPER_ACQUIRE_HOME")
    if env and env.strip():
        return Path(env).expanduser().resolve()

    discovered = _discover_home(Path.cwd().resolve())
    if discovered is not None:
        return discovered.resolve()

    return DEFAULT_GLOBAL_HOME


# --- Path accessors (call these; do not cache results across cwd changes) ------


def home_root() -> Path:
    return resolve_home()


def papers_root() -> Path:
    return resolve_home() / LIBRARY_SUBDIR


def overview_dir() -> Path:
    return papers_root() / "overview"


def abs_dir() -> Path:
    return papers_root() / "abs"


def index_path() -> Path:
    return papers_root() / "index.json"


def graph_path() -> Path:
    return papers_root() / "graph.json"


def preview_html_path() -> Path:
    return papers_root() / "index.html"


def ensure_storage_dirs() -> None:
    overview_dir().mkdir(parents=True, exist_ok=True)
    abs_dir().mkdir(parents=True, exist_ok=True)
    papers_root().mkdir(parents=True, exist_ok=True)


def overview_path_for(paper_id: str) -> Path:
    return overview_dir() / f"{paper_id}.overview.md"


def abs_path_for(paper_id: str) -> Path:
    return abs_dir() / f"{paper_id}.abs.md"


def to_repo_relative(path: Path | None) -> str | None:
    """Return ``path`` relative to the active papers root, else its string form.

    Stored index records keep paths relative to the library so the library can be
    moved without rewriting records. Paths outside the current root (e.g. a stale
    absolute path) fall back to the absolute string.
    """
    if path is None:
        return None
    resolved = path.resolve()
    root = papers_root().resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def resolve_stored_path(value: str | None) -> Path | None:
    """Inverse of :func:`to_repo_relative` for reading stored records."""
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return papers_root() / candidate
