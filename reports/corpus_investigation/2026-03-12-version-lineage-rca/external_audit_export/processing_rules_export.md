# Processing Rules Export

- export_version: `external_audit_processing_rules_v2`
- documents_zip: `/Users/artemgendler/dev/legal_agentic_rag/datasets/official_fetch_2026-03-11/documents.zip`
- metadata profile: `corpus_metadata_normalizer_v5`
- metadata deployment: `wf-gpt5mini-metadata`
- api mode: `responses`
- reasoning effort: `minimal`
- verbosity: `low`

## Ingest Rules
- parser-only ingest with stable page identities
- no title fallback during metadata recognition
- amendment references extracted as ordered arrays
- court structure normalized against repo-controlled registry enriched from official DIFC sources

## Included Prompt Files
- `/Users/artemgendler/dev/legal_agentic_rag/packages/prompts/corpus_law_title_identity_v2.md`
- `/Users/artemgendler/dev/legal_agentic_rag/packages/prompts/corpus_regulation_title_identity_v2.md`
- `/Users/artemgendler/dev/legal_agentic_rag/packages/prompts/corpus_enactment_notice_title_identity_v2.md`
- `/Users/artemgendler/dev/legal_agentic_rag/packages/prompts/corpus_case_title_identity_v2.md`
- `/Users/artemgendler/dev/legal_agentic_rag/packages/prompts/corpus_other_title_router_v2.md`

## Included Implementation Files
- `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/court_registry_v1.json`
- `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/court_registry.py`
- `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/corpus_metadata_normalizer.py`
- `/Users/artemgendler/dev/legal_agentic_rag/services/ingest/ingest.py`
- `/Users/artemgendler/dev/legal_agentic_rag/apps/api/src/legal_rag_api/azure_llm.py`

## Included Test Files
- `/Users/artemgendler/dev/legal_agentic_rag/tests/contracts/test_azure_llm_contracts.py`
- `/Users/artemgendler/dev/legal_agentic_rag/tests/contracts/test_azure_docker_env_contract.py`
- `/Users/artemgendler/dev/legal_agentic_rag/tests/contracts/test_corpus_metadata_normalizer.py`
- `/Users/artemgendler/dev/legal_agentic_rag/tests/contracts/test_ingest_stub_titles.py`
