# Evidence-backed research preparation

The agent performs source inspection and translation. CLI helpers collect metadata when available, validate structured records and render consistent reports; they do not autonomously understand Methods, find every resource or translate abstracts. Finish the agent work before presenting a draft as a completed investigation.

## Basic information

Prefer publisher author information/affiliation footnotes, then PubMed/Europe PMC or Crossref/arXiv metadata as available. Preserve author order and publication-time affiliations; current lab websites cannot silently replace them. Record explicitly marked equal contributions and corresponding authors only. Keep English names when Chinese spellings have not been verified. Crossref's `journal-article` is a bibliographic type, not proof the paper is an original research Article; check the publisher for Review/Perspective etc.

For JIF use the journal's official metrics page or legitimately accessible Clarivate/JCR information. Store `value`, `metric_year`, `journal`, `source_url`, `checked_at` together. Prefer the latest metric actually found and identify its year. Do not mix 2-year JIF, 5-year JIF, CiteScore, SNIP or SJR. Do not infer JIF from a recommendation headline or assign an arXiv preprint a journal's metric without confirmed venue/version information. If unavailable, report pending.

Acquire the original abstract from the publisher or a reliable bibliographic record. Translate into Chinese without adding interpretation, sample counts or conclusions. Preserve negation, uncertainty and the original scope. Retain the original and its source in private research details. `S2 TL;DR`, a generated summary, and promotional text are not original abstracts. A short explanation of the paper may be added separately, labelled as such. Respect applicable copyright limits; if an abstract cannot be reproduced/translated, provide a clearly labelled summary and original source instead of claiming a full translation.

## Related-paper entry

The CLI builds `https://www.connectedpapers.com/search?q=<encoded DOI/arXiv/title>` as a **search entry**. It does not inspect the service or prove coverage, successful graph creation or account entitlement.

Use a controlled browser/search to find the actual paper and graph if possible; capture the returned URL, check the origin against the verified title/DOI, record a date and evidence, and preserve the exact URL. URL structure is not an API guarantee. A URL supplied by the user is `provided`, not automatically `verified`. Initial pass: reuse a matching supplied graph, otherwise try the controlled site once; after a block/timeout keep the search fallback and explain it. Do not retry indefinitely, generate unrelated graphs, bypass quotas or promise a universal direct-link API. No public supported API was established during this project's design.

Similarity edges do not establish direct citation, agreement, experimental validation or ancestry. If exporting related works, retain the service/date/relationship type and verify each selected DOI separately.

## Reproduction resources

Inspect Data Availability, Code Availability, Methods, supplementary files, reporting summaries, and explicit author-linked repository records. Follow relevant links to verify paper title/DOI, accession, versions/commits and access conditions. Examples of possible repositories: GEO/SRA, PRIDE/ProteomeXchange, Zenodo/Figshare, GitHub/GitLab and protocols.io; the location alone does not establish ownership or raw-vs-processed data.

Convert documents with the user's required parser before reading. `scan-resources` accepts already-converted `.md`/`.txt`, preserves line/heading evidence and emits only candidate URL hints. It can miss accession-only datasets, image citations and links not preserved by extraction; it is not an exhaustive search. Do not pass its output directly as verified resources.

The eight checklist categories are raw data, processed data, code, software/compute environment, materials/samples, equipment, supplements and protocols. For each recorded resource retain ownership, access and evidence independently:

- `author_provided`: supplied for this paper by its authors.
- `third_party`: external implementation linked to this paper; not author code.
- `dependency`: generic software/tool/instrument used or explicitly required by the paper.
- `cited_work`: a resource of a referenced paper; provide that paper's DOI or exact arXiv ID/version.
- `not_assessed`: candidate ownership still unconfirmed.

Version/model/quantity/parameters must come from the actual paper or linked environment specification. Recommendations for substitutions belong in a separate note and must be labelled as recommendations. An instrument model is not safely inferred from a familiar workflow name. Software licenses and data-access requirements are not inferred from a public landing page.

Category statuses: `not_checked`, `needs_review`, `verified` (one or more supported records), `not_found` (only within named inspected sources), `not_public` (explicit availability statement), `not_applicable` (reason and source). Every negative conclusion needs evidence and coverage; a blocked full text cannot prove resource absence. One recorded resource does not imply all dependencies have been found. Do not assign a reproducibility score or state that the experiment can be reproduced solely because resources exist.

For reviews/Perspectives, first list the paper's own resources. Experimental conditions quoted from prior work are attributed to that work. Do not silently investigate every reference: if the user wants a specific cited study, create a separately identified dossier or ask which experiment/result they want to reproduce.

The request for a checklist authorizes locating resource links and inspecting relevant accessible descriptions. It does not by itself ask for downloading large datasets, cloning/executing unknown code or installing environments. Those operations are separate user requests. Small source documents needed to inspect Methods/supplements can be obtained through the authorized reading workflow; never substitute supplementary files for the main article.

## Commands and schema

```text
python <skill>/scripts/paper_finder.py prepare --doi "10.…" --out results/paper --cache work/cache
python <skill>/scripts/paper_finder.py prepare --arxiv-id "1706.03762v2" --out results/preprint --cache work/cache
python <skill>/scripts/paper_finder.py prepare --manifest results/paper/papers.json --out results/paper
python <skill>/scripts/paper_finder.py scan-resources --input work/paper.md --source-url "https://publisher.example/article" --doi "10.…" --out work/resource-candidates.json
```

Read generated `research-details.json`, complete the actual research, then merge the reviewed details:

```text
python <skill>/scripts/paper_finder.py prepare --manifest results/paper/papers.json --details work/reviewed-details.json --out results/paper
```

`--out` for an existing manifest must be that manifest's directory, preserving existing PDF paths. `prepare` adds `research` to each paper without discarding source/vision/verification/download evidence. It writes `papers.json`, `report.md`, `references.bib`, `research-details.json`, `research-report.md` and UTF-8-BOM `reproduction-checklist.csv`. Defaults say pending; they are not a completed research report. `report` also rebuilds research exports when `research` is present.

Details are bound by paper ID plus its metadata DOI, or exact arXiv ID/version if there is no DOI. Unknown/mismatched/duplicate IDs are rejected. Object fields merge; lists replace, so retain already-reviewed resources when adding entries. Schema:

```json
{
  "schema_version": 1,
  "papers": [{
    "id": "paper_001", "doi": "10.1234/example.2026",
    "research": {
      "bibliography": {
        "title_zh": "人工翻译的题名", "article_type": "Article", "published_date": "2026-01-02",
        "author_details": [{"name": "Alex Chen", "affiliations": ["Example University"], "roles": ["通讯作者"]}],
        "evidence": [{"source_url": "https://publisher.example/article", "location": "Authors and Affiliations", "quote": "Literal supporting excerpt"}]
      },
      "abstract": {"original": "Original abstract text", "translation_zh": "经核对的中文翻译", "kind": "original_abstract", "source_url": "https://publisher.example/article"},
      "impact_factor": {"value": 2.1, "metric_year": 2025, "journal": "Example Journal", "source_url": "https://publisher.example/metrics", "checked_at": "2026-10-14"},
      "connected_papers": {"status": "search_only"},
      "coverage": [{"source_url": "https://publisher.example/article", "scope": "full_text", "checked_at": "2026-10-14", "note": "Availability statements and Methods inspected"}],
      "resources": [{
        "kind": "code", "name": "Author analysis code", "url": "https://github.com/example/research",
        "status": "verified", "scope": "author_provided", "access": "open", "version": "v1.0",
        "evidence": [{"source_url": "https://publisher.example/article", "location": "Code Availability", "quote": "Literal author code statement"}]
      }],
      "checks": {"code": {"status": "verified", "reason": "Author-linked repository identified; actual execution not tested"}},
      "notes": ["No code was executed; resource presence is not proof of reproducibility."]
    }
  }]
}
```

Evidence needs a public `source_url` and precise `location`; quotes, when retained, are literal and subject to copyright limits. `verified` is an agent-recorded judgement, not independent verification by the renderer. For a verified graph additionally record `url`, `origin_doi` (or matching `origin_title` without DOI), `checked_at` and `evidence`. For `cited_work` resources record `owner_doi` or `owner_arxiv_id`. For negative checks add `reason` and `evidence`.

Keep real abstracts, evidence excerpts, resource details, personal paths and downloaded files out of the public source repository. Publish only synthetic examples unless the user explicitly approves a properly licensed, anonymized real example.
