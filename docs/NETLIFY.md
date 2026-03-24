# Hosting on Netlify

## Deploy

- **Publish directory:** `blog` (set automatically if you use the repo `netlify.toml`).
- **Build command:** `python3 scripts/build_blog.py` (generates HTML from `n64/*.txt`).

Connect the Git repo in Netlify; each push rebuilds the site.

## Traffic / analytics (pick one)

### 1. Netlify Analytics (easiest, no code)

Paid add-on: **Site configuration → Analytics**. Server-side, no cookies, no script in your pages. Good if you want “how many visits / top pages” without editing HTML.

### 2. Snippet injection (no rebuild)

**Site configuration → Environment variables → Snippet injection** (or **Build & deploy → Post processing → Snippet injection** depending on UI).

Paste your GA4, Plausible, or Cloudflare beacon snippet there. Netlify injects it on every HTML response—no change to `build_blog.py` and no `analytics.fragment.html` file.

### 3. Build-time fragment (this repo)

1. Copy `analytics.fragment.example.html` → `analytics.fragment.html` at the **repo root**.
2. Edit it: uncomment one block and fill in IDs / domain.
3. Run `python scripts/build_blog.py` — the snippet is inserted before `</body>` on index, about, and all posts.

`analytics.fragment.html` is listed in `.gitignore`. To use it on Netlify, either:

- **`git add -f analytics.fragment.html`** and commit (IDs are visible in page source anyway), or  
- Rely on **snippet injection** (2) instead so nothing sensitive lives in the repo.

## Local preview

```bash
python scripts/build_blog.py
cd blog && python -m http.server 8080
```

Open `http://127.0.0.1:8080`.
