# Post metadata (optional)

The build script reads `.txt` posts from these folders under the repo root:

| Folder       | Default platform (if `Platform:` is missing) |
|-------------|-----------------------------------------------|
| `n64/`      | N64                                           |
| `snes/`     | SNES                                          |
| `gamecube/` | GameCube                                      |
| `pc/`       | PC                                            |
| `switch/`   | Nintendo Switch                               |
| `switch2/`  | Switch 2                                      |

Inference per file:

- **Platform** — from a `Platform: …` line, otherwise the folder default above.
- **Release year** — earliest year found in the **Release dates** section (falls back to scanning the file).
- **Score** — from emoji thumbs on the `**Verdict:**` line (`👍👍👍` … `👎👎`).
- **Developer** / **Publisher** — first `Developer:` and `Publisher:` line in the file body (used for filters and the “Top developers / publishers” charts on the Posts page).

Override anything by adding an optional **frontmatter** block at the **very top** of a `.txt` file:

```text
---
platform: Nintendo Switch
release_year: 2017
score: 2-up
---

Your Game Title
===============
```

**`platform`:** one of the supported names, e.g. `N64`, `Nintendo 64`, `SNES`, `GameCube`, `Wii`, `Wii U`, `Nintendo Switch`, `Switch 2`, `PC`.

**`release_year`:** integer (calendar year you want listed for “release year” navigation).

**`score`:** one of `3-up`, `2-up`, `1-up`, `1-down`, `2-down` (matches the verdict scale on the About page).

After editing, run `python scripts/build_blog.py` so `blog/index.html`, `blog/posts.json`, and post HTML stay in sync.
