# services/ingest

ZIP/PDF ingestion, parsing, dedupe, paragraph chunking, lineage extraction, indexing jobs.

## Deterministic Ingest Command

Run deterministic ingest and emit diagnostics baseline JSON:

```bash
./.venv/bin/python -m services.ingest.ingest deterministic \
  --project-id demo-project \
  --blob-url /abs/path/to/corpus.zip \
  --parse-policy balanced \
  --output reports/ingest_diagnostics_baseline.json
```

Output includes:
- `identity_fingerprint`
- `artifact_fingerprint`
- per-document deterministic artifact snapshot
