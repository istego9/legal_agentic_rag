# Full-Corpus Chunk Processing Feasibility Memo

## Scope

This memo records the first corpus-wide run attempt for the current rules-first chunk/proposition stack across the full `30`-document corpus.

It is not a rollout approval memo.

## What Was Changed Before The Run

- active chunk analysis/docs were rewritten to use generic failure-class framing instead of document-named framing
- a separate full-corpus evaluator was added:
  - [run_chunk_processing_full_corpus_eval.py](/Users/artemgendler/dev/legal_agentic_rag/scripts/run_chunk_processing_full_corpus_eval.py)
- the full evaluator disables document metadata normalization for the run, so the run measures the chunk layer rather than re-spending budget on title-page metadata

## Corpus-Wide Run Attempt

Artifact root:

- [chunk_processing_full_corpus_eval_v1](/Users/artemgendler/dev/legal_agentic_rag/.artifacts/competition_runs/full/chunk_processing_full_corpus_eval_v1)

Observed facts:

- full import completed successfully
- import timing:
  - started: `2026-03-13T07:13:25.104316+00:00`
  - completed: `2026-03-13T07:13:34.811866+00:00`
- imported corpus summary:
  - `documents = 30`
  - `pages = 590`
  - `paragraphs = 2433`
  - `relation_edges = 1493`
  - `parse_errors = 0`
  - `parse_warnings = 0`

The chunk evaluator then selected:

- `target_chunk_count = 2151`
- `total_chunk_count = 2433`

This means the current semantic-rich gate classifies about `88.4%` of the corpus as requiring semantic chunk processing.

## Operational Result

The corpus-wide semantic pass did **not** complete within a reasonable evaluation window.

The run remained in:

- `stage = target_chunks_selected`

and never reached:

- `chunk_enrichment_complete`

This makes the current corpus-wide semantic pass operationally non-viable in its present form.

## Interpretation

This is not a document-import bottleneck.

The bottleneck is the current semantic-target selection:

- too many chunks are being treated as semantic-LMM-worthy
- the stack is still effectively trying to semantically process almost the whole corpus

So the present architecture is still:

- viable on the 5-document pilot
- not yet viable on a 30-document corpus-wide semantic pass

## Decision

Do **not** enable full-corpus chunk/proposition semantic rollout yet.

The next step should be:

1. narrow semantic-target selection aggressively
2. separate corpus-wide structural/provenance coverage from semantic-LMM coverage
3. run a corpus-wide evaluation on:
   - all chunks for structure/provenance
   - a much narrower semantic target subset for LLM semantics

## Bottom Line

The 30-document run was worth doing because it exposed the real scaling problem:

- import is fast enough
- semantic chunk targeting is far too broad

That is the current blocker, not the parser and not the corpus assembly.
