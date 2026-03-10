BEGIN;

CREATE TABLE IF NOT EXISTS documents (
    document_id UUID PRIMARY KEY,
    project_id UUID NOT NULL,
    pdf_id TEXT NOT NULL,
    canonical_doc_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    source_file_name TEXT,
    source_sha256 CHAR(64) NOT NULL,
    duplicate_group_id TEXT,
    title_raw TEXT,
    title_normalized TEXT,
    short_title TEXT,
    citation_title TEXT,
    language TEXT,
    jurisdiction TEXT,
    issued_date DATE,
    effective_start_date DATE,
    effective_end_date DATE,
    repealed_date DATE,
    is_current_version BOOLEAN NOT NULL DEFAULT TRUE,
    version_group_id TEXT,
    version_sequence INTEGER,
    supersedes_doc_id UUID,
    superseded_by_doc_id UUID,
    page_count INTEGER NOT NULL CHECK (page_count > 0),
    parser_version TEXT,
    ocr_used BOOLEAN,
    extraction_confidence NUMERIC(6,5),
    ingested_at TIMESTAMPTZ,
    last_reprocessed_at TIMESTAMPTZ,
    topic_tags TEXT[] NOT NULL DEFAULT '{}',
    legal_domains TEXT[] NOT NULL DEFAULT '{}',
    entity_names TEXT[] NOT NULL DEFAULT '{}',
    citation_keys TEXT[] NOT NULL DEFAULT '{}',
    search_text_compact TEXT,
    search_priority_score NUMERIC(8,5),
    status TEXT NOT NULL DEFAULT 'parsed'
);

CREATE TABLE IF NOT EXISTS law_documents (
    document_id UUID PRIMARY KEY REFERENCES documents(document_id) ON DELETE CASCADE,
    law_number TEXT,
    law_year INTEGER,
    law_family_code TEXT,
    instrument_kind TEXT,
    administering_authority TEXT,
    promulgation_date DATE,
    commencement_date DATE,
    last_consolidated_date DATE,
    status TEXT,
    parent_law_id UUID,
    amends_law_ids TEXT[] NOT NULL DEFAULT '{}',
    amended_by_doc_ids UUID[] NOT NULL DEFAULT '{}',
    part_count INTEGER,
    chapter_count INTEGER,
    section_count INTEGER,
    article_count INTEGER,
    schedule_count INTEGER,
    definition_term_count INTEGER,
    defined_terms TEXT[] NOT NULL DEFAULT '{}',
    regulated_subjects TEXT[] NOT NULL DEFAULT '{}',
    obligation_categories TEXT[] NOT NULL DEFAULT '{}',
    penalty_categories TEXT[] NOT NULL DEFAULT '{}',
    procedure_categories TEXT[] NOT NULL DEFAULT '{}',
    exceptions_present BOOLEAN,
    cross_references TEXT[] NOT NULL DEFAULT '{}',
    concept_lineage_ids TEXT[] NOT NULL DEFAULT '{}',
    edition_scope TEXT,
    effective_logic_type TEXT
);

CREATE TABLE IF NOT EXISTS regulation_documents (
    document_id UUID PRIMARY KEY REFERENCES documents(document_id) ON DELETE CASCADE,
    regulation_number TEXT,
    regulation_year INTEGER,
    regulation_type TEXT,
    issuing_authority TEXT,
    enabled_by_law_id TEXT,
    enabled_by_law_title TEXT,
    enabled_by_article_refs TEXT[] NOT NULL DEFAULT '{}',
    status TEXT,
    is_current_version BOOLEAN,
    regulated_entities TEXT[] NOT NULL DEFAULT '{}',
    compliance_subjects TEXT[] NOT NULL DEFAULT '{}',
    reporting_requirements TEXT[] NOT NULL DEFAULT '{}',
    filing_requirements TEXT[] NOT NULL DEFAULT '{}',
    penalty_or_consequence_present BOOLEAN,
    procedural_steps TEXT[] NOT NULL DEFAULT '{}',
    amends_regulation_ids TEXT[] NOT NULL DEFAULT '{}',
    related_law_ids TEXT[] NOT NULL DEFAULT '{}',
    cross_references TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS enactment_notice_documents (
    document_id UUID PRIMARY KEY REFERENCES documents(document_id) ON DELETE CASCADE,
    notice_number TEXT,
    notice_year INTEGER,
    notice_type TEXT,
    issuing_authority TEXT,
    target_doc_id TEXT,
    target_doc_type TEXT,
    target_title TEXT,
    target_law_number TEXT,
    target_law_year INTEGER,
    commencement_scope_type TEXT,
    commencement_date DATE,
    commencement_date_text_raw TEXT,
    target_article_refs TEXT[] NOT NULL DEFAULT '{}',
    excluded_article_refs TEXT[] NOT NULL DEFAULT '{}',
    conditions_precedent TEXT[] NOT NULL DEFAULT '{}',
    territorial_scope TEXT,
    exception_text_present BOOLEAN,
    overrides_prior_notice_ids TEXT[] NOT NULL DEFAULT '{}',
    related_notice_ids TEXT[] NOT NULL DEFAULT '{}',
    linked_version_group_id TEXT
);

CREATE TABLE IF NOT EXISTS case_documents (
    document_id UUID PRIMARY KEY REFERENCES documents(document_id) ON DELETE CASCADE,
    case_number TEXT,
    neutral_citation TEXT,
    court_name TEXT,
    court_level TEXT,
    chamber_or_division TEXT,
    jurisdiction TEXT,
    filing_date DATE,
    hearing_date DATE,
    decision_date DATE,
    judgment_date DATE,
    claimant_names TEXT[] NOT NULL DEFAULT '{}',
    respondent_names TEXT[] NOT NULL DEFAULT '{}',
    appellant_names TEXT[] NOT NULL DEFAULT '{}',
    defendant_names TEXT[] NOT NULL DEFAULT '{}',
    party_names_normalized TEXT[] NOT NULL DEFAULT '{}',
    judge_names TEXT[] NOT NULL DEFAULT '{}',
    presiding_judge TEXT,
    panel_size INTEGER,
    procedural_stage TEXT,
    cause_of_action TEXT,
    legal_topics TEXT[] NOT NULL DEFAULT '{}',
    claim_amounts TEXT[] NOT NULL DEFAULT '{}',
    relief_sought TEXT[] NOT NULL DEFAULT '{}',
    issues_present TEXT[] NOT NULL DEFAULT '{}',
    final_disposition TEXT,
    outcome_for_claimant TEXT,
    outcome_for_respondent TEXT,
    cited_law_ids TEXT[] NOT NULL DEFAULT '{}',
    cited_article_refs TEXT[] NOT NULL DEFAULT '{}',
    cited_case_ids TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS pages (
    page_id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    pdf_id TEXT NOT NULL,
    page_num INTEGER NOT NULL CHECK (page_num >= 0),
    source_page_id TEXT NOT NULL,
    page_label_raw TEXT,
    page_text_raw TEXT NOT NULL,
    page_text_clean TEXT,
    page_class TEXT,
    heading_path TEXT[] NOT NULL DEFAULT '{}',
    contains_dates BOOLEAN NOT NULL DEFAULT FALSE,
    contains_money BOOLEAN NOT NULL DEFAULT FALSE,
    contains_party_names BOOLEAN NOT NULL DEFAULT FALSE,
    contains_judges BOOLEAN NOT NULL DEFAULT FALSE,
    contains_article_refs BOOLEAN NOT NULL DEFAULT FALSE,
    contains_schedule_refs BOOLEAN NOT NULL DEFAULT FALSE,
    contains_amendment_language BOOLEAN NOT NULL DEFAULT FALSE,
    contains_commencement_language BOOLEAN NOT NULL DEFAULT FALSE,
    dominant_section_kind TEXT,
    search_text_compact TEXT
);

CREATE TABLE IF NOT EXISTS paragraphs (
    paragraph_id UUID PRIMARY KEY,
    page_id UUID NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    paragraph_index INTEGER NOT NULL CHECK (paragraph_index >= 0),
    heading_path TEXT[] NOT NULL DEFAULT '{}',
    paragraph_class TEXT NOT NULL,
    text TEXT NOT NULL,
    text_clean TEXT,
    text_compact TEXT,
    retrieval_text TEXT,
    summary_tag TEXT,
    entities TEXT[] NOT NULL DEFAULT '{}',
    entity_names_normalized TEXT[] NOT NULL DEFAULT '{}',
    article_refs TEXT[] NOT NULL DEFAULT '{}',
    schedule_refs TEXT[] NOT NULL DEFAULT '{}',
    law_refs TEXT[] NOT NULL DEFAULT '{}',
    case_refs TEXT[] NOT NULL DEFAULT '{}',
    dates TEXT[] NOT NULL DEFAULT '{}',
    money_mentions TEXT[] NOT NULL DEFAULT '{}',
    roles TEXT[] NOT NULL DEFAULT '{}',
    topic_tags TEXT[] NOT NULL DEFAULT '{}',
    legal_action_tags TEXT[] NOT NULL DEFAULT '{}',
    chunk_type TEXT NOT NULL DEFAULT 'paragraph',
    chunk_index_on_page INTEGER,
    char_start INTEGER,
    char_end INTEGER,
    section_kind TEXT,
    structural_level INTEGER,
    parent_section_id TEXT,
    prev_chunk_id UUID,
    next_chunk_id UUID,
    effective_start_date DATE,
    effective_end_date DATE,
    is_current_version BOOLEAN,
    version_lineage_id TEXT,
    canonical_concept_id TEXT,
    historical_relation_type TEXT,
    exact_terms TEXT[] NOT NULL DEFAULT '{}',
    search_keywords TEXT[] NOT NULL DEFAULT '{}',
    rank_hints TEXT[] NOT NULL DEFAULT '{}',
    answer_candidate_types TEXT[] NOT NULL DEFAULT '{}',
    confidence_score NUMERIC(6,5),
    parser_flags TEXT[] NOT NULL DEFAULT '{}',
    extraction_method TEXT,
    tagging_model_version TEXT,
    last_tagged_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS law_chunk_facets (
    chunk_id UUID PRIMARY KEY REFERENCES paragraphs(paragraph_id) ON DELETE CASCADE,
    law_number TEXT,
    law_year INTEGER,
    article_number TEXT,
    article_number_normalized TEXT,
    article_title TEXT,
    part_ref TEXT,
    chapter_ref TEXT,
    section_ref TEXT,
    schedule_number TEXT,
    schedule_title TEXT,
    definition_term TEXT,
    provision_kind TEXT,
    administering_authority TEXT,
    amends_law_ids TEXT[] NOT NULL DEFAULT '{}',
    amended_by_doc_ids UUID[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS regulation_chunk_facets (
    chunk_id UUID PRIMARY KEY REFERENCES paragraphs(paragraph_id) ON DELETE CASCADE,
    regulation_number TEXT,
    regulation_year INTEGER,
    regulation_type TEXT,
    enabled_by_law_id TEXT,
    enabled_by_article_refs TEXT[] NOT NULL DEFAULT '{}',
    provision_number TEXT,
    provision_kind TEXT,
    regulated_entities TEXT[] NOT NULL DEFAULT '{}',
    compliance_subjects TEXT[] NOT NULL DEFAULT '{}',
    reporting_requirement_present BOOLEAN,
    filing_requirement_present BOOLEAN
);

CREATE TABLE IF NOT EXISTS enactment_notice_chunk_facets (
    chunk_id UUID PRIMARY KEY REFERENCES paragraphs(paragraph_id) ON DELETE CASCADE,
    notice_number TEXT,
    notice_year INTEGER,
    target_doc_id TEXT,
    target_law_number TEXT,
    target_article_refs TEXT[] NOT NULL DEFAULT '{}',
    excluded_article_refs TEXT[] NOT NULL DEFAULT '{}',
    commencement_scope_type TEXT,
    commencement_date DATE,
    rule_type TEXT,
    condition_text_present BOOLEAN
);

CREATE TABLE IF NOT EXISTS case_chunk_facets (
    chunk_id UUID PRIMARY KEY REFERENCES paragraphs(paragraph_id) ON DELETE CASCADE,
    case_number TEXT,
    neutral_citation TEXT,
    court_name TEXT,
    court_level TEXT,
    decision_date DATE,
    section_kind_case TEXT,
    party_names TEXT[] NOT NULL DEFAULT '{}',
    party_roles_present TEXT[] NOT NULL DEFAULT '{}',
    judge_names TEXT[] NOT NULL DEFAULT '{}',
    presiding_judge TEXT,
    claim_amounts TEXT[] NOT NULL DEFAULT '{}',
    relief_sought TEXT[] NOT NULL DEFAULT '{}',
    disposition_label TEXT,
    outcome_side TEXT,
    cited_law_ids TEXT[] NOT NULL DEFAULT '{}',
    cited_case_ids TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS relation_edges (
    edge_id UUID PRIMARY KEY,
    source_object_type TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    target_object_type TEXT NOT NULL,
    target_object_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    confidence_score NUMERIC(6,5),
    source_page_id TEXT,
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS chunk_search_documents (
    chunk_id UUID PRIMARY KEY REFERENCES paragraphs(paragraph_id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    pdf_id TEXT NOT NULL,
    page_id UUID NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    doc_type TEXT NOT NULL,
    title_normalized TEXT,
    short_title TEXT,
    jurisdiction TEXT,
    status TEXT,
    is_current_version BOOLEAN,
    effective_start_date DATE,
    effective_end_date DATE,
    heading_path TEXT[] NOT NULL DEFAULT '{}',
    section_kind TEXT,
    text_clean TEXT NOT NULL,
    retrieval_text TEXT NOT NULL,
    entity_names TEXT[] NOT NULL DEFAULT '{}',
    article_refs TEXT[] NOT NULL DEFAULT '{}',
    dates TEXT[] NOT NULL DEFAULT '{}',
    money_values TEXT[] NOT NULL DEFAULT '{}',
    exact_terms TEXT[] NOT NULL DEFAULT '{}',
    search_keywords TEXT[] NOT NULL DEFAULT '{}',
    version_lineage_id TEXT,
    canonical_concept_id TEXT,
    historical_relation_type TEXT,
    law_number TEXT,
    law_year INTEGER,
    regulation_number TEXT,
    regulation_year INTEGER,
    notice_number TEXT,
    notice_year INTEGER,
    case_number TEXT,
    court_name TEXT,
    decision_date DATE,
    article_number TEXT,
    section_ref TEXT,
    schedule_number TEXT,
    administering_authority TEXT,
    enabled_by_law_id TEXT,
    target_doc_id TEXT,
    target_article_refs TEXT[] NOT NULL DEFAULT '{}',
    commencement_date DATE,
    commencement_scope_type TEXT,
    judge_names TEXT[] NOT NULL DEFAULT '{}',
    party_names_normalized TEXT[] NOT NULL DEFAULT '{}',
    final_disposition TEXT,
    edge_types TEXT[] NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_documents_doc_type ON documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents (status);
CREATE INDEX IF NOT EXISTS idx_documents_version_group ON documents (version_group_id);
CREATE INDEX IF NOT EXISTS idx_documents_effective_dates ON documents (effective_start_date, effective_end_date);

CREATE INDEX IF NOT EXISTS idx_pages_document_id ON pages (document_id);
CREATE INDEX IF NOT EXISTS idx_pages_source_page_id ON pages (source_page_id);

CREATE INDEX IF NOT EXISTS idx_paragraphs_document_id ON paragraphs (document_id);
CREATE INDEX IF NOT EXISTS idx_paragraphs_version_lineage_id ON paragraphs (version_lineage_id);
CREATE INDEX IF NOT EXISTS idx_paragraphs_canonical_concept_id ON paragraphs (canonical_concept_id);
CREATE INDEX IF NOT EXISTS idx_paragraphs_section_kind ON paragraphs (section_kind);
CREATE INDEX IF NOT EXISTS idx_paragraphs_topic_tags_gin ON paragraphs USING GIN (topic_tags);
CREATE INDEX IF NOT EXISTS idx_paragraphs_article_refs_gin ON paragraphs USING GIN (article_refs);

CREATE INDEX IF NOT EXISTS idx_relation_edges_type ON relation_edges (edge_type);
CREATE INDEX IF NOT EXISTS idx_relation_edges_source ON relation_edges (source_object_id);
CREATE INDEX IF NOT EXISTS idx_relation_edges_target ON relation_edges (target_object_id);

CREATE INDEX IF NOT EXISTS idx_chunk_search_doc_type ON chunk_search_documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_chunk_search_status ON chunk_search_documents (status);
CREATE INDEX IF NOT EXISTS idx_chunk_search_law_number ON chunk_search_documents (law_number);
CREATE INDEX IF NOT EXISTS idx_chunk_search_case_number ON chunk_search_documents (case_number);
CREATE INDEX IF NOT EXISTS idx_chunk_search_notice_number ON chunk_search_documents (notice_number);
CREATE INDEX IF NOT EXISTS idx_chunk_search_regulation_number ON chunk_search_documents (regulation_number);
CREATE INDEX IF NOT EXISTS idx_chunk_search_version_lineage_id ON chunk_search_documents (version_lineage_id);
CREATE INDEX IF NOT EXISTS idx_chunk_search_canonical_concept_id ON chunk_search_documents (canonical_concept_id);
CREATE INDEX IF NOT EXISTS idx_chunk_search_edge_types_gin ON chunk_search_documents USING GIN (edge_types);
CREATE INDEX IF NOT EXISTS idx_chunk_search_article_refs_gin ON chunk_search_documents USING GIN (article_refs);

COMMIT;
