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

Every user-facing paper result must include a visible DOI field: the complete identifier plus its canonical DOI link, or `未查到／待确认` when unavailable. Reports use a separate DOI column. Unverified identifiers carry `待核验`; an empty JSON DOI remains empty, rather than storing the display placeholder. Absence from lookup results does not establish that no DOI was assigned. This applies to both per-post reports and the combined report, and to chat replies even when only a link or download was requested.

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

## Research preparation extension (v0.2)

The manifest stays `schema_version=1`. `metadata.author_details` preserves publication-time author/affiliation mappings when supplied by the API; `metadata.abstract` stores a source abstract when available. Publisher article type, Chinese translation, dated JIF and resource evidence are agent-reviewed fields under each paper's optional `research`. Existing unknown provenance fields survive `prepare`.

Read [research-preparation.md](research-preparation.md) for the detail schema and source-inspection workflow. `research-details.json` is bound by paper ID and metadata DOI or exact arXiv ID/version. The CLI rejects mismatched details, unsupported resource kinds, unsafe URLs, verified records without evidence, graphs without matching origin evidence, and JIF without journal/year/source/date. These checks validate the record structure, not the truth of an agent's notes.

Resources retain `kind`, `name`, `status`, `scope`, `access`, actual link/accession/version/details and evidence. `cited_work` requires the actual owning paper's DOI/arXiv ID. Category checks record `not_checked`, `needs_review`, `verified`, `not_found`, `not_public` or `not_applicable`, with reasons and evidence for negative findings and actual inspection coverage. Reports render missing values explicitly; blank defaults must not be mistaken for a completed investigation.
