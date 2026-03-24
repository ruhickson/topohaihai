#!/usr/bin/env python3
"""Generate lightweight static blog from platform folders under the repo root (n64/, snes/, …)."""
from __future__ import annotations

import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "blog"
POSTS_DIR = OUT / "posts"
# Optional: copy analytics.fragment.example.html → analytics.fragment.html at repo root
ANALYTICS_FRAGMENT = ROOT / "analytics.fragment.html"


def analytics_fragment_html() -> str:
    """Raw HTML/scripts to inject before </body> on every page (traffic analytics)."""
    if not ANALYTICS_FRAGMENT.is_file():
        return ""
    raw = ANALYTICS_FRAGMENT.read_text(encoding="utf-8").strip()
    return f"\n{raw}\n" if raw else ""

DATE_START = date(2025, 9, 1)
DATE_END = date(2026, 3, 19)  # "today" per project context
# Always newest post (override hash)
LATEST_SLUG = "lylat-wars"

# Canonical platforms (slug → display label for filters / UI)
PLATFORM_ORDER: list[tuple[str, str]] = [
    ("switch", "Nintendo Switch"),
    ("switch2", "Switch 2"),
    ("snes", "SNES"),
    ("n64", "N64"),
    ("gc", "GameCube"),
    ("wii", "Wii"),
    ("wii-u", "Wii U"),
    ("pc", "PC"),
]

PLATFORM_ALIASES: dict[str, tuple[str, str]] = {}
for _slug, label in PLATFORM_ORDER:
    PLATFORM_ALIASES[_slug.replace("-", " ")] = (_slug, label)
    PLATFORM_ALIASES[label.lower()] = (_slug, label)
PLATFORM_ALIASES.update(
    {
        "nintendo switch": ("switch", "Nintendo Switch"),
        "switch": ("switch", "Nintendo Switch"),
        "switch 2": ("switch2", "Switch 2"),
        "switch2": ("switch2", "Switch 2"),
        "nintendo switch 2": ("switch2", "Switch 2"),
        "super nintendo": ("snes", "SNES"),
        "super nintendo entertainment system": ("snes", "SNES"),
        "nintendo 64": ("n64", "N64"),
        "n64": ("n64", "N64"),
        "gamecube": ("gc", "GameCube"),
        "game cube": ("gc", "GameCube"),
        "nintendo gamecube": ("gc", "GameCube"),
        "wii": ("wii", "Wii"),
        "wii u": ("wii-u", "Wii U"),
        "wii-u": ("wii-u", "Wii U"),
        "pc": ("pc", "PC"),
        "windows": ("pc", "PC"),
        "microsoft windows": ("pc", "PC"),
    }
)

# Folder name under ROOT → default (platform_slug, platform_label) when a post has no Platform: line
GAME_SOURCE_DIRS: list[tuple[str, tuple[str, str]]] = [
    ("n64", ("n64", "N64")),
    ("snes", ("snes", "SNES")),
    ("gamecube", ("gc", "GameCube")),
    ("pc", ("pc", "PC")),
    ("switch", ("switch", "Nintendo Switch")),
    ("switch2", ("switch2", "Switch 2")),
]

SCORE_ORDER: list[str] = ["3-up", "2-up", "1-up", "1-down", "2-down"]

SCORE_LABELS: dict[str, str] = {
    "3-up": "👍👍👍 Three thumbs up",
    "2-up": "👍👍 Two thumbs up",
    "1-up": "👍 One thumb up",
    "1-down": "👎 One thumb down",
    "2-down": "👎👎 Two thumbs down",
}

# Stacked bar chart colours (index page)
CHART_SCORE_COLORS: dict[str, str] = {
    "3-up": "#c9a227",
    "2-up": "#58d68d",
    "1-up": "#5dade2",
    "1-down": "#e67e22",
    "2-down": "#cb4335",
}

CHART_PLATFORM_COLORS: dict[str, str] = {
    "switch": "#e74c3c",
    "switch2": "#fd79a8",
    "snes": "#a569bd",
    "n64": "#3498db",
    "gc": "#1abc9c",
    "wii": "#2ecc71",
    "wii-u": "#16a085",
    "pc": "#bdc3c7",
}
# Keys should match PLATFORM_ORDER slugs; unknown slugs use #888888 in chart_payload_for_manifest.

# Filter sentinel + chart limits (must match JS in index_filter_script)
FILTER_NONE = "__none__"
TOP_CHART_DEV_PUB = 15


def parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Optional --- key: value --- block at top of .txt (no PyYAML dependency)."""
    text = raw.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, raw
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw
    meta: dict[str, str] = {}
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
        line = lines[i].strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    if end < 0:
        return {}, raw
    rest = "\n".join(lines[end + 1 :]).lstrip("\n")
    return meta, rest


def normalize_platform(value: str | None) -> tuple[str, str] | None:
    if not value:
        return None
    key = re.sub(r"\s+", " ", value.strip().lower())
    return PLATFORM_ALIASES.get(key)


def infer_platform_from_body(body: str) -> tuple[str, str] | None:
    m = re.search(r"^Platform:\s*(.+)$", body, re.MULTILINE | re.IGNORECASE)
    if m:
        return normalize_platform(m.group(1).strip())
    return None


def infer_release_year(body: str) -> int | None:
    """Earliest plausible calendar year in the Release dates section, else anywhere in file."""
    sec_match = re.search(
        r"Release dates[^\n]*\n[-=]+\s*\n(.*?)(?=\n[^\n]+\n[-=]+\s*\n)",
        body,
        re.DOTALL | re.IGNORECASE,
    )
    chunk = sec_match.group(1) if sec_match else body
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", chunk)]
    years = [y for y in years if 1980 <= y <= 2035]
    return min(years) if years else None


def extract_developer_publisher(body: str) -> tuple[str, str]:
    """First `Developer:` / `Publisher:` line in the raw post body (under Description, etc.)."""
    dev = ""
    pub = ""
    dm = re.search(r"^Developer:\s*(.+)$", body, re.MULTILINE | re.IGNORECASE)
    if dm:
        dev = dm.group(1).strip().split("\n")[0].strip()
    pm = re.search(r"^Publisher:\s*(.+)$", body, re.MULTILINE | re.IGNORECASE)
    if pm:
        pub = pm.group(1).strip().split("\n")[0].strip()
    return dev, pub


def infer_score_slug(body: str) -> str | None:
    m = re.search(r"\*\*Verdict:\*\*\s*([^\n]+)", body)
    if not m:
        return None
    line = m.group(1)
    ups = line.count("👍")
    downs = line.count("👎")
    if downs == 0:
        if ups >= 3:
            return "3-up"
        if ups == 2:
            return "2-up"
        if ups == 1:
            return "1-up"
        return None
    if downs >= 2:
        return "2-down"
    if downs == 1:
        return "1-down"
    return None


def resolve_metadata(
    fm: dict[str, str],
    raw_body: str,
    default_platform: tuple[str, str] | None = None,
) -> dict[str, object]:
    """Merge YAML-style frontmatter with inference from the post body.

    Resolution order for platform: frontmatter ``platform`` → ``Platform:`` line in body
    → *default_platform* (folder default from ``GAME_SOURCE_DIRS`` in ``main``)
    → fallback ``N64`` only if nothing else applies (e.g. callers omit *default_platform*).
    """
    platform_slug = fm.get("platform")
    ps: str | None = None
    pl: str | None = None
    if platform_slug:
        n = normalize_platform(platform_slug)
        if n:
            ps, pl = n
    if not ps:
        inf = infer_platform_from_body(raw_body)
        if inf:
            ps, pl = inf
    if not ps:
        if default_platform:
            ps, pl = default_platform
        else:
            ps, pl = "n64", "N64"

    year_val: int | None = None
    if "release_year" in fm and fm["release_year"].strip():
        try:
            year_val = int(fm["release_year"].strip())
        except ValueError:
            year_val = None
    if year_val is None:
        year_val = infer_release_year(raw_body)

    score_slug: str | None = None
    if fm.get("score"):
        cand = fm["score"].strip().lower().replace(" ", "-")
        if cand in SCORE_LABELS:
            score_slug = cand
    if score_slug is None:
        score_slug = infer_score_slug(raw_body)
    if score_slug is None:
        score_slug = "1-up"
    score_label = SCORE_LABELS.get(score_slug, score_slug)

    return {
        "platform": ps,
        "platform_label": pl,
        "release_year": year_val,
        "score": score_slug,
        "score_label": score_label,
    }


def build_browse_sections(rows: list[dict]) -> str:
    """HTML: Contents with Platform / Year / Score groupings (details/summary)."""
    by_platform: dict[str, list[dict]] = {}
    by_year: dict[int, list[dict]] = {}
    by_score: dict[str, list[dict]] = {}

    for r in rows:
        ps = r["platform"]
        by_platform.setdefault(ps, []).append(r)
        y = r.get("release_year")
        if isinstance(y, int):
            by_year.setdefault(y, []).append(r)
        sc = r["score"]
        by_score.setdefault(sc, []).append(r)

    def sort_posts(lst: list[dict]) -> list[dict]:
        return sorted(lst, key=lambda x: (x.get("date", ""), x.get("title", "")), reverse=True)

    platform_sections: list[str] = []
    for slug, label in PLATFORM_ORDER:
        if slug not in by_platform:
            continue
        items = sort_posts(by_platform[slug])
        lis = []
        for m in items:
            href = f"posts/{m['slug']}.html"
            lis.append(
                f'        <li><a href="{html.escape(href)}">{html.escape(m["title"])}</a></li>'
            )
        platform_sections.append(
            f"""      <details class="browse__details">
        <summary class="browse__summary">{html.escape(label)} <span class="browse__count">({len(items)})</span></summary>
        <ul class="browse__list">
{chr(10).join(lis)}
        </ul>
      </details>"""
        )

    year_sections: list[str] = []
    for y in sorted(by_year.keys()):
        items = sort_posts(by_year[y])
        lis = []
        for m in items:
            href = f"posts/{m['slug']}.html"
            lis.append(
                f'        <li><a href="{html.escape(href)}">{html.escape(m["title"])}</a></li>'
            )
        year_sections.append(
            f"""      <details class="browse__details">
        <summary class="browse__summary">{y} <span class="browse__count">({len(items)})</span></summary>
        <ul class="browse__list">
{chr(10).join(lis)}
        </ul>
      </details>"""
        )

    score_sections: list[str] = []
    for sc in SCORE_ORDER:
        if sc not in by_score:
            continue
        items = sort_posts(by_score[sc])
        label = SCORE_LABELS.get(sc, sc)
        lis = []
        for m in items:
            href = f"posts/{m['slug']}.html"
            lis.append(
                f'        <li><a href="{html.escape(href)}">{html.escape(m["title"])}</a></li>'
            )
        score_sections.append(
            f"""      <details class="browse__details">
        <summary class="browse__summary">{html.escape(label)} <span class="browse__count">({len(items)})</span></summary>
        <ul class="browse__list">
{chr(10).join(lis)}
        </ul>
      </details>"""
        )

    empty_col = '      <p class="browse__empty">—</p>'
    plat_block = chr(10).join(platform_sections) if platform_sections else empty_col
    year_block = chr(10).join(year_sections) if year_sections else empty_col
    score_block = chr(10).join(score_sections) if score_sections else empty_col

    return f"""    <aside class="browse browse--sidebar" aria-labelledby="browse-heading">
      <h2 id="browse-heading" class="browse__title">Contents</h2>
      <p class="browse__intro">Jump by platform, release year, or verdict. Lists use the same order as the main column (newest on the site first).</p>
      <div class="browse__grid">
        <div class="browse__col">
          <h3 class="browse__col-title">Platform</h3>
{plat_block}
        </div>
        <div class="browse__col">
          <h3 class="browse__col-title">Release year</h3>
{year_block}
        </div>
        <div class="browse__col">
          <h3 class="browse__col-title">Score</h3>
{score_block}
        </div>
      </div>
    </aside>"""


def index_filter_script() -> str:
    """Client-side filters for the main post list (index page only)."""
    fn_js = json.dumps(FILTER_NONE)
    return f"""
  <script>
  (function () {{
    var FILTER_NONE = {fn_js};
    function applyPostFilters() {{
      var list = document.querySelector(".index__list");
      if (!list) return;
      var items = list.querySelectorAll(".index__item");
      var p = (document.getElementById("filter-platform") || {{}}).value || "";
      var y = (document.getElementById("filter-year") || {{}}).value || "";
      var s = (document.getElementById("filter-score") || {{}}).value || "";
      var mo = (document.getElementById("filter-month") || {{}}).value || "";
      var dev = (document.getElementById("filter-developer") || {{}}).value || "";
      var pub = (document.getElementById("filter-publisher") || {{}}).value || "";
      items.forEach(function (li) {{
        var ok = true;
        if (p && li.getAttribute("data-platform") !== p) ok = false;
        if (y && String(li.getAttribute("data-year") || "") !== y) ok = false;
        if (s && li.getAttribute("data-score") !== s) ok = false;
        if (mo && (li.getAttribute("data-site-month") || "") !== mo) ok = false;
        if (dev) {{
          var dattr = (li.getAttribute("data-developer") || "").trim();
          if (dev === FILTER_NONE) {{
            if (dattr !== "") ok = false;
          }} else if (dattr !== dev) ok = false;
        }}
        if (pub) {{
          var pattr = (li.getAttribute("data-publisher") || "").trim();
          if (pub === FILTER_NONE) {{
            if (pattr !== "") ok = false;
          }} else if (pattr !== pub) ok = false;
        }}
        li.hidden = !ok;
      }});
    }}
    window.topohaihaiApplyFilters = applyPostFilters;
    var ids = ["filter-platform", "filter-year", "filter-score", "filter-month", "filter-developer", "filter-publisher"];
    ids.forEach(function (id) {{
      var el = document.getElementById(id);
      if (el) el.addEventListener("change", applyPostFilters);
    }});
    var clr = document.querySelector("[data-browse-clear]");
    if (clr) clr.addEventListener("click", function () {{
      ids.forEach(function (id) {{
        var el = document.getElementById(id);
        if (el) el.value = "";
      }});
      applyPostFilters();
    }});
  }})();
  </script>"""


def _platform_sort_key(slug: str) -> int:
    for i, (s, _) in enumerate(PLATFORM_ORDER):
        if s == slug:
            return i
    return 999


def build_filter_bar(manifest: list[dict]) -> str:
    """Dropdown filters above the main chronological list (two rows)."""
    plats = sorted({m["platform"] for m in manifest}, key=_platform_sort_key)
    years = sorted(
        {m["release_year"] for m in manifest if isinstance(m.get("release_year"), int)}
    )
    months = sorted({m["date"][:7] for m in manifest})
    scores_present = [s for s in SCORE_ORDER if any(m["score"] == s for m in manifest)]

    devs = sorted({(m.get("developer") or "").strip() for m in manifest if (m.get("developer") or "").strip()})
    pubs = sorted({(m.get("publisher") or "").strip() for m in manifest if (m.get("publisher") or "").strip()})
    has_unlisted_dev = any(not (m.get("developer") or "").strip() for m in manifest)
    has_unlisted_pub = any(not (m.get("publisher") or "").strip() for m in manifest)

    plat_opts = ['<option value="">All platforms</option>']
    for s, lab in PLATFORM_ORDER:
        if s in plats:
            plat_opts.append(f'<option value="{html.escape(s)}">{html.escape(lab)}</option>')
    year_opts = ['<option value="">All years</option>'] + [
        f'<option value="{y}">{y}</option>' for y in years
    ]
    month_opts = ['<option value="">All months</option>'] + [
        f'<option value="{html.escape(mo)}">{html.escape(mo)}</option>' for mo in months
    ]
    score_opts = ['<option value="">All scores</option>'] + [
        f'<option value="{html.escape(s)}">{html.escape(SCORE_LABELS[s])}</option>'
        for s in scores_present
    ]

    dev_opts = ['<option value="">All developers</option>']
    if has_unlisted_dev:
        dev_opts.append(
            f'<option value="{html.escape(FILTER_NONE)}">Not listed</option>'
        )
    for d in devs:
        dev_opts.append(f'<option value="{html.escape(d, quote=True)}">{html.escape(d)}</option>')

    pub_opts = ['<option value="">All publishers</option>']
    if has_unlisted_pub:
        pub_opts.append(
            f'<option value="{html.escape(FILTER_NONE)}">Not listed</option>'
        )
    for p in pubs:
        pub_opts.append(f'<option value="{html.escape(p, quote=True)}">{html.escape(p)}</option>')

    return f"""    <div class="browse-filters" role="region" aria-label="Filter posts">
      <div class="browse-filters__row">
        <label class="browse-filters__field">
          <span class="browse-filters__label">Platform</span>
          <select class="browse-filters__select" id="filter-platform">
{chr(10).join("            " + o for o in plat_opts)}
          </select>
        </label>
        <label class="browse-filters__field">
          <span class="browse-filters__label">Release year</span>
          <select class="browse-filters__select" id="filter-year">
{chr(10).join("            " + o for o in year_opts)}
          </select>
        </label>
        <label class="browse-filters__field">
          <span class="browse-filters__label">Score</span>
          <select class="browse-filters__select" id="filter-score">
{chr(10).join("            " + o for o in score_opts)}
          </select>
        </label>
      </div>
      <div class="browse-filters__row">
        <label class="browse-filters__field">
          <span class="browse-filters__label">Site month</span>
          <select class="browse-filters__select" id="filter-month">
{chr(10).join("            " + o for o in month_opts)}
          </select>
        </label>
        <label class="browse-filters__field">
          <span class="browse-filters__label">Developer</span>
          <select class="browse-filters__select" id="filter-developer">
{chr(10).join("            " + o for o in dev_opts)}
          </select>
        </label>
        <label class="browse-filters__field">
          <span class="browse-filters__label">Publisher</span>
          <select class="browse-filters__select" id="filter-publisher">
{chr(10).join("            " + o for o in pub_opts)}
          </select>
        </label>
        <button type="button" class="browse-filters__clear" data-browse-clear>Clear filters</button>
      </div>
    </div>"""


def chart_payload_for_manifest(manifest: list[dict]) -> dict:
    """Build JSON-serializable chart data for the index overview + click-to-filter."""
    month_score: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    month_plat: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    year_plat: defaultdict[int, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    months_set: set[str] = set()
    for m in manifest:
        ym = m["date"][:7]
        months_set.add(ym)
        month_score[ym][m["score"]] += 1
        month_plat[ym][m["platform"]] += 1
        ry = m.get("release_year")
        if isinstance(ry, int):
            year_plat[ry][m["platform"]] += 1
    months_sorted = sorted(months_set)
    years_sorted = sorted(year_plat.keys())

    score_datasets: list[dict] = []
    for sc in SCORE_ORDER:
        counts = [month_score[mo].get(sc, 0) for mo in months_sorted]
        if any(counts):
            score_datasets.append(
                {
                    "key": sc,
                    "label": SCORE_LABELS[sc],
                    "backgroundColor": CHART_SCORE_COLORS[sc],
                    "data": counts,
                }
            )

    plats_in_use = sorted({m["platform"] for m in manifest}, key=_platform_sort_key)
    plat_month_datasets: list[dict] = []
    for pslug in plats_in_use:
        counts = [month_plat[mo].get(pslug, 0) for mo in months_sorted]
        if any(counts):
            lab = next((lbl for s, lbl in PLATFORM_ORDER if s == pslug), pslug)
            plat_month_datasets.append(
                {
                    "key": pslug,
                    "label": lab,
                    "backgroundColor": CHART_PLATFORM_COLORS.get(pslug, "#888888"),
                    "data": counts,
                }
            )

    plat_year_datasets: list[dict] = []
    for pslug in plats_in_use:
        counts = [year_plat[y][pslug] for y in years_sorted]
        if any(counts):
            lab = next((lbl for s, lbl in PLATFORM_ORDER if s == pslug), pslug)
            plat_year_datasets.append(
                {
                    "key": pslug,
                    "label": lab,
                    "backgroundColor": CHART_PLATFORM_COLORS.get(pslug, "#888888"),
                    "data": counts,
                }
            )

    score_totals = Counter(m["score"] for m in manifest)
    st_labels: list[str] = []
    st_keys: list[str] = []
    st_data: list[int] = []
    st_colors: list[str] = []
    for sc in SCORE_ORDER:
        c = score_totals.get(sc, 0)
        if c:
            st_labels.append(SCORE_LABELS[sc])
            st_keys.append(sc)
            st_data.append(c)
            st_colors.append(CHART_SCORE_COLORS[sc])

    not_listed = "(not listed)"

    def top_list(field: str) -> dict:
        ctr: Counter[str] = Counter()
        for m in manifest:
            raw = (m.get(field) or "").strip()
            ctr[raw if raw else not_listed] += 1
        out_display: list[str] = []
        out_filter: list[str] = []
        out_counts: list[int] = []
        out_colors: list[str] = []
        for name, cnt in ctr.most_common(TOP_CHART_DEV_PUB):
            disp = name if len(name) <= 44 else name[:41] + "…"
            fv = FILTER_NONE if name == not_listed else name
            hue = (40 + len(out_display) * 17) % 360
            col = f"hsl({hue}, 52%, 52%)"
            out_display.append(disp)
            out_filter.append(fv)
            out_counts.append(cnt)
            out_colors.append(col)
        return {
            "displayLabels": out_display,
            "filterValues": out_filter,
            "counts": out_counts,
            "backgroundColors": out_colors,
        }

    return {
        "filterNone": FILTER_NONE,
        "months": months_sorted,
        "years": years_sorted,
        "score": score_datasets,
        "platformByMonth": plat_month_datasets,
        "platformByReleaseYear": plat_year_datasets,
        "scoreTotals": {
            "labels": st_labels,
            "keys": st_keys,
            "data": st_data,
            "colors": st_colors,
        },
        "topDevelopers": top_list("developer"),
        "topPublishers": top_list("publisher"),
    }


CHART_INIT_JS = """
(function() {
  var payloadEl = document.getElementById("chart-payload");
  if (!payloadEl || typeof Chart === "undefined") return;
  var payload = JSON.parse(payloadEl.textContent);
  Chart.defaults.color = "#9a95a8";
  Chart.defaults.borderColor = "rgba(201, 162, 39, 0.12)";

  function applyFromCharts() {
    if (typeof window.topohaihaiApplyFilters === "function") window.topohaihaiApplyFilters();
  }
  function setV(id, v) {
    var el = document.getElementById(id);
    if (el) el.value = v != null ? String(v) : "";
  }

  function barOptionsStacked() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: true },
      onHover: function(evt, els) {
        if (evt.native && evt.native.target) evt.native.target.style.cursor = els.length ? "pointer" : "default";
      },
      plugins: {
        legend: {
          position: "bottom",
          labels: { boxWidth: 11, padding: 8, font: { size: 10 }, usePointStyle: true }
        },
        tooltip: { mode: "index", intersect: false }
      },
      scales: {
        x: {
          stacked: true,
          grid: { color: "rgba(201, 162, 39, 0.08)" },
          ticks: { maxRotation: 40, font: { size: 10 } }
        },
        y: {
          stacked: true,
          beginAtZero: true,
          ticks: { precision: 0, font: { size: 10 } },
          grid: { color: "rgba(201, 162, 39, 0.08)" }
        }
      }
    };
  }

  function barOptionsSimpleVertical() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: true },
      onHover: function(evt, els) {
        if (evt.native && evt.native.target) evt.native.target.style.cursor = els.length ? "pointer" : "default";
      },
      plugins: { legend: { display: false }, tooltip: {} },
      scales: {
        x: {
          grid: { color: "rgba(201, 162, 39, 0.08)" },
          ticks: { font: { size: 10 } }
        },
        y: {
          beginAtZero: true,
          ticks: { precision: 0, font: { size: 10 } },
          grid: { color: "rgba(201, 162, 39, 0.08)" }
        }
      }
    };
  }

  function mapDs(arr) {
    return (arr || []).map(function(ds) {
      return {
        label: ds.label,
        data: ds.data,
        backgroundColor: ds.backgroundColor,
        borderWidth: 0,
        borderRadius: 2,
        key: ds.key
      };
    });
  }

  if (payload.months && payload.months.length) {
    if (payload.score && payload.score.length) {
      var ca = document.getElementById("chart-score-month");
      if (ca) {
        var chA = new Chart(ca, {
          type: "bar",
          data: { labels: payload.months, datasets: mapDs(payload.score) },
          options: barOptionsStacked()
        });
        chA.options.onClick = function(evt, els) {
          if (!els.length) return;
          var e = els[0];
          setV("filter-month", payload.months[e.index]);
          setV("filter-score", payload.score[e.datasetIndex].key);
          applyFromCharts();
        };
      }
    }
    if (payload.platformByMonth && payload.platformByMonth.length) {
      var cb = document.getElementById("chart-platform-month");
      if (cb) {
        var chB = new Chart(cb, {
          type: "bar",
          data: { labels: payload.months, datasets: mapDs(payload.platformByMonth) },
          options: barOptionsStacked()
        });
        chB.options.onClick = function(evt, els) {
          if (!els.length) return;
          var e = els[0];
          setV("filter-month", payload.months[e.index]);
          setV("filter-platform", payload.platformByMonth[e.datasetIndex].key);
          applyFromCharts();
        };
      }
    }
  }
  if (payload.years && payload.years.length && payload.platformByReleaseYear && payload.platformByReleaseYear.length) {
    var cc = document.getElementById("chart-release-year");
    if (cc) {
      var chC = new Chart(cc, {
        type: "bar",
        data: {
          labels: payload.years.map(String),
          datasets: mapDs(payload.platformByReleaseYear)
        },
        options: barOptionsStacked()
      });
      chC.options.onClick = function(evt, els) {
        if (!els.length) return;
        var e = els[0];
        setV("filter-year", String(payload.years[e.index]));
        setV("filter-platform", payload.platformByReleaseYear[e.datasetIndex].key);
        applyFromCharts();
      };
    }
  }

  var st = payload.scoreTotals;
  if (st && st.data && st.data.length) {
    var cd = document.getElementById("chart-score-totals");
    if (cd) {
      var chD = new Chart(cd, {
        type: "bar",
        data: {
          labels: st.labels,
          datasets: [{
            label: "Posts",
            data: st.data,
            backgroundColor: st.colors,
            borderWidth: 0,
            borderRadius: 3
          }]
        },
        options: barOptionsSimpleVertical()
      });
      chD.options.onClick = function(evt, els) {
        if (!els.length) return;
        setV("filter-score", st.keys[els[0].index]);
        applyFromCharts();
      };
    }
  }

  var td = payload.topDevelopers;
  if (td && td.counts && td.counts.length) {
    var ce = document.getElementById("chart-top-developers");
    if (ce) {
      var oE = barOptionsSimpleVertical();
      oE.indexAxis = "y";
      oE.plugins.legend.display = false;
      var chE = new Chart(ce, {
        type: "bar",
        data: {
          labels: td.displayLabels,
          datasets: [{
            label: "Posts",
            data: td.counts,
            backgroundColor: td.backgroundColors,
            borderWidth: 0
          }]
        },
        options: oE
      });
      chE.options.onClick = function(evt, els) {
        if (!els.length) return;
        setV("filter-developer", td.filterValues[els[0].index]);
        applyFromCharts();
      };
    }
  }

  var tp = payload.topPublishers;
  if (tp && tp.counts && tp.counts.length) {
    var cf = document.getElementById("chart-top-publishers");
    if (cf) {
      var oF = barOptionsSimpleVertical();
      oF.indexAxis = "y";
      oF.plugins.legend.display = false;
      var chF = new Chart(cf, {
        type: "bar",
        data: {
          labels: tp.displayLabels,
          datasets: [{
            label: "Posts",
            data: tp.counts,
            backgroundColor: tp.backgroundColors,
            borderWidth: 0
          }]
        },
        options: oF
      });
      chF.options.onClick = function(evt, els) {
        if (!els.length) return;
        setV("filter-publisher", tp.filterValues[els[0].index]);
        applyFromCharts();
      };
    }
  }
})();
"""


def build_index_charts_section(manifest: list[dict]) -> str:
    payload = chart_payload_for_manifest(manifest)
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""    <section class="index__charts" aria-label="Post statistics">
      <h2 class="index__charts-heading">Overview</h2>
      <p class="index__charts-lead">Stacked bars by site month / release year; second row totals scores and top developers &amp; publishers. <strong>Click</strong> a bar or segment to apply the matching filters below.</p>
      <div class="index__charts-grid">
        <div class="chart-card">
          <h3 class="chart-card__title">Posts on this site by month</h3>
          <p class="chart-card__hint">Stacked by score — click sets month + score</p>
          <div class="chart-card__canvas chart-card__canvas--clickable"><canvas id="chart-score-month" aria-label="Posts per month by score"></canvas></div>
        </div>
        <div class="chart-card">
          <h3 class="chart-card__title">Posts on this site by month</h3>
          <p class="chart-card__hint">Stacked by platform — click sets month + platform</p>
          <div class="chart-card__canvas chart-card__canvas--clickable"><canvas id="chart-platform-month" aria-label="Posts per month by platform"></canvas></div>
        </div>
        <div class="chart-card">
          <h3 class="chart-card__title">Games by original release year</h3>
          <p class="chart-card__hint">Stacked by platform — click sets release year + platform</p>
          <div class="chart-card__canvas chart-card__canvas--clickable"><canvas id="chart-release-year" aria-label="Games by release year"></canvas></div>
        </div>
      </div>
      <h3 class="index__charts-subheading">Totals &amp; credits</h3>
      <div class="index__charts-grid">
        <div class="chart-card">
          <h3 class="chart-card__title">All posts by score</h3>
          <p class="chart-card__hint">Click a bar to filter by verdict</p>
          <div class="chart-card__canvas chart-card__canvas--clickable"><canvas id="chart-score-totals" aria-label="Total posts by score"></canvas></div>
        </div>
        <div class="chart-card">
          <h3 class="chart-card__title">Top developers</h3>
          <p class="chart-card__hint">From Developer: lines — click a row to filter</p>
          <div class="chart-card__canvas chart-card__canvas--clickable"><canvas id="chart-top-developers" aria-label="Top developers"></canvas></div>
        </div>
        <div class="chart-card">
          <h3 class="chart-card__title">Top publishers</h3>
          <p class="chart-card__hint">From Publisher: lines — click a row to filter</p>
          <div class="chart-card__canvas chart-card__canvas--clickable"><canvas id="chart-top-publishers" aria-label="Top publishers"></canvas></div>
        </div>
      </div>
      <script type="application/json" id="chart-payload">{payload_json}</script>
    </section>"""


def build_index_chart_scripts_tail() -> str:
    """Load Chart.js and run init after topohaihaiApplyFilters exists (end of body)."""
    return f"""  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script>
{CHART_INIT_JS}
  </script>"""


def date_for_slug(slug: str) -> date:
    if slug == LATEST_SLUG:
        return DATE_END
    h = int(hashlib.md5(slug.encode("utf-8")).hexdigest(), 16)
    span = (DATE_END - DATE_START).days + 1
    d = DATE_START + timedelta(days=h % span)
    # Avoid colliding with forced latest date
    if d == DATE_END:
        d = DATE_END - timedelta(days=1)
    return d


def parse_sections(raw: str) -> tuple[str, list[tuple[str, str]]]:
    lines = raw.strip("\n").splitlines()
    if not lines:
        return "Untitled", []
    title = lines[0].strip()
    i = 1
    while i < len(lines) and lines[i].strip() and set(lines[i].strip()) <= {"="}:
        i += 1
    rest = "\n".join(lines[i:]).lstrip("\n")
    sections: list[tuple[str, str]] = []
    matches = list(re.finditer(r"^([^\n]+)\n[-=]+\s*\n", rest, re.MULTILINE))
    if not matches:
        if rest.strip():
            sections.append(("", rest.strip()))
        return title, sections
    for j, m in enumerate(matches):
        sec_title = m.group(1).strip()
        body_start = m.end()
        body_end = matches[j + 1].start() if j + 1 < len(matches) else len(rest)
        body = rest[body_start:body_end].strip()
        sections.append((sec_title, body))
    return title, sections


def text_to_html_paragraphs(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    chunks = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out = []
    for p in chunks:
        p_esc = html.escape(p)
        p_esc = p_esc.replace("\n", "<br>\n")
        p_esc = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", p_esc)
        p_esc = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", p_esc)
        out.append(f"<p>{p_esc}</p>")
    return "\n".join(out)


def section_to_html(title: str, body: str) -> str:
    inner = text_to_html_paragraphs(body)
    if not title:
        return f'<div class="section section--body">{inner}</div>'
    t = html.escape(title)
    return f'<section class="section"><h2 class="section__title">{t}</h2>\n<div class="section__body">{inner}</div></section>'


def nav_tabs(active: str, nav_prefix: str) -> str:
    """active: 'posts' | 'about'. nav_prefix: '' for blog root, '..' for posts/."""
    base = "../" if nav_prefix == ".." else ""
    posts_cls = " site-tab--active" if active == "posts" else ""
    about_cls = " site-tab--active" if active == "about" else ""
    return f"""<nav class="site-tabs" aria-label="Main">
    <a href="{base}index.html" class="site-tab{posts_cls}">Posts</a>
    <a href="{base}about.html" class="site-tab{about_cls}">About</a>
  </nav>"""


def site_header(active: str, nav_prefix: str) -> str:
    base = "../" if nav_prefix == ".." else ""
    return f"""  <header class="site-header">
    <div class="site-header__brand">
      <a class="site-title" href="{base}index.html">topohaihai</a>
      {nav_tabs(active, nav_prefix)}
    </div>
  </header>"""


def build_about_page() -> str:
    """Single About page at blog/about.html."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>About · topohaihai</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
{site_header("about", "")}
  <main class="about">
    <h1 class="about__title">About</h1>
    <p class="about__lead">
      <strong>topohaihai</strong> is a small, static blog of game notes across platforms: facts, release trivia, and long-form
      “Thoughts” pieces written in a casual, stream-of-consciousness voice—like someone rambling after too many cups of
      coffee and a weekend with a controller.
    </p>
    <h2 class="about__h2">Scoring</h2>
    <p>
      Each post ends with a <strong>Verdict</strong> line with emoji thumbs. There are five levels:
      <strong>three thumbs up</strong> (all-time highlight),
      <strong>two thumbs up</strong> (love it),
      <strong>one thumb up</strong> (solid / uneven but positive),
      <strong>one thumb down</strong> (rough or niche),
      and <strong>two thumbs down</strong> (avoid unless you enjoy pain or archaeology).
      It’s not a scientific rubric—just a quick read on how much I’d recommend the game today.
    </p>
    <h2 class="about__h2">Elsewhere</h2>
    <p class="about__socials">
      <a href="https://www.twitch.tv/topohaihai" rel="noopener noreferrer">Twitch — @topohaihai</a><br>
      <a href="https://www.youtube.com/@topohaihai" rel="noopener noreferrer">YouTube — @topohaihai</a><br>
      <a href="https://bsky.app/profile/topohaihai.bsky.social" rel="noopener noreferrer">Bluesky — @topohaihai</a>
    </p>
  </main>
  <footer class="site-footer"><p>Lightweight static blog</p></footer>{analytics_fragment_html()}</body>
</html>
"""


def build_page(title: str, pub: date, slug: str, sections: list[tuple[str, str]], rel_root: str = "..") -> str:
    body_html = "\n".join(section_to_html(t, b) for t, b in sections)
    pub_s = pub.isoformat()
    title_esc = html.escape(title)
    slug_esc = html.escape(slug)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title_esc} · topohaihai</title>
  <link rel="stylesheet" href="{rel_root}/styles.css">
</head>
<body>
{site_header("posts", "..")}
  <main class="post">
    <article id="post-{slug_esc}">
      <p class="post__date"><time datetime="{pub_s}">{pub_s}</time></p>
      <h1 class="post__title">{title_esc}</h1>
      {body_html}
    </article>
  </main>
  <footer class="site-footer"><p>Lightweight static blog</p></footer>{analytics_fragment_html()}</body>
</html>
"""


def main() -> None:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    txt_jobs: list[tuple[Path, tuple[str, str]]] = []
    for subdir, plat in GAME_SOURCE_DIRS:
        d = ROOT / subdir
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.txt")):
            if p.name.lower() == "readme.txt":
                continue
            txt_jobs.append((p, plat))

    if not txt_jobs:
        raise SystemExit(
            "No .txt posts found under game folders (n64/, snes/, gamecube/, pc/, switch/, switch2/)."
        )

    manifest: list[dict] = []

    for path, default_platform in txt_jobs:
        slug = path.stem
        raw = path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(raw)
        title, sections = parse_sections(body)
        pub = date_for_slug(slug)
        meta = resolve_metadata(fm, body, default_platform=default_platform)
        developer, publisher = extract_developer_publisher(body)
        rel_file = path.relative_to(ROOT).as_posix()
        row = {
            "slug": slug,
            "title": title,
            "date": pub.isoformat(),
            "file": rel_file,
            "developer": developer,
            "publisher": publisher,
            **meta,
        }
        manifest.append(row)
        page = build_page(title, pub, slug, sections, rel_root="..")
        (POSTS_DIR / f"{slug}.html").write_text(page, encoding="utf-8")

    manifest.sort(key=lambda x: x["date"], reverse=True)
    (OUT / "posts.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # index.html
    items: list[str] = []
    for m in manifest:
        href = f"posts/{m['slug']}.html"
        t = html.escape(m["title"])
        d = m["date"]
        ps = html.escape(m["platform"])
        sc = html.escape(m["score"])
        pl_label = html.escape(m["platform_label"])
        score_label = html.escape(m["score_label"])
        y = m.get("release_year")
        y_str = str(y) if isinstance(y, int) else "—"
        y_attr = str(y) if isinstance(y, int) else ""
        sid = html.escape(m["slug"])
        site_month = html.escape(m["date"][:7], quote=True)
        dv = (m.get("developer") or "").strip()
        pb = (m.get("publisher") or "").strip()
        dev_attr = html.escape(dv, quote=True)
        pub_attr = html.escape(pb, quote=True)
        items.append(
            f'  <li class="index__item" id="post-{sid}" data-platform="{ps}" '
            f'data-year="{html.escape(y_attr)}" data-score="{sc}" '
            f'data-site-month="{site_month}" data-developer="{dev_attr}" data-publisher="{pub_attr}">\n'
            f'    <time class="index__date" datetime="{d}">{d}</time>\n'
            f'    <div class="index__item-body">\n'
            f'      <a class="index__link" href="{href}">{t}</a>\n'
            f'      <p class="index__tags">{pl_label} · {y_str} · {score_label}</p>\n'
            f"    </div>\n"
            f"  </li>"
        )

    browse_html = build_browse_sections(manifest)
    filters_html = build_filter_bar(manifest)
    charts_html = build_index_charts_section(manifest)

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>topohaihai — posts</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
{site_header("posts", "")}
  <main class="index">
    <h1 class="index__heading">Posts</h1>
    <p class="index__meta">Game notes and opinions — filter the list or jump from <strong>Contents</strong> (sidebar on wider screens). Dates on the left are when each post appears on this site ({DATE_START.isoformat()} … {DATE_END.isoformat()}).</p>
{charts_html}
    <div class="index__layout">
      <div class="index__primary">
{filters_html}
        <h2 class="index__list-heading">All posts</h2>
        <ul class="index__list">
{chr(10).join(items)}
        </ul>
      </div>
{browse_html}
    </div>
  </main>
  <footer class="site-footer"><p>Lightweight static blog</p></footer>{index_filter_script()}{build_index_chart_scripts_tail()}{analytics_fragment_html()}</body>
</html>
"""
    (OUT / "index.html").write_text(index_html, encoding="utf-8")
    (OUT / "about.html").write_text(build_about_page(), encoding="utf-8")
    print(f"Wrote {len(manifest)} posts + about.html to {OUT}")


if __name__ == "__main__":
    main()
