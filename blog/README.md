# Static blog

Generated from `n64/*.txt` by:

```bash
python scripts/build_blog.py
```

- **Index:** [index.html](index.html)
- **Styles:** [styles.css](styles.css)
- **Manifest:** [posts.json](posts.json) (titles + `YYYY-MM-DD` dates)

Publication dates are deterministic from each file’s slug (MD5 → day in range Sept 2025–Mar 2026), except `lylat-wars` which is pinned as the latest post. `README.txt` is not published.
