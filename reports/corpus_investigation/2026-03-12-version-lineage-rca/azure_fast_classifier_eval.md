# Azure Fast Classifier Evaluation

- model: `wf-fast10`
- chunk enrichment llm enabled: `False`
- metadata normalization status: `completed`
- llm calls: `32`
- cache hits: `0`
- rate-limit retries: `7`
- prompt tokens: `37616`
- completion tokens: `11503`
- llm-merged docs: `30`
- failed docs: `0`
- case relation edges: `2`

## Findings

- After adding pacing, retries, and cache, the Azure fast-classifier run completed successfully instead of failing partial on 429 bursts.
- All 30 documents reached `llm_merge`.
- Chunk enrichment stayed rules-only, so Azure cost remained limited to title-page normalization and two case-family resolver calls.
- Remaining manual review items are now semantic quality items, not transport failures.
