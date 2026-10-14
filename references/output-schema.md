# Output schema (version 1)

`extract` produces an intake JSON; `resolve` enriches it into `papers.json`. Preserve unknown additional fields so agent review and vision provenance survive subsequent steps.

```json
{
  "schema_version": 1,
  "source": "https://mp.weixin.qq.com/s/example",
  "document": {"text": "Source text", "links": [], "images": [], "metadata": {}},
  "papers": [{
    "id": "paper_001",
    "role": "main",
    "raw_title": "Literal title or explicitly labelled inferred search hint",
    "doi": "",
    "arxiv_id": "",
    "author_hint": "",
    "year_hint": null,
    "venue_hint": "",
    "evidence": [{"kind": "title_label", "quote": "Literal source excerpt", "source": "input filename/URL; screenshot location"}]
  }]
}
```

For images/documents attach `vision_provenance` containing the configured tool's `task_type`, `tool_used`, `confidence`, `result`, `metadata`. Record inferred search hints separately from literal quotations. Use unique stable IDs; merging hints must preserve their original evidence.

`metadata` after lookup: `title`, `authors`, `year`, `venue`, `doi`, `arxiv_id` where relevant, `publisher_url`, `doi_url`, `metadata_source`, `metadata_url`, `version`. Source-specific unknown values are left empty, not invented.

For shared-card screenshots, `source_discovery` retains visible clues, search queries, candidate URLs and vision provenance. `source_verification` records whether the selected full post agrees with the title/account/snippet or captured URL. This is separate from each paper's bibliographic verification. Automatic download is skipped if a shared-card origin is present but the article identity remains unverified.

A batch discovery has `task=share_card_batch` and a `cards` list of individual plans; each nested `share_card.card_id` identifies the source card. One post's `papers` array has no fixed size. `collect` writes a separate `collection.json` with `posts` and `unique_verified_works`, preserving each post/paper occurrence. If a paper was found directly from screenshot topic clues while the post was unavailable, record `association.status=probable` and its reasons separately from verified bibliographic metadata; do not imply that its membership in the original post is proven.

`verification.status`: `verified`, `needs_review`, `unresolved`, `duplicate`. `verification.reasons`, `conflicts`, `checked_at`, `evidence_url` explain the decision. Candidate metadata appear in `candidates`; without verification the first candidate is provisional. `duplicate_of` points to an earlier record; source evidence remains available.

`download.status`:

| Status | Meaning |
|---|---|
| `not_requested` (rendered default) | No download command was run |
| `skipped_unverified` | Identity not confirmed |
| `skipped_source_unverified` | Shared-card candidate post has not been confirmed as the original article |
| `skipped_role` | Not selected main work; classify before downloading |
| `downloaded` | New PDF parsed and title validated |
| `already_present` | Existing target PDF revalidated; no new request |
| `existing_file_needs_review` | Existing file failed validation; preserved |
| `no_oa_pdf_found` | Current OA lookups returned no direct usable PDF location |
| `download_failed` | Known locations were tried but did not yield a validated file |

Successful downloads include relative `path`, `bytes`, `sha256`, `pages`, `identity_basis`, `doi_present`, source/final URLs, access basis, actual version/license where known and timestamp. Failures include bounded attempts and lookup notes. Null license means unknown and does not imply permission to redistribute. Version `unknown` must remain unknown until corroborated.

No abstract, source passage, email, local file path or PDF from a real user belongs in the public repository. Reports may contain such private research material and belong in a separate output directory.
