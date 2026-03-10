BEGIN;

DROP TABLE IF EXISTS chunk_search_documents;
DROP TABLE IF EXISTS relation_edges;
DROP TABLE IF EXISTS case_chunk_facets;
DROP TABLE IF EXISTS enactment_notice_chunk_facets;
DROP TABLE IF EXISTS regulation_chunk_facets;
DROP TABLE IF EXISTS law_chunk_facets;
DROP TABLE IF EXISTS paragraphs;
DROP TABLE IF EXISTS pages;
DROP TABLE IF EXISTS case_documents;
DROP TABLE IF EXISTS enactment_notice_documents;
DROP TABLE IF EXISTS regulation_documents;
DROP TABLE IF EXISTS law_documents;
DROP TABLE IF EXISTS documents;

COMMIT;
