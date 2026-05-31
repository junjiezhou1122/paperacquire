from __future__ import annotations

import html
import re
from pathlib import Path

from .index import list_records
from .paths import preview_html_path, resolve_stored_path


def build_preview_page() -> Path:
    records = list_records()
    list_items = [render_list_item(record, order=index, selected=index == 0) for index, record in enumerate(records)]
    detail_panes = [render_detail_pane(record, selected=index == 0) for index, record in enumerate(records)]
    filter_options = ''.join(
        f'<option value="{html.escape(label)}">{html.escape(label)}</option>'
        for label in sorted({label for record in records for label in _labels_for_record(record)}, key=str.lower)
    )
    count_label = f"{len(records)} papers"

    html_text = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>AgentRG Paper Preview</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #fbf7f2;
      --panel: #fffdfa;
      --line: #ddd1c5;
      --line-soft: #ebe2d8;
      --text: #2d1c1d;
      --muted: #7f6b67;
      --chip-blue: #cbe8ff;
      --chip-green: #d8efde;
      --chip-peach: #f8e0d3;
      --chip-lavender: #e7def6;
      --shadow: 0 16px 40px rgba(66, 38, 28, 0.05);
      --ui-font: \"Avenir Next\", \"Helvetica Neue\", Arial, sans-serif;
      --display-font: \"Iowan Old Style\", \"Palatino Linotype\", Georgia, serif;
    }}

    * {{ box-sizing: border-box; }}
    html {{ height: 100%; scroll-behavior: smooth; }}
    body {{
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: var(--ui-font);
      overflow: hidden;
    }}

    a {{ color: inherit; }}
    button, input, select {{ font: inherit; }}

    .shell {{
      width: 100%;
      height: 100vh;
    }}

    .workspace {{
      display: grid;
      grid-template-columns: clamp(280px, 32vw, 420px) minmax(0, 1fr);
      height: 100vh;
      background: var(--panel);
      border-top: 1px solid var(--line-soft);
    }}

    .rail {{
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
      min-height: 0;
      padding: 18px 20px 0;
      border-right: 1px solid var(--line-soft);
      background:
        radial-gradient(circle at 70% 20%, rgba(193, 226, 255, 0.28), transparent 34%),
        radial-gradient(circle at 30% 70%, rgba(250, 229, 214, 0.28), transparent 26%),
        var(--panel);
      overflow: hidden;
    }}

    .viewer {{
      min-width: 0;
      overflow: hidden;
      background: var(--panel);
    }}

    .eyebrow {{
      margin: 0;
      font-size: 0.76rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
      color: var(--muted);
    }}

    .hero-title {{
      margin: 0;
      max-width: none;
      font-family: var(--display-font);
      font-size: 1.15rem;
      line-height: 1.2;
      letter-spacing: -0.015em;
      font-weight: 700;
    }}

    .hero-copy {{
      display: none;
    }}

    .rail-top {{
      display: grid;
      gap: 4px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--line);
    }}

    .count-chip {{
      display: inline-flex;
      align-items: center;
      width: fit-content;
      padding: 4px 9px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
      color: var(--text);
      font-size: 0.76rem;
      line-height: 1;
      font-weight: 600;
      box-shadow: none;
      white-space: nowrap;
    }}

    .list-wrap {{
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      margin-top: 0;
      min-height: 0;
      padding-top: 6px;
      overflow: hidden;
    }}

    .list-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
      position: sticky;
      top: 0;
      z-index: 2;
      padding-bottom: 6px;
      background: color-mix(in srgb, var(--panel) 92%, transparent);
      backdrop-filter: blur(6px);
    }}

    .list-title {{
      margin: 0;
      font-size: 0.84rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 800;
      color: var(--muted);
    }}

    .paper-list {{
      display: grid;
      align-content: start;
      gap: 0;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding-right: 6px;
      padding-bottom: 24px;
    }}

    .list-empty {{
      margin: 18px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
    }}

    .paper-item {{
      width: 100%;
      text-align: left;
      border: 0;
      border-bottom: 1px solid var(--line-soft);
      background: transparent;
      padding: 16px 0 18px;
      cursor: pointer;
      color: inherit;
      transition: opacity 160ms ease, transform 160ms ease;
    }}

    .paper-item:hover {{
      opacity: 0.86;
    }}

    .paper-item.is-selected {{
      opacity: 1;
    }}

    .paper-item.is-selected h2 {{
      text-decoration: underline;
      text-decoration-thickness: 1px;
      text-underline-offset: 0.18em;
      text-decoration-color: var(--line);
    }}

    .paper-item h2 {{
      margin: 0;
      font-size: 1.18rem;
      line-height: 1.3;
      font-weight: 700;
      letter-spacing: -0.03em;
    }}

    .paper-meta {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.55;
    }}

    .pill-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}

    .pill {{
      display: inline-flex;
      align-items: center;
      padding: 5px 10px;
      border-radius: 999px;
      background: #f3ede6;
      color: var(--muted);
      font-size: 0.78rem;
      line-height: 1;
      white-space: nowrap;
    }}

    .paper-item.is-selected .pill {{
      background: #eee5db;
      color: var(--text);
    }}

    .stats-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}

    .stat-badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 10px;
      border-radius: 999px;
      border: 1px solid var(--line-soft);
      background: rgba(255, 255, 255, 0.72);
      color: var(--text);
      font-size: 0.78rem;
      line-height: 1;
      white-space: nowrap;
    }}

    .stat-badge-label {{
      color: var(--muted);
      font-weight: 600;
    }}

    .stat-badge-value {{
      font-weight: 700;
    }}

    .paper-item.is-selected .stat-badge {{
      background: #f6efe6;
      border-color: var(--line);
    }}

    .detail-pane {{
      display: none;
      height: 100vh;
      grid-template-rows: auto minmax(0, 1fr);
    }}

    .detail-empty {{
      display: grid;
      place-items: center;
      height: 100vh;
      padding: 32px;
    }}

    .detail-empty-inner {{
      width: 100%;
      max-width: 920px;
    }}

    .detail-pane.is-active {{
      display: grid;
    }}

    .detail-head {{
      padding: 16px 24px 12px;
      border-bottom: 1px solid var(--line-soft);
    }}

    .detail-kicker {{
      display: none;
    }}

    .detail-title {{
      margin: 0;
      max-width: 34ch;
      font-family: var(--display-font);
      font-size: clamp(1.35rem, 1.8vw, 1.9rem);
      line-height: 1.14;
      letter-spacing: -0.02em;
      font-weight: 700;
    }}

    .detail-copy {{
      margin: 8px 0 0;
      max-width: 56rem;
      font-size: 0.92rem;
      line-height: 1.45;
      color: color-mix(in srgb, var(--text) 84%, white);
    }}

    .detail-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }}

    .detail-links a {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: transparent;
      text-decoration: none;
      font-size: 0.86rem;
      font-weight: 600;
      box-shadow: none;
    }}

    .detail-enrichment {{
      display: grid;
      gap: 14px;
      margin-top: 14px;
    }}

    .detail-meta-card {{
      display: grid;
      gap: 10px;
      padding: 14px 16px;
      border: 1px solid var(--line-soft);
      border-radius: 18px;
      background: color-mix(in srgb, white 84%, var(--bg));
    }}

    .detail-meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }}

    .detail-meta-row {{
      display: grid;
      gap: 4px;
    }}

    .detail-meta-label {{
      color: var(--muted);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}

    .detail-meta-value {{
      font-size: 0.95rem;
      line-height: 1.45;
      word-break: break-word;
    }}

    .detail-keywords {{
      display: grid;
      gap: 8px;
    }}

    .summary-card {{
      display: grid;
      gap: 8px;
      padding: 16px 18px;
      border: 1px solid var(--line-soft);
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(248, 241, 233, 0.86));
    }}

    .summary-card p {{
      margin: 0;
      font-size: 0.98rem;
      line-height: 1.7;
      color: color-mix(in srgb, var(--text) 90%, white);
    }}

    .summary-card.is-collapsed p {{
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 6;
      overflow: hidden;
    }}

    .summary-toggle {{
      width: fit-content;
      padding: 0;
      border: 0;
      background: transparent;
      color: var(--text);
      font-size: 0.86rem;
      font-weight: 700;
      cursor: pointer;
      text-decoration: underline;
      text-underline-offset: 0.18em;
    }}

    .detail-body {{
      overflow: auto;
      padding: 16px 24px 32px;
    }}

    .content-label {{
      margin: 0 0 18px;
      font-size: 0.8rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-weight: 700;
      color: var(--muted);
    }}

    .markdown {{
      max-width: 920px;
      font-size: 1rem;
      line-height: 1.72;
      color: color-mix(in srgb, var(--text) 92%, white);
    }}

    .rail-search {{
      margin-top: 10px;
      padding: 10px 0 8px;
      border-bottom: 1px solid var(--line);
      display: grid;
      gap: 10px;
    }}

    .search-field {{
      display: flex;
      align-items: center;
      min-height: 42px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,0.78);
    }}

    .search-input {{
      width: 100%;
      border: 0;
      outline: 0;
      background: transparent;
      color: var(--text);
      font-size: 0.95rem;
    }}

    .search-input::placeholder {{
      color: color-mix(in srgb, var(--muted) 88%, white);
    }}

    .search-controls {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 8px;
    }}

    .search-select {{
      width: 100%;
      min-height: 38px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255,255,255,0.78);
      color: var(--text);
      outline: 0;
    }}

    mark.search-hit {{
      background: color-mix(in srgb, var(--chip-peach) 78%, white);
      color: inherit;
      padding: 0 0.08em;
      border-radius: 0.2em;
    }}

    .markdown h1,
    .markdown h2,
    .markdown h3,
    .markdown h4,
    .markdown h5,
    .markdown h6 {{
      line-height: 1.24;
      letter-spacing: -0.02em;
      margin: 2rem 0 0.8rem;
      color: var(--text);
    }}

    .markdown h1 {{ font-size: 1.7rem; }}
    .markdown h2 {{ font-size: 1.4rem; }}
    .markdown h3 {{ font-size: 1.2rem; }}
    .markdown h4 {{ font-size: 1.05rem; }}
    .markdown p {{ margin: 0 0 1rem; }}
    .markdown ul,
    .markdown ol {{ margin: 0 0 1.15rem; padding-left: 1.3rem; }}
    .markdown li + li {{ margin-top: 0.35rem; }}
    .markdown blockquote {{
      margin: 1.5rem 0;
      padding: 0.15rem 0 0.15rem 1rem;
      border-left: 1px solid var(--line);
      color: var(--muted);
    }}

    .markdown a {{
      color: inherit;
      text-decoration-color: var(--line);
      text-underline-offset: 0.15em;
    }}

    .markdown code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.88em;
      padding: 0.1rem 0.35rem;
      border-radius: 0.35rem;
      background: #f4eee7;
    }}

    .markdown pre {{
      margin: 1.4rem 0;
      padding: 1rem 1.1rem;
      overflow: auto;
      border-radius: 18px;
      border: 1px solid var(--line-soft);
      background: #fcf8f3;
    }}

    .markdown pre code {{
      padding: 0;
      background: transparent;
      border-radius: 0;
    }}

    .markdown hr {{
      border: 0;
      border-top: 1px solid var(--line);
      margin: 1.8rem 0;
    }}

    .empty-state {{
      margin: 0;
      color: var(--muted);
      font-size: 1rem;
    }}

    @media (max-width: 760px) {{
      body {{ overflow: auto; }}
      .shell,
      .workspace,
      .detail-pane {{ height: auto; }}
      .workspace {{ grid-template-columns: 1fr; }}
      .rail {{
        grid-template-rows: auto auto auto;
        border-right: 0;
        border-bottom: 1px solid var(--line-soft);
        padding: 20px 20px 0;
        overflow: visible;
      }}
      .list-wrap,
      .paper-list,
      .viewer,
      .detail-body {{ overflow: visible; }}
      .list-wrap {{ display: block; }}
      .list-head {{
        position: static;
        padding-bottom: 0;
        background: transparent;
        backdrop-filter: none;
      }}
      .detail-head {{ padding: 20px; }}
      .detail-body {{ padding: 20px; }}
    }}
  </style>
</head>
<body>
  <main class=\"shell\">
    <section class=\"workspace\">
      <aside class=\"rail\">
        <div class=\"rail-top\">
          <p class=\"eyebrow\">Paper preview library</p>
          <h1 class=\"hero-title\">Local papers</h1>
        </div>

        <section class=\"rail-search\">
          <label class=\"search-field\" for=\"paper-search\">
            <input id=\"paper-search\" class=\"search-input\" type=\"search\" placeholder=\"Search title, author, venue...\" autocomplete=\"off\" spellcheck=\"false\" />
          </label>
          <div class=\"search-controls\">
            <select id=\"paper-filter\" class=\"search-select\" aria-label=\"Filter papers by source\">
              <option value=\"\">All sources</option>
              {filter_options}
            </select>
            <select id=\"paper-sort\" class=\"search-select\" aria-label=\"Sort papers\">
              <option value=\"default\">Recent added</option>
              <option value=\"title\">Title A–Z</option>
              <option value=\"year_desc\">Year newest</option>
              <option value=\"year_asc\">Year oldest</option>
            </select>
          </div>
        </section>

        <section class=\"list-wrap\">
          <div class=\"list-head\">
            <p class=\"list-title\">Saved papers</p>
            <span class=\"count-chip\" data-paper-count>{html.escape(count_label)}</span>
          </div>
          <div class=\"paper-list\">{''.join(list_items)}</div>
          <p class=\"list-empty\" data-list-empty hidden>No papers match your search.</p>
        </section>
      </aside>

      <section class=\"viewer\">{''.join(detail_panes)}
        <article class=\"detail-empty\" data-detail-empty hidden>
          <div class=\"detail-empty-inner\">
            <p class=\"content-label\">Rendered overview</p>
            <p class=\"empty-state\">No papers match your search.</p>
          </div>
        </article>
      </section>
    </section>
  </main>

  <script>
    const items = Array.from(document.querySelectorAll('[data-paper-target]'));
    const panes = Array.from(document.querySelectorAll('[data-paper-pane]'));
    const list = document.querySelector('.paper-list');
    const searchInput = document.getElementById('paper-search');
    const filterSelect = document.getElementById('paper-filter');
    const sortSelect = document.getElementById('paper-sort');
    const countChip = document.querySelector('[data-paper-count]');
    const listEmpty = document.querySelector('[data-list-empty]');
    const detailEmpty = document.querySelector('[data-detail-empty]');

    items.forEach((item) => {{
      const title = item.querySelector('[data-paper-title]');
      const meta = item.querySelector('[data-paper-meta]');
      item.dataset.originalTitle = title?.textContent || '';
      item.dataset.originalMeta = meta?.textContent || '';
    }});

    function escapeRegExp(value) {{
      return value.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\$&');
    }}

    function highlightText(text, query) {{
      if (!query) return text;
      const pattern = new RegExp(`(${{escapeRegExp(query)}})`, 'ig');
      return text.replace(pattern, '<mark class="search-hit">$1</mark>');
    }}

    function updateHighlights(query) {{
      const normalized = query.trim();
      items.forEach((item) => {{
        const title = item.querySelector('[data-paper-title]');
        const meta = item.querySelector('[data-paper-meta]');
        if (title) title.innerHTML = highlightText(item.dataset.originalTitle || '', normalized);
        if (meta) meta.innerHTML = highlightText(item.dataset.originalMeta || '', normalized);
      }});
    }}

    function visibleItems() {{
      return items.filter((item) => !item.hidden);
    }}

    function updateCount() {{
      if (!countChip) return;
      const visible = visibleItems().length;
      countChip.textContent = `${{visible}} paper${{visible === 1 ? '' : 's'}}`;
    }}

    function sortItems(mode) {{
      if (!list) return;
      const sorted = [...items].sort((a, b) => {{
        if (mode === 'title') return (a.dataset.sortTitle || '').localeCompare(b.dataset.sortTitle || '');
        if (mode === 'year_desc') return Number(b.dataset.sortYear || -Infinity) - Number(a.dataset.sortYear || -Infinity);
        if (mode === 'year_asc') return Number(a.dataset.sortYear || Infinity) - Number(b.dataset.sortYear || Infinity);
        return Number(a.dataset.sortOrder || 0) - Number(b.dataset.sortOrder || 0);
      }});
      sorted.forEach((item) => list.appendChild(item));
    }}

    function setActivePaper(key) {{
      let matched = false;
      items.forEach((item) => {{
        const active = !item.hidden && item.dataset.paperTarget === key;
        item.classList.toggle('is-selected', active);
        if (active) matched = true;
      }});
      panes.forEach((pane) => {{
        const active = pane.dataset.paperPane === key;
        pane.classList.toggle('is-active', matched && active);
        if (matched && active) {{
          const body = pane.querySelector('.detail-body');
          if (body) body.scrollTop = 0;
        }}
      }});
      if (detailEmpty) detailEmpty.hidden = matched;
      if (matched) {{
        history.replaceState(null, '', '#' + encodeURIComponent(key));
      }}
    }}

    function applyControls() {{
      const query = searchInput?.value || '';
      const normalized = query.trim().toLowerCase();
      const filterValue = filterSelect?.value || '';
      const sortValue = sortSelect?.value || 'default';

      sortItems(sortValue);
      items.forEach((item) => {{
        const haystack = item.dataset.searchText || '';
        const labels = (item.dataset.filterLabels || '').split(/\\s+/).filter(Boolean);
        const searchMatch = normalized ? haystack.includes(normalized) : true;
        const filterMatch = filterValue ? labels.includes(filterValue) : true;
        item.hidden = !(searchMatch && filterMatch);
      }});

      updateHighlights(query);
      const visible = visibleItems();
      if (listEmpty) listEmpty.hidden = visible.length > 0;
      updateCount();

      const selectedVisible = visible.find((item) => item.classList.contains('is-selected'));
      const nextKey = selectedVisible?.dataset.paperTarget || visible[0]?.dataset.paperTarget;
      if (nextKey) {{
        setActivePaper(nextKey);
      }} else {{
        items.forEach((item) => item.classList.remove('is-selected'));
        panes.forEach((pane) => pane.classList.remove('is-active'));
        if (detailEmpty) detailEmpty.hidden = false;
      }}
    }}

    items.forEach((item) => {{
      item.addEventListener('click', () => setActivePaper(item.dataset.paperTarget));
    }});

    if (searchInput) {{
      searchInput.addEventListener('input', applyControls);
    }}
    if (filterSelect) {{
      filterSelect.addEventListener('change', applyControls);
    }}
    if (sortSelect) {{
      sortSelect.addEventListener('change', applyControls);
    }}

    document.querySelectorAll('[data-summary-toggle]').forEach((toggle) => {{
      toggle.addEventListener('click', (event) => {{
        event.preventDefault();
        event.stopPropagation();
        const card = toggle.closest('[data-summary-card]');
        if (!card) return;
        const isCollapsed = card.classList.toggle('is-collapsed');
        toggle.textContent = isCollapsed ? 'Expand summary' : 'Collapse summary';
      }});
    }});

    const hashKey = decodeURIComponent(window.location.hash.slice(1) || '');
    const initialKey = items.find((item) => item.dataset.paperTarget === hashKey)?.dataset.paperTarget || items[0]?.dataset.paperTarget;
    if (initialKey) setActivePaper(initialKey);
    applyControls();
  </script>
</body>
</html>
"""
    preview_html_path().write_text(html_text, encoding="utf-8")
    return preview_html_path()



def render_list_item(record: dict, order: int, selected: bool = False) -> str:
    key = _record_key(record)
    title = html.escape(record.get("title") or record.get("paper_id") or "Untitled paper")
    meta_html = html.escape(_meta_line(record))
    labels = _labels_for_record(record)
    pills = ''.join(_pill_html(label) for label in labels)
    stats_html = _list_stats_html(record)
    search_text = html.escape(_search_text(record), quote=True)
    filter_labels = html.escape(" ".join(labels), quote=True)
    sort_title = html.escape(_sort_title(record), quote=True)
    sort_year = html.escape(_sort_year(record), quote=True)
    state_class = " is-selected" if selected else ""
    return f"""
    <button class=\"paper-item{state_class}\" type=\"button\" data-paper-target=\"{html.escape(key)}\" data-search-text=\"{search_text}\" data-filter-labels=\"{filter_labels}\" data-sort-order=\"{order}\" data-sort-title=\"{sort_title}\" data-sort-year=\"{sort_year}\">
      <h2 data-paper-title>{title}</h2>
      <p class=\"paper-meta\" data-paper-meta>{meta_html}</p>
      <div class=\"pill-row\">{pills}</div>
      {stats_html}
    </button>
    """



def _list_stats_html(record: dict) -> str:
    stats: list[tuple[str, str]] = []
    github_stars = record.get("github_stars")
    upvotes = record.get("upvotes")
    if github_stars is not None:
        stats.append(("GitHub ★", str(github_stars)))
    if upvotes is not None:
        stats.append(("HF ↑", str(upvotes)))
    if not stats:
        return ""
    badges = "".join(
        f'<span class="stat-badge"><span class="stat-badge-label">{html.escape(label)}</span><span class="stat-badge-value">{html.escape(value)}</span></span>'
        for label, value in stats
    )
    return f'<div class="stats-row">{badges}</div>'



def render_detail_pane(record: dict, selected: bool = False) -> str:
    key = _record_key(record)
    title = html.escape(record.get("title") or record.get("paper_id") or "Untitled paper")
    meta_html = html.escape(_meta_line(record))
    pills = ''.join(_pill_html(label) for label in _labels_for_record(record))
    links = ''.join(_detail_link_html(label, value) for label, value in (
        ("Raw overview", record.get("overview_path")),
        ("Raw abs", record.get("abs_path")),
        ("Landing", record.get("landing_page_url") or record.get("canonical_url")),
        ("PDF", record.get("pdf_url")),
    ) if _to_href(value))
    enrichment = _detail_enrichment_html(record)
    content_label, content_html = _detail_content(record)
    state_class = " is-active" if selected else ""

    return f"""
    <article class=\"detail-pane{state_class}\" data-paper-pane=\"{html.escape(key)}\">
      <header class=\"detail-head\">
        <p class=\"detail-kicker\">Welcome back</p>
        <h2 class=\"detail-title\">{title}</h2>
        <p class=\"detail-copy\">{meta_html}</p>
        <div class=\"pill-row\">{pills}</div>
        <div class=\"detail-links\">{links}</div>
        {enrichment}
      </header>
      <div class=\"detail-body\">
        <p class=\"content-label\">Rendered {html.escape(content_label)}</p>
        <article class=\"markdown\">{content_html}</article>
      </div>
    </article>
    """



def _detail_link_html(label: str, value: str | None) -> str:
    href = _to_href(value)
    if not href:
        return ""
    return f'<a href="{html.escape(href)}" target="_blank" rel="noreferrer">{html.escape(label)}</a>'



def _detail_enrichment_html(record: dict) -> str:
    rows: list[tuple[str, str]] = []
    organization = record.get("organization") or ""
    github_repo = record.get("github_repo") or ""
    github_stars = record.get("github_stars")
    upvotes = record.get("upvotes")
    comments = record.get("comments")
    ai_keywords = [str(item).strip() for item in (record.get("ai_keywords", []) or []) if str(item).strip()]
    ai_summary = (record.get("ai_summary") or "").strip()

    if organization:
        rows.append(("Organization", html.escape(str(organization))))
    if github_repo:
        github_href = github_repo if str(github_repo).startswith(("http://", "https://")) else f"https://github.com/{str(github_repo).lstrip('/')}"
        rows.append(("GitHub", f'<a href="{html.escape(github_href)}" target="_blank" rel="noreferrer">{html.escape(str(github_repo))}</a>'))
    if github_stars is not None:
        rows.append(("GitHub stars", html.escape(str(github_stars))))
    if upvotes is not None:
        rows.append(("HF upvotes", html.escape(str(upvotes))))
    if comments is not None:
        rows.append(("HF comments", html.escape(str(comments))))

    sections: list[str] = []
    if rows:
        rows_html = "".join(
            f'<div class="detail-meta-row"><span class="detail-meta-label">{html.escape(label)}</span><span class="detail-meta-value">{value}</span></div>'
            for label, value in rows
        )
        sections.append(f'<div class="detail-meta-card"><div class="detail-meta-grid">{rows_html}</div></div>')

    if ai_keywords:
        keyword_pills = ''.join(_pill_html(keyword) for keyword in ai_keywords)
        sections.append(
            '<div class="detail-meta-card detail-keywords">'
            '<span class="detail-meta-label">AI keywords</span>'
            f'<div class="pill-row">{keyword_pills}</div>'
            '</div>'
        )

    if ai_summary:
        toggle_html = ''
        summary_class = 'summary-card'
        if len(ai_summary) > 420:
            summary_class += ' is-collapsed'
            toggle_html = '<button class="summary-toggle" type="button" data-summary-toggle>Expand summary</button>'
        sections.append(
            f'<div class="{summary_class}" data-summary-card>'
            '<span class="detail-meta-label">AI summary</span>'
            f'<p>{html.escape(ai_summary)}</p>'
            f'{toggle_html}'
            '</div>'
        )

    if not sections:
        return ""
    return '<div class="detail-enrichment">' + ''.join(sections) + '</div>'



def _detail_content(record: dict) -> tuple[str, str]:
    for label, relative_path in (("overview", record.get("overview_path")), ("abs", record.get("abs_path"))):
        text = _read_repo_text(relative_path)
        if text:
            return label, _markdown_to_html(text)

    published = record.get("published") or ""
    if published:
        return "summary", f"<p>{html.escape(published)}</p>"
    return "summary", '<p class="empty-state">No overview markdown is available for this paper yet.</p>'



def _labels_for_record(record: dict) -> list[str]:
    labels = list(record.get("sources", []) or ([record.get("source")] if record.get("source") else []))
    labels.extend([item.strip() for item in (record.get("source_topics", []) or []) if item and item.strip()])
    graph_status = record.get("graph_status", {}) or {}
    if graph_status.get("references_fetched") == "fetched":
        labels.append("references")
    if graph_status.get("citations_fetched") == "fetched":
        labels.append("citations")

    seen: set[str] = set()
    deduped: list[str] = []
    for label in labels:
        if not label or label in seen:
            continue
        seen.add(label)
        deduped.append(label)
    return deduped



def _pill_html(label: str) -> str:
    return f'<span class="pill">{html.escape(label)}</span>'



def _meta_line(record: dict) -> str:
    authors = ", ".join(record.get("authors", [])[:4])
    if len(record.get("authors", [])) > 4:
        authors += ", …"
    parts = [
        part
        for part in [
            str(record.get("year") or ""),
            record.get("venue") or "",
            authors,
        ]
        if part
    ]
    return " · ".join(parts) or (record.get("paper_id") or "No metadata yet")



def _search_text(record: dict) -> str:
    parts: list[str] = [
        record.get("paper_id") or "",
        record.get("title") or "",
        record.get("venue") or "",
        " ".join(record.get("authors", []) or []),
        " ".join(_labels_for_record(record)),
        _stringify_record_value(record.get("ai_summary")),
        " ".join(str(item) for item in (record.get("ai_keywords", []) or []) if item),
        _stringify_record_value(record.get("github_repo")),
        _stringify_record_value(record.get("organization")),
    ]
    normalized = [" ".join(part.split()) for part in parts if part]
    return " ".join(normalized).lower()



def _stringify_record_value(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("fullname", "name", "title"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        return ""
    return str(value) if value not in (None, "") else ""



def _sort_title(record: dict) -> str:
    return " ".join((record.get("title") or record.get("paper_id") or "Untitled paper").split()).lower()



def _sort_year(record: dict) -> str:
    year = record.get("year")
    return str(year) if isinstance(year, int) else ""



def _record_key(record: dict) -> str:
    return record.get("paper_id") or record.get("title") or "paper"



def _to_href(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value

    relative = Path(value)
    preview_root = preview_html_path().parent.name
    try:
        relative = relative.relative_to(preview_root)
    except ValueError:
        pass
    return relative.as_posix()



def _read_repo_text(relative_path: str | None) -> str:
    if not relative_path:
        return ""
    path = resolve_stored_path(relative_path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")



def _markdown_to_html(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    parts: list[str] = []
    paragraph: list[str] = []
    list_type: str | None = None
    in_code_block = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            parts.append(f"<p>{_render_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            parts.append(f"</{list_type}>")
            list_type = None

    def flush_code_block() -> None:
        nonlocal in_code_block
        if in_code_block:
            escaped_code = html.escape("\n".join(code_lines))
            parts.append(f"<pre><code>{escaped_code}</code></pre>")
            code_lines.clear()
            in_code_block = False

    for raw_line in lines:
        stripped = raw_line.strip()

        if in_code_block:
            if stripped.startswith("```"):
                flush_code_block()
            else:
                code_lines.append(raw_line.rstrip("\n"))
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            close_list()
            in_code_block = True
            code_lines.clear()
            continue

        if not stripped:
            flush_paragraph()
            close_list()
            continue

        if re.fullmatch(r"-{3,}|\*{3,}", stripped):
            flush_paragraph()
            close_list()
            parts.append("<hr />")
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_paragraph()
            close_list()
            level = len(heading_match.group(1))
            parts.append(f"<h{level}>{_render_inline(heading_match.group(2).strip())}</h{level}>")
            continue

        bullet_match = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet_match:
            flush_paragraph()
            if list_type != "ul":
                close_list()
                list_type = "ul"
                parts.append("<ul>")
            parts.append(f"<li>{_render_inline(bullet_match.group(1).strip())}</li>")
            continue

        ordered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ordered_match:
            flush_paragraph()
            if list_type != "ol":
                close_list()
                list_type = "ol"
                parts.append("<ol>")
            parts.append(f"<li>{_render_inline(ordered_match.group(1).strip())}</li>")
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            close_list()
            parts.append(f"<blockquote><p>{_render_inline(stripped[1:].strip())}</p></blockquote>")
            continue

        paragraph.append(stripped)

    flush_paragraph()
    close_list()
    flush_code_block()
    return ''.join(parts)



def _render_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: f'<a href="{html.escape(match.group(2), quote=True)}" target="_blank" rel="noreferrer">{match.group(1)}</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped
