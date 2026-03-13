# Retrieval Quality Report

> Superseded historical snapshot. Current canonical rules-first chunk/proposition pilot truth lives in `.artifacts/...` and is indexed by `reports/corpus_investigation/2026-03-12-version-lineage-rca/chunk_processing_pilot_truth_index.md`.

- report_version: `chunk_processing_retrieval_report_v1`
- query_count: `6`
- top3_expected_hit_count: `6`
- top3_expected_hit_ratio: `1.0`
## items

```json
[
  {
    "question_id": "employment_void_clause_boolean",
    "answer": true,
    "abstained": false,
    "route_name": "article_lookup",
    "top3_contains_expected": true,
    "used_source_page_ids": [
      "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16_6",
      "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16_3"
    ],
    "top_candidates": [
      {
        "paragraph_id": "para_d5434318071aab73242a6bf4",
        "source_page_id": "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16_6",
        "stage": "structural_lookup",
        "score": 2.5875,
        "reasons": [
          "exact_identifier_hit",
          "current_version_soft_boost",
          "article_lookup_structural_match",
          "article_lookup_law_year_match",
          "article_lookup_doc_type_match",
          "semantic_proposition_match",
          "structural_lookup_priority"
        ]
      },
      {
        "paragraph_id": "para_384334b42e2affc76e2037ac",
        "source_page_id": "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16_1",
        "stage": "structural_lookup",
        "score": 2.24,
        "reasons": [
          "exact_identifier_hit",
          "current_version_soft_boost",
          "article_lookup_structural_match",
          "article_lookup_law_year_match",
          "article_lookup_doc_type_match",
          "structural_lookup_priority"
        ]
      },
      {
        "paragraph_id": "para_8c7483ce8efd214e9af93d5e",
        "source_page_id": "fbdd7f9dd299d83b1f398778da2e6765dfaaed62005667264734a1f76ec09071_4",
        "stage": "structural_lookup",
        "score": 2.175,
        "reasons": [
          "exact_identifier_hit",
          "article_lookup_structural_match",
          "article_lookup_doc_type_match",
          "semantic_proposition_match",
          "structural_lookup_priority"
        ]
      }
    ]
  },
  {
    "question_id": "employment_conditional_waiver_boolean",
    "answer": true,
    "abstained": false,
    "route_name": "article_lookup",
    "top3_contains_expected": true,
    "used_source_page_ids": [
      "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16_6",
      "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16_3"
    ],
    "top_candidates": [
      {
        "paragraph_id": "para_d5434318071aab73242a6bf4",
        "source_page_id": "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16_6",
        "stage": "structural_lookup",
        "score": 2.4928,
        "reasons": [
          "exact_identifier_hit",
          "current_version_soft_boost",
          "article_lookup_structural_match",
          "article_lookup_doc_type_match",
          "semantic_proposition_match",
          "structural_lookup_priority"
        ]
      },
      {
        "paragraph_id": "para_384334b42e2affc76e2037ac",
        "source_page_id": "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16_1",
        "stage": "structural_lookup",
        "score": 2.16,
        "reasons": [
          "exact_identifier_hit",
          "current_version_soft_boost",
          "article_lookup_structural_match",
          "article_lookup_doc_type_match",
          "structural_lookup_priority"
        ]
      },
      {
        "paragraph_id": "para_8c7483ce8efd214e9af93d5e",
        "source_page_id": "fbdd7f9dd299d83b1f398778da2e6765dfaaed62005667264734a1f76ec09071_4",
        "stage": "structural_lookup",
        "score": 2.1466,
        "reasons": [
          "exact_identifier_hit",
          "article_lookup_structural_match",
          "article_lookup_doc_type_match",
          "semantic_proposition_match",
          "structural_lookup_priority"
        ]
      }
    ]
  },
  {
    "question_id": "coinmena_costs_amount",
    "answer": null,
    "abstained": true,
    "route_name": "single_case_extraction",
    "top3_contains_expected": true,
    "used_source_page_ids": [],
    "top_candidates": [
      {
        "paragraph_id": "para_af6d26cc942f65b51f507d90",
        "source_page_id": "897ab23ed5a70034d3d708d871ad1da8bc7b6608d94b1ca46b5d578d985d3c13_0",
        "stage": "lexical_projected",
        "score": 0.7024,
        "reasons": [
          "current_version_soft_boost",
          "semantic_proposition_match"
        ]
      },
      {
        "paragraph_id": "para_fe7a3c1a9355672bd16c7dd0",
        "source_page_id": "897ab23ed5a70034d3d708d871ad1da8bc7b6608d94b1ca46b5d578d985d3c13_1",
        "stage": "lexical_projected",
        "score": 0.6743,
        "reasons": [
          "current_version_soft_boost",
          "semantic_proposition_match"
        ]
      },
      {
        "paragraph_id": "para_0fda36dfc3337f971936b06f",
        "source_page_id": "897ab23ed5a70034d3d708d871ad1da8bc7b6608d94b1ca46b5d578d985d3c13_1",
        "stage": "lexical_projected",
        "score": 0.6217,
        "reasons": [
          "current_version_soft_boost",
          "semantic_proposition_match"
        ]
      }
    ]
  },
  {
    "question_id": "coinmena_deadline_days",
    "answer": null,
    "abstained": true,
    "route_name": "single_case_extraction",
    "top3_contains_expected": true,
    "used_source_page_ids": [],
    "top_candidates": [
      {
        "paragraph_id": "para_fe7a3c1a9355672bd16c7dd0",
        "source_page_id": "897ab23ed5a70034d3d708d871ad1da8bc7b6608d94b1ca46b5d578d985d3c13_1",
        "stage": "semantic_proposition",
        "score": 0.7306,
        "reasons": [
          "current_version_soft_boost",
          "semantic_proposition_match"
        ]
      },
      {
        "paragraph_id": "para_0d37002b417bf6ebbc0c91fe",
        "source_page_id": "897ab23ed5a70034d3d708d871ad1da8bc7b6608d94b1ca46b5d578d985d3c13_1",
        "stage": "lexical_projected",
        "score": 0.6498,
        "reasons": [
          "current_version_soft_boost",
          "semantic_proposition_match"
        ]
      },
      {
        "paragraph_id": "para_e10734b444b74ce9ffd5540b",
        "source_page_id": "897ab23ed5a70034d3d708d871ad1da8bc7b6608d94b1ca46b5d578d985d3c13_1",
        "stage": "lexical_projected",
        "score": 0.6462,
        "reasons": [
          "current_version_soft_boost",
          "semantic_proposition_match"
        ]
      }
    ]
  },
  {
    "question_id": "ca004_interest_rate",
    "answer": null,
    "abstained": true,
    "route_name": "single_case_extraction",
    "top3_contains_expected": true,
    "used_source_page_ids": [],
    "top_candidates": [
      {
        "paragraph_id": "para_a6df0c0ab334e3d95dfbaecd",
        "source_page_id": "78ffe994cdc61ce6a2a6937c79fc52751bb5d2b4eaa4019f088fbccf70569c26_2",
        "stage": "lexical_projected",
        "score": 1.1114,
        "reasons": [
          "exact_identifier_hit",
          "current_version_soft_boost",
          "case_lookup_structural_match",
          "semantic_proposition_match"
        ]
      },
      {
        "paragraph_id": "para_828b70be070e5d45a2065a5b",
        "source_page_id": "fbdd7f9dd299d83b1f398778da2e6765dfaaed62005667264734a1f76ec09071_10",
        "stage": "lexical_projected",
        "score": 0.5005,
        "reasons": [
          "semantic_proposition_match"
        ]
      },
      {
        "paragraph_id": "para_a433ef070933d6532f8d4b73",
        "source_page_id": "33bc02044716acdfedb164b065bdaec098aaadcae863c591f9931c88e7307d16_10",
        "stage": "lexical_projected",
        "score": 0.5,
        "reasons": [
          "current_version_soft_boost"
        ]
      }
    ]
  },
  {
    "question_id": "ca004_court_name",
    "answer": null,
    "abstained": true,
    "route_name": "single_case_extraction",
    "top3_contains_expected": true,
    "used_source_page_ids": [],
    "top_candidates": [
      {
        "paragraph_id": "para_0ff30722c98b05a546db920a",
        "source_page_id": "78ffe994cdc61ce6a2a6937c79fc52751bb5d2b4eaa4019f088fbccf70569c26_0",
        "stage": "lexical_projected",
        "score": 1.2939,
        "reasons": [
          "exact_identifier_hit",
          "current_version_soft_boost",
          "case_lookup_structural_match",
          "semantic_proposition_match"
        ]
      },
      {
        "paragraph_id": "para_63b705eb504c14f227944398",
        "source_page_id": "78ffe994cdc61ce6a2a6937c79fc52751bb5d2b4eaa4019f088fbccf70569c26_3",
        "stage": "lexical_projected",
        "score": 1.1814,
        "reasons": [
          "exact_identifier_hit",
          "current_version_soft_boost",
          "case_lookup_structural_match"
        ]
      },
      {
        "paragraph_id": "para_3a99aacbababaf8e70fb5404",
        "source_page_id": "4e387152960c1029b3711cacb05b287b13c977bc61f2558059a62b7b427a62eb_10",
        "stage": "lexical_projected",
        "score": 0.6464,
        "reasons": [
          "semantic_proposition_match"
        ]
      }
    ]
  }
]
```
