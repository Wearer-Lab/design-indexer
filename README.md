# Public PCB link indexer

Copy this directory into a GitHub repository, enable Actions with repository write permissions, and run **Crawl public PCB links** once manually. The workflow then runs every six hours. No personal access token is needed. Run locally with `GITHUB_TOKEN=... python crawler.py --max-repos 250 --max-requests 1500`.

Outputs under `data/`: `github_links.txt` (one immutable GitHub file URL per line), `pcb_links.jsonl` (repo, format, path, commit, blob SHA), and `state.json` (cursor, pending page, scan counts, skipped repositories). Commit all three files; the workflow does so automatically. A candidate is validated by downloading its blob and checking its signature. Current coverage: KiCad boards, Altium PcbDoc compound files, Eagle XML boards, LibrePCB .lpp and gEDA .pcb. It indexes *board designs*, not schematic-only files. Binary validation confirms container type, not full semantic parse; this is a link index, not a complete EDA parser.

**Scale and completeness:** Enumeration starts at repository ID zero and progresses in creation order. At 250 repositories per run, four runs daily scan at most 1,000 repos/day; a full historic crawl is impractical on this schedule. Each repository needs several API calls. Increase the budget only with appropriate API capacity, or use an external persistent worker and storage for a large backfill. Results cover current default-branch snapshots only. Repositories deleted, made private, updated after their turn, or containing unusual PCB formats are absent until separately revisited. `skipped` records errors for later retry. Links may stop working if a repository is removed or access changes. GitHub Actions scheduled runs can be delayed; GitHub may disable them in inactive public repositories.

**Important:** The earlier suggestion to scan every public repository using its tree is costly. The exact public-repository enumeration endpoint exists, but this implementation does not promise exhaustive results within a practical timeframe. No source file content is saved, only metadata and links.

## BoardRepo source

`boardrepo.py` reads the public `https://boardrepo.com/sitemap.xml` and writes deduplicated project page links to `data/boardrepo_links.txt`. The site advertises public crawling in `robots.txt`. This is an index of public project pages, not downloaded designs or a validation of native PCB files. GitHub source links, where available, remain in the existing GitHub index. Run locally with `python boardrepo.py`. The scheduled workflow updates both sources.
