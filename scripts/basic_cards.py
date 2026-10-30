"""Compact, source-backed cards. Network discovery remains an agent task."""
from __future__ import annotations

import copy
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import paper_finder as wpf

MISSING = "未查到／待核实"


def utcnow():
    return datetime.now(timezone.utc)


def date_value(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def validate_impact(impact, journal):
    if impact.get("value") is None:
        return
    value = impact["value"]
    if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError("JIF must be a finite nonnegative number")
    year = impact.get("metric_year")
    if type(year) is not int or not 1900 <= year <= utcnow().year:
        raise ValueError("JIF needs a valid metric year")
    if not journal or wpf.norm(journal) != wpf.norm(impact.get("journal")):
        raise ValueError("JIF journal does not match paper")
    wpf.public_url(impact.get("source_url", ""))
    checked = date_value(impact.get("checked_at", ""))
    if checked.date() > utcnow().date():
        raise ValueError("JIF lookup date cannot be in the future")


class JournalCache:
    """Journal identifier + metric year, with in-batch reuse and 30-day freshness.

    An agent supplies newly checked metrics via --details. Expired entries stay
    visible as stale until that lookup succeeds; no network verification is implied.
    """

    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else None
        self.entries = {}
        self.warnings = []
        if self.folder and self.folder.exists():
            for path in self.folder.glob("*.json"):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    validate_impact(record, record.get("journal", ""))
                    if record.get("value") is not None:
                        self.entries[(record["journal_id"], record["metric_year"])] = record
                except (ValueError, KeyError, TypeError, OSError, wpf.PaperError):
                    self.warnings.append("忽略损坏或无效的 JIF 缓存：" + path.name)

    @staticmethod
    def journal_id(metadata):
        return metadata.get("issn_l") or next(iter(metadata.get("issn", [])), "") or "name:" + wpf.norm(metadata.get("venue", ""))

    def remember(self, paper):
        record = paper.get("research", {}).get("impact_factor", {})
        if record.get("value") is None:
            return
        metadata = paper.get("metadata", {})
        if metadata.get("arxiv_id") or metadata.get("version") == "preprint":
            raise ValueError("Preprint does not have its own journal impact factor")
        validate_impact(record, metadata.get("venue", ""))
        record = copy.deepcopy(record)
        record["journal_id"] = self.journal_id(metadata)
        record.pop("cache_status", None)
        key = (record["journal_id"], record["metric_year"])
        previous = self.entries.get(key)
        if previous and date_value(previous["checked_at"]) > date_value(record["checked_at"]):
            return
        self.entries[key] = record
        if self.folder:
            filename = hashlib.sha256(json.dumps(key).encode()).hexdigest() + ".json"
            wpf.write_json(self.folder / filename, record)

    def apply(self, paper):
        metadata = paper.get("metadata", {})
        if metadata.get("arxiv_id") or metadata.get("version") == "preprint":
            return
        supplied = paper.setdefault("research", {}).setdefault("impact_factor", {})
        matches = [v for (identifier, _), v in self.entries.items()
                   if identifier == self.journal_id(metadata)
                   and wpf.norm(v["journal"]) == wpf.norm(metadata.get("venue"))]
        if not matches:
            return
        best = copy.deepcopy(max(matches, key=lambda v: (v["metric_year"], date_value(v["checked_at"]))))
        age = (utcnow() - date_value(best["checked_at"])).total_seconds()
        best["cache_status"] = "fresh" if age < 30 * 86400 else "stale"
        if supplied.get("refresh_error"):
            best["refresh_error"] = supplied["refresh_error"]
        paper["research"]["impact_factor"] = best


def normalize_batch(papers, cache):
    from research_prepare import normalize_research
    for paper in papers:
        try:
            paper["research"] = normalize_research(paper, profile="basic")
            cache.remember(paper)
            if paper.get("metadata"):
                paper.pop("basic_error", None)
        except (ValueError, TypeError, KeyError, wpf.PaperError) as exc:
            # Keep a failed item without leaking invalid detailed metadata into output.
            paper["basic_error"] = str(exc)
            paper["research"] = {}
    for paper in papers:
        if not paper.get("basic_error"):
            cache.apply(paper)


def expand_duplicates(papers):
    by_id = {p["id"]: p for p in papers}
    for p in papers:
        original = by_id.get(p.get("duplicate_of"))
        if original and original.get("verification", {}).get("status") == "verified":
            metadata = original.get("metadata", {})
            if (wpf.normalize_doi(p.get("doi", "")) != wpf.normalize_doi(metadata.get("doi", ""))
                    or p.get("arxiv_id", "") != metadata.get("arxiv_id", "")):
                continue
            p["metadata"] = copy.deepcopy(metadata)
            p["verification"] = wpf.assess(p, metadata, True)
            if p["verification"]["status"] == "verified":
                p["research"] = copy.deepcopy(original.get("research", {}))


def identity(paper):
    if paper.get("verification", {}).get("status") != "verified":
        return ""
    meta = paper.get("metadata", {})
    if meta.get("arxiv_id"):
        return "arxiv:" + meta["arxiv_id"]
    doi = wpf.normalize_doi(meta.get("doi", ""))
    return (doi + "|" + meta.get("version", "published_record")) if doi else ""


def safe_link(value):
    try:
        return wpf.public_url(value) if value else ""
    except (ValueError, wpf.PaperError):
        return ""


def card(paper, source):
    meta = paper.get("metadata", {})
    research = paper.get("research", {})
    bibliography = research.get("bibliography", {})
    authors = bibliography.get("author_details") or meta.get("author_details", [])
    if not authors:
        authors = [{"name": name, "affiliations": []} for name in meta.get("authors", [])]
    doi = wpf.normalize_doi(meta.get("doi") or paper.get("doi", ""))
    impact = research.get("impact_factor", {})
    missing = []
    for key, value in [("正式题名", meta.get("title")), ("DOI", doi), ("作者", authors),
                       ("期刊", meta.get("venue")), ("发表年份", meta.get("year")),
                       ("原文网站", safe_link(meta.get("publisher_url", "")))]:
        if not value:
            missing.append(key)
    if not authors or any(not a.get("affiliations") for a in authors):
        missing.append("作者机构对应")
    if impact.get("value") is None:
        missing.append("JIF及来源")
    elif impact.get("cache_status") == "stale":
        missing.append("JIF缓存超过30天，待更新" + ("（更新失败）" if impact.get("refresh_error") else ""))
    if paper.get("basic_error"):
        missing.append("补充信息校验失败：" + paper["basic_error"])
    evidence = bibliography.get("evidence", [])
    sources = [safe_link(meta.get("metadata_url", "")), safe_link(paper.get("verification", {}).get("evidence_url", ""))]
    sources += [safe_link(e.get("source_url", "")) for e in evidence]
    return {"title": meta.get("title") or paper.get("raw_title") or "未识别论文",
            "doi": doi, "doi_url": "https://doi.org/" + doi if doi else "", "authors": authors,
            "journal": meta.get("venue", ""), "year": meta.get("year"), "impact_factor": impact,
            "publisher_url": safe_link(meta.get("publisher_url", "")),
            "verification": paper.get("verification", {}).get("status", "unresolved"),
            "association": paper.get("association", {}).get("status", "未另行核验"),
            "missing_fields": missing, "evidence_urls": list(dict.fromkeys(filter(None, sources))),
            "origins": [{**source, "association": paper.get("association", {})}], "identity": identity(paper)}


def export_cards(pairs, outdir, warnings=None):
    cards, seen = [], {}
    for paper, source in pairs:
        if paper.get("role") in {"background", "related"}:
            continue
        row = card(paper, source)
        key = row["identity"]
        if key and key in seen:
            existing = seen[key]
            all_evidence = list(dict.fromkeys(existing["evidence_urls"] + row["evidence_urls"]))
            # Prefer the more complete record; never silently combine conflicting affiliations.
            if len(row["missing_fields"]) < len(existing["missing_fields"]):
                origins = existing["origins"]
                existing.update(row)
                existing["origins"] = origins
            existing["origins"].extend(row["origins"])
            existing["evidence_urls"] = all_evidence
        else:
            cards.append(row)
            if key:
                seen[key] = row
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": 1, "profile": "basic", "created_at": wpf.now(), "papers": cards, "warnings": warnings or []}
    wpf.write_json(outdir / "basic-cards.json", result)
    rows = ["# 论文批量信息卡", ""]
    if len(cards) > 1:
        rows += ["| 序号 | 标题 | DOI | 论文核验 |", "|---|---|---|---|"]
        for i, c in enumerate(cards, 1):
            rows.append(f"| {i} | {wpf.md(c['title'])} | {wpf.md(c['doi'] or MISSING)} | {'已核验' if c['verification'] == 'verified' else '待确认'} |")
    csv_rows = []
    for i, c in enumerate(cards, 1):
        jif = c["impact_factor"]
        authors = "；".join(a["name"] + "：" + "、".join(a.get("affiliations") or [MISSING]) for a in c["authors"]) or MISSING
        metric = (f"{jif['value']}（{jif['metric_year']}）；查询日期：{jif['checked_at']}；"
                  + wpf.markdown_link("来源", jif["source_url"]) + "；缓存状态：" + jif.get("cache_status", "未缓存")) if jif.get("value") is not None else MISSING
        doi = wpf.markdown_link(c["doi"], c["doi_url"]) if c["doi"] else MISSING
        if c["verification"] != "verified" and c["doi"]:
            doi += "（待核验）"
        rows += ["", f"## {i}. {wpf.md(c['title'])}", "", "- DOI：" + doi,
                 "- 作者与发表时所属机构：" + wpf.md(authors),
                 "- 期刊／年份：" + wpf.md(c["journal"] or MISSING) + "／" + str(c["year"] or MISSING),
                 "- 影响因子（JIF）：" + metric,
                 "- 原文网站：" + (wpf.markdown_link("出版社／预印本原文", c["publisher_url"]) or MISSING),
                 "- 论文身份：" + ("已核验" if c["verification"] == "verified" else "待确认"),
                 "- 输入对应关系：" + wpf.md(c["association"]),
                 "- 缺失或待核实：" + wpf.md("；".join(c["missing_fields"]) or "无"),
                 "- 来源：" + "；".join(wpf.markdown_link("书目依据", u) for u in c["evidence_urls"]),
                 "- 输入记录：" + wpf.md("；".join(o["source"] + " / " + o["paper_id"] for o in c["origins"]))]
        csv_rows.append({"title": c["title"], "doi": c["doi"] or MISSING, "doi_url": c["doi_url"],
                         "authors_affiliations": authors, "journal": c["journal"], "year": c["year"],
                         "jif": jif.get("value", ""), "jif_year": jif.get("metric_year", ""),
                         "jif_source": jif.get("source_url", ""), "jif_checked_at": jif.get("checked_at", ""),
                         "jif_cache_status": jif.get("cache_status", ""), "publisher_url": c["publisher_url"],
                         "verification": c["verification"], "association": c["association"],
                         "missing_fields": "；".join(c["missing_fields"]), "evidence_urls": "；".join(c["evidence_urls"]),
                         "origins": json.dumps(c["origins"], ensure_ascii=False)})
    rows += ["", *["提示：" + wpf.md(w) for w in warnings or []]]
    (outdir / "basic-cards.md").write_text("\n".join(rows), encoding="utf-8")
    with (outdir / "basic-cards.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        fields = list(csv_rows[0]) if csv_rows else ["title", "doi", "publisher_url", "verification", "missing_fields"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        # Prevent spreadsheet formulas while leaving JSON and Markdown values unchanged.
        writer.writerows({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for k, v in row.items()} for row in csv_rows)
    return result


def prepare_basic(manifest, outdir, cache_path=None):
    cache = JournalCache(cache_path)
    expand_duplicates(manifest["papers"])
    normalize_batch(manifest["papers"], cache)
    pairs = [(p, {"source": manifest.get("source", ""), "paper_id": p["id"]}) for p in manifest["papers"]]
    if not pairs:
        pairs = [({"id": "unresolved"}, {"source": manifest.get("source", ""), "paper_id": "unresolved"})]
    export_cards(pairs, outdir, cache.warnings)
    wpf.write_json(Path(outdir) / "papers.json", manifest)
    wpf.write_json(Path(outdir) / "research-details.json", {"schema_version": 1, "papers": [
        {"id": p["id"], "doi": p.get("metadata", {}).get("doi", ""), "arxiv_id": p.get("metadata", {}).get("arxiv_id", ""), "research": p.get("research", {})} for p in manifest["papers"]]})
    return manifest


def collect_basic(paths, outdir, cache_path=None):
    pairs, posts = [], []
    cache = JournalCache(cache_path)
    for index, path in enumerate(paths, 1):
        try:
            manifest = wpf.read_json(Path(path))
            papers = copy.deepcopy(manifest["papers"])
            expand_duplicates(papers)
            source = manifest.get("source") or str(path)
        except (ValueError, KeyError, OSError, wpf.PaperError) as exc:
            papers, source = [{"id": "unresolved", "basic_error": str(exc)}], str(path)
        posts.append({"id": f"post_{index:03d}", "source": source, "manifest_path": str(path)})
        for p in papers or [{"id": "unresolved"}]:
            pairs.append((p, {"source": source, "post_id": posts[-1]["id"], "paper_id": p["id"]}))
    normalize_batch([p for p, _ in pairs], cache)
    result = export_cards(pairs, outdir, cache.warnings)
    result["posts"] = posts
    result["unique_verified_works"] = [c["identity"] for c in result["papers"] if c["identity"]]
    wpf.write_json(Path(outdir) / "basic-cards.json", result)
    return result
