# 2026-03-10 Definition of Done Checklists

## For any runtime PR
- [ ] Route behavior is explicit
- [ ] No silent fallback added
- [ ] Telemetry still emitted
- [ ] Page sources returned for answerable cases
- [ ] Output schema unchanged or intentionally versioned
- [ ] `python scripts/agentfirst.py verify --strict` passes
- [ ] Docker stack rebuilt locally
- [ ] Docs updated
- [ ] Score impact recorded

## For any parser / ingest PR
- [ ] No contest path uses stub parser
- [ ] Page ids generated deterministically
- [ ] Paragraphs map to pages
- [ ] Document type projection generated
- [ ] Fixture ingest test added

## For any scorer PR
- [ ] Exact-answer validation covered
- [ ] No-answer covered
- [ ] Source page validation covered
- [ ] Telemetry completeness covered
- [ ] Regression fixtures added

## For any Codex-generated PR
- [ ] Scope is bounded
- [ ] Files touched are intentionally listed
- [ ] Tests were added, not just updated
- [ ] No TODO/pass/NotImplemented remains in the changed path