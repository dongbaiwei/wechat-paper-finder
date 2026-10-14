# Matching and review

Keep evidence extraction, bibliographic identity and full-text access as separate decisions.

| Source evidence | Action |
|---|---|
| Literal DOI/PMID/arXiv ID | Resolve the identifier; compare available title/author/year clues. A DOI may refer to a background citation or even be mistyped. |
| Original English title | Search the title with known author/venue/year. Prefer a corroborated record over a search engine's first result. |
| Chinese translation | Use it as a semantic search hint, not a literal English-title match. Retrieve an original title and independently corroborate it. |
| Research description | Combine distinctive methods, organism/material, authors/institution, venue and time. Retain candidates if identity cannot be established. |
| OCR title/DOI | Preserve recognized text and uncertain characters. Test plausible corrections against authoritative metadata; do not silently replace the source evidence. |

The script's similarity is a string ranking metric, not confidence probability. Without a direct identifier, automatic verification requires title similarity >=0.96 plus corroborated author, venue or year. Competing near-identical records or conflicting clues require review. A one-year difference can reflect online/print dates; larger discrepancies require inspection. Author/venue abbreviations may need manual review rather than rejection.

For review, record the authoritative URL actually inspected and the specific agreeing clues. Avoid circular reasoning: a model-generated English title, the search query and a search snippet are not three independent sources. A direct DOI with a translated Chinese title can be verified by the identifier, but a conflicting original English title must be reviewed.

Classify the paper's role from the post's context. “本研究 / 原文链接 / 本文介绍” often indicates main work; reference lists and background paragraphs are not automatic recommendations. The same work can appear in both places; retain evidence and prefer main scope when appropriate.

Deduplicate DOI case/URL variants. For records without DOI use verified arXiv ID including version; title alone is a weaker duplicate key. For a preprint and published paper, preserve both records and their distinct dates, titles and files; record a relationship only when supported. A Crossref correction, editorial or dataset can have a DOI similar to the paper's DOI and is a different object.

Full-text validation requires an expected title on the first page as well as a readable PDF. Finding the target DOI somewhere in a reference list does not establish identity. Cover pages, scans and unfamiliar ligatures may cause conservative validation failures; use document/OCR tools or manual inspection and record the actual method before marking success.

Useful primary API documentation:

- Crossref bibliographic/DOI lookup: https://github.com/Crossref/rest-api-doc
- arXiv identifiers, versions and Atom metadata: https://info.arxiv.org/help/api/user-manual.html
- Europe PMC REST search and OA metadata: https://europepmc.org/RestfulWebService
- Unpaywall DOI API: https://unpaywall.org/products/api
- Unpaywall location/version/license fields: https://unpaywall.org/data-format

The project does not depend on the retired Unpaywall title-search endpoint. More sources may be added through available agent tools; credentials and current limits must be checked before adding a new API adapter.
