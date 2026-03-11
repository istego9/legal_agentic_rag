# Official Dataset Access Policy Note

Date: 2026-03-11

## Decision
- Do not keep organizer-fetched dataset bundles (`questions.json`, `documents.zip`) in the public repository by default.
- Keep only reproducibility artifacts:
  - fetch script: `scripts/fetch_official_dataset.py`
  - checksum manifest: `datasets/manifests/official_fetch_2026-03-11.manifest.json`

## Rationale
- Public redistribution rights can differ from participant access rights.
- Keeping only script + manifest preserves reproducibility while reducing accidental policy violations.

## Operator Instructions
- Fetch locally with API key from environment:
  - `EVAL_API_KEY=... .venv/bin/python scripts/fetch_official_dataset.py --output-dir datasets/official_fetch_local`
- Verify local files against checksum manifest before use.
- If organizers explicitly confirm public redistribution is allowed, this policy can be revisited.
