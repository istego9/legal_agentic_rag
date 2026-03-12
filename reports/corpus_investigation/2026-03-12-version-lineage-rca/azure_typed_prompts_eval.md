## Azure Typed Prompt Eval

- report: `reports/competition_runs/prepare_report.azure_typed_prompts_pg_final_rerun.json`
- metadata profile: `corpus_metadata_normalizer_v3`
- title-page prompt set: `corpus_typed_title_identity_prompt_set_v1`
- model: `wf-fast10`
- status: `completed`
- cache hits: `32`
- manual review docs: `0`

### Notes

- Typed prompts are now selected per routed document family.
- Title-page amendment refs are persisted for legislative documents when phrases like `As amended by` are present.
- The model path is still using the current Azure deployment from env; GPT-5-mini override is implemented in code/config, but not activated in this run.
