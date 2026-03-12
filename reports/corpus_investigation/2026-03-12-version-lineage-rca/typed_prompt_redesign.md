## Typed Prompt Redesign And Grounded Consolidated Law Plan

### Why The Current Approach Is Wrong

The current title-page normalizer mixes four responsibilities in one call:

- document-type routing
- field extraction
- review decisioning
- repair/normalization

That shape is brittle. It makes prompt failures look like extraction failures,
and it lets the model produce self-contradictory outputs such as:

- valid case anchor plus `missing_case_anchor`
- case-like court order plus `doc_type=regulation`
- `manual_review_required=true` with no actionable reason

This must be split by document family and by task.

### Relevant OpenAI Best Practices

The redesign should follow the current OpenAI guidance:

- Use structured outputs with explicit JSON Schema, `strict: true`, and
  `additionalProperties: false`.
- Keep system guidance global and stable; keep task details and examples in the
  user message.
- Keep schema keys clear and intuitive, and add descriptions for important
  fields.
- Use evals to compare prompt variants instead of trusting intuition.
- For PDF inputs, models with vision can work from both extracted text and page
  images, which is useful when title pages contain layout or scan artifacts.
- For a smaller GPT-5-family model, prefer `gpt-5-mini`.
- Do not rely on `temperature` for GPT-5-family extraction flows. For GPT-5
  reasoning paths, omit unsupported sampling parameters instead of carrying
  legacy settings forward.

### Hard Requirements For The New Extraction Layer

1. The model does not own `manual_review_required`.
2. The model does not own `doc_type` once deterministic routing is confident.
3. The model returns facts, evidence-bearing candidates, and uncertainty notes.
4. Post-LLM validation computes review flags deterministically.
5. Each prompt has a single document-family scope.
6. Amendment extraction is a separate stage, not a side effect of title parsing.

### New Stage Layout

#### Stage 0: Deterministic Router

Input:

- parser text from title page(s)
- existing deterministic doc-type hints

Output:

- `doc_type`
- `routing_confidence`
- `fallback_doc_type_candidates`

If routing confidence is high, downstream prompts are typed and fixed.

#### Stage 1: Typed Identity Extraction

Use separate prompts:

- `law_title_identity_v1`
- `regulation_title_identity_v1`
- `enactment_notice_title_identity_v1`
- `case_title_identity_v1`

These prompts extract only identity and title-page metadata for that family.

They do not decide review and do not rewrite lineage.

#### Stage 2: Amendment Reference Extraction

Only for `law` and `regulation`.

Prompt:

- `legislative_title_amendment_refs_v1`

Purpose:

- read title-page statements such as `is amended by`, `as amended by`,
  `consolidated version`, `laws amendment law`
- output an ordered list of cited amending laws and version references

This is where title-page amendment references belong.

#### Stage 3: Amendment Operation Extraction

Only for amendment instruments and consolidation tasks.

Prompt:

- `legislative_amendment_ops_v1`

Purpose:

- extract structured amendment operations, such as:
  - replace article text
  - insert article
  - repeal article
  - rename part/title
  - amend definition
  - amend schedule

This stage should run on only the relevant pages, not the whole document by
default.

#### Stage 4: Deterministic Consolidation Engine

This does not ask the model to rewrite the whole law.

It applies extracted amendment operations to a structured base law tree.

Output:

- grounded consolidated snapshot
- unresolved operations queue
- per-node provenance

#### Stage 5: Case Relation Resolution

Only for `case`.

Prompt:

- `case_relation_resolver_v2`

Purpose:

- connect same-case documents
- classify `judgment`, `order`, `reasons`, `appeal`, `permission`
- produce relation edges only

It does not invent legislative supersession.

### Typed Schemas

#### `law_title_identity_v1`

Returns:

- `official_title`
- `short_title`
- `citation_title`
- `law_number`
- `law_year`
- `jurisdiction`
- `issued_date`
- `commencement_date`
- `consolidated_version_label`
- `consolidated_version_date`
- `issuing_authority`
- `uncertainty_notes[]`

Does not return:

- `manual_review_required`
- `current_version`
- `effective_end_date`

#### `regulation_title_identity_v1`

Returns:

- `official_title`
- `regulation_number`
- `regulation_year`
- `jurisdiction`
- `issued_date`
- `commencement_date`
- `issuing_authority`
- `enabled_by_law_title`
- `enabled_by_law_number`
- `enabled_by_law_year`
- `uncertainty_notes[]`

#### `enactment_notice_title_identity_v1`

Returns:

- `notice_title`
- `notice_number`
- `notice_year`
- `issued_date`
- `target_law_title`
- `target_law_number`
- `target_law_year`
- `commencement_date`
- `commencement_scope`
- `uncertainty_notes[]`

#### `case_title_identity_v1`

Returns:

- `official_title`
- `short_title`
- `case_number`
- `claim_number`
- `appeal_number`
- `neutral_citation`
- `court_name`
- `court_level`
- `decision_date`
- `document_role`
- `party_block[]`
- `judge_names[]`
- `presiding_judge`
- `same_case_anchor_candidate`
- `uncertainty_notes[]`

Does not return:

- legislative numbers
- current-version semantics
- review booleans

#### `legislative_title_amendment_refs_v1`

Returns:

- `consolidated_version_label`
- `consolidated_version_date`
- `amending_laws_on_title_page[]`

Each amendment ref:

- `title`
- `law_number`
- `law_year`
- `reference_phrase`
- `order_index`

This prompt should only read title-page evidence.

#### `legislative_amendment_ops_v1`

Returns a list of amendment operations:

- `operation_type`
- `target_path`
- `target_label`
- `replacement_text`
- `insert_after`
- `insert_before`
- `effective_from`
- `source_page_ids[]`
- `source_paragraph_ids[]`
- `uncertainty_notes[]`

### Review Should Become Deterministic

Instead of asking the model for:

- `manual_review_required`
- `manual_review_reasons`

the model should return:

- `missing_required_fields[]`
- `uncertainty_notes[]`
- `unresolved_references[]`

Then code computes:

- `manual_review_required = bool(missing_required_fields or unresolved_references or blocking_uncertainty_notes)`

This removes a large class of self-contradictory outputs.

### Grounded Consolidated Law

Yes, the “stitched law” idea is viable, but only if it is treated as a derived,
grounded artifact rather than a free-form LLM rewrite.

The safe design is:

1. Keep every source law and amending law immutable.
2. Parse the base law into a structural tree:
   - title
   - parts
   - chapters
   - articles
   - subclauses
3. Extract amendment operations from amending laws.
4. Apply those operations deterministically to the tree.
5. Emit a consolidated law snapshot whose every node carries provenance.

### Provenance Requirements For The Consolidated Snapshot

Each consolidated node must carry:

- `consolidated_node_id`
- `logical_path`
- `current_text`
- `effective_from`
- `effective_to`
- `source_fragments[]`

Each source fragment should include:

- `source_doc_id`
- `source_pdf_id`
- `source_page_id`
- `source_paragraph_id`
- `fragment_role`
  - `base_text`
  - `replacement_text`
  - `inserted_text`
  - `repeal_marker`
  - `title_version_note`
- `amendment_doc_id`
- `amendment_page_id`
- `confidence`

This is what makes the stitched law auditable and grounded.

### What Must Not Happen

Do not ask one model call to:

- read all versions
- rewrite the whole law
- silently resolve conflicts
- output only final prose

That would create a synthetic text artifact with weak auditability.

The model should help with:

- identifying structure
- extracting amendment refs
- extracting amendment operations
- resolving ambiguous local matches

The final consolidation must be deterministic and provenance-preserving.

### Recommended Model Strategy

For the metadata extraction and amendment-op path:

- primary model: `gpt-5-mini`
- use reasoning effort `none` or the lowest supported reasoning path for fast,
  schema-driven extraction
- do not send `temperature`
- do not send `top_p`

Use a stronger model only on the unresolved queue.

### Action Items

- [ ] Split the current title-page normalizer into typed prompts by document
      family.
- [ ] Remove model-owned `manual_review_required` from the extraction contract.
- [ ] Add `legislative_title_amendment_refs_v1`.
- [ ] Add deterministic extraction for title-page phrases like `is amended by`
      and `as amended by` before invoking LLM.
- [ ] Add `legislative_amendment_ops_v1` for amendment instruments.
- [ ] Design a structural law tree representation for deterministic
      consolidation.
- [ ] Emit grounded consolidated-law snapshots with per-node provenance.
- [ ] Keep the consolidated law as a derived artifact, never as a replacement
      for immutable source laws.
- [ ] Add evals for:
      - title identity extraction
      - amendment reference extraction
      - amendment operation extraction
      - consolidation correctness
      - provenance completeness
