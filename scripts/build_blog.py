#!/usr/bin/env python3
"""Generate lightweight static blog from n64/*.txt files."""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
N64 = ROOT / "n64"
OUT = ROOT / "blog"
POSTS_DIR = OUT / "posts"

DATE_START = date(2025, 9, 1)
DATE_END = date(2026, 3, 19)  # "today" per project context
# Always newest post (override hash)
LATEST_SLUG = "lylat-wars"


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
      <strong>topohaihai</strong> is a small, static blog of Nintendo 64 game notes: facts, release trivia, and long-form
      “Thoughts” pieces written in a casual, stream-of-consciousness voice—like someone rambling after too many cups of
      coffee and a weekend with a controller.
    </p>
    <h2 class="about__h2">Scoring</h2>
    <p>
      Each post ends with a simple verdict line plus emoji “thumb” rating. There are four levels:
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
  <footer class="site-footer"><p>Lightweight static blog</p></footer>
</body>
</html>
"""


def build_page(title: str, pub: date, slug: str, sections: list[tuple[str, str]], rel_root: str = "..") -> str:
    body_html = "\n".join(section_to_html(t, b) for t, b in sections)
    pub_s = pub.isoformat()
    title_esc = html.escape(title)
    nav_prefix = ".." if rel_root == ".." else ""
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
    <article>
      <p class="post__date"><time datetime="{pub_s}">{pub_s}</time></p>
      <h1 class="post__title">{title_esc}</h1>
      {body_html}
    </article>
  </main>
  <footer class="site-footer"><p>Lightweight static blog</p></footer>
</body>
</html>
"""


def main() -> None:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    txt_files = [
        p
        for p in sorted(N64.glob("*.txt"))
        if p.name.lower() != "readme.txt"
    ]
    if not txt_files:
        raise SystemExit("No .txt files in n64/ (excluding README.txt)")

    manifest: list[dict] = []

    for path in txt_files:
        slug = path.stem
        raw = path.read_text(encoding="utf-8")
        title, sections = parse_sections(raw)
        pub = date_for_slug(slug)
        manifest.append(
            {
                "slug": slug,
                "title": title,
                "date": pub.isoformat(),
                "file": path.name,
            }
        )
        page = build_page(title, pub, slug, sections, rel_root="..")
        (POSTS_DIR / f"{slug}.html").write_text(page, encoding="utf-8")

    manifest.sort(key=lambda x: x["date"], reverse=True)
    (OUT / "posts.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # index.html
    items = []
    for m in manifest:
        href = f"posts/{m['slug']}.html"
        t = html.escape(m["title"])
        d = m["date"]
        items.append(
            f'  <li class="index__item"><time class="index__date" datetime="{d}">{d}</time> '
            f'<a class="index__link" href="{href}">{t}</a></li>'
        )
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
    <p class="index__meta">N64 notes — publication dates assigned for this site ({DATE_START.isoformat()} … {DATE_END.isoformat()}).</p>
    <ul class="index__list">
{chr(10).join(items)}
    </ul>
  </main>
  <footer class="site-footer"><p>Lightweight static blog</p></footer>
</body>
</html>
"""
    (OUT / "index.html").write_text(index_html, encoding="utf-8")
    (OUT / "about.html").write_text(build_about_page(), encoding="utf-8")
    print(f"Wrote {len(manifest)} posts + about.html to {OUT}")


if __name__ == "__main__":
    main()
