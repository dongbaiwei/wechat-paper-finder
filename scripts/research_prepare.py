"""Evidence-backed research dossiers; discovery and translation remain agent tasks."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import re
import urllib.parse

import paper_finder as wpf


KINDS = {
    "raw_data": "原始数据", "processed_data": "处理后数据", "code": "代码",
    "software": "计算环境与软件", "materials": "材料与样本",
    "equipment": "仪器设备", "supplement": "补充材料", "protocol": "操作协议",
}
STATUSES = {
    "not_checked": "尚未检查", "needs_review": "待核验", "verified": "已核实记录",
    "not_found": "在已检查范围内未找到", "not_public": "作者明确未公开",
    "not_applicable": "不适用",
}
SCOPES = {"author_provided", "third_party", "cited_work", "dependency", "not_assessed"}
ACCESS = {"open", "restricted", "unavailable", "unknown"}


def url(value):
    try:
        return wpf.public_url(value)
    except (wpf.PaperError, ValueError) as exc:
        raise ValueError(str(exc)) from exc


def evidence_checked(items):
    if not isinstance(items, list):
        raise ValueError("Evidence must be a list")
    for item in items:
        if not isinstance(item, dict) or not item.get("location"):
            raise ValueError("Evidence needs source_url and a specific location")
        url(item.get("source_url", ""))
    return bool(items)


def merge(base, patch):
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def connected_papers(paper, supplied):
    """Never fabricate a graph identifier; a search entry is always labelled as such."""
    metadata = paper.get("metadata", {})
    doi = wpf.normalize_doi(metadata.get("doi", ""))
    query = metadata.get("title") or ""
    graph = copy.deepcopy(supplied or {})
    graph["search_url"] = "https://www.connectedpapers.com/search?" + urllib.parse.urlencode({"q": query}) if query else ""
    graph.setdefault("status", "search_only")
    if graph["status"] not in {"search_only", "provided", "verified", "unavailable"}:
        raise ValueError("Invalid Connected Papers status")
    if graph.get("url"):
        parts = urllib.parse.urlsplit(url(graph["url"]))
        if parts.hostname not in {"connectedpapers.com", "www.connectedpapers.com"} or not parts.path.startswith("/main/"):
            raise ValueError("Graph URL must be an actual Connected Papers /main/ URL")
        if graph["status"] in {"search_only", "unavailable"}:
            raise ValueError("A graph URL must be labelled provided or verified")
    elif graph["status"] in {"provided", "verified"}:
        raise ValueError("Graph URL required")
    if graph["status"] == "verified":
        if paper.get("verification", {}).get("status") != "verified":
            raise ValueError("Verify the paper before confirming its graph")
        if doi:
            if wpf.normalize_doi(graph.get("origin_doi", "")) != doi:
                raise ValueError("Graph origin DOI differs from the paper")
        elif wpf.norm(graph.get("origin_title")) != wpf.norm(metadata.get("title")):
            raise ValueError("Graph origin title differs from the paper")
        if not graph.get("checked_at") or not evidence_checked(graph.get("evidence", [])):
            raise ValueError("Verified graph needs inspection date and origin evidence")
    graph.setdefault("note", "检索入口不保证已生成图谱；图谱展示相似性，不等同于直接引用关系。")
    return graph


def normalize_research(paper):
    metadata = paper.get("metadata", {})
    research = copy.deepcopy(paper.get("research", {}))
    identity = "arxiv:" + metadata["arxiv_id"] if metadata.get("arxiv_id") else wpf.normalize_doi(metadata.get("doi", ""))
    if research.get("origin_identifier") and research["origin_identifier"] != identity:
        raise ValueError("Research dossier belongs to another paper/version; review/reset its details")
    research["origin_identifier"] = identity
    bibliography = research.setdefault("bibliography", {})
    bibliography.setdefault("author_details", metadata.get("author_details", []))
    bibliography.setdefault("article_type", "")
    bibliography.setdefault("title_zh", "")
    if bibliography.get("evidence"):
        evidence_checked(bibliography["evidence"])
    for author in bibliography["author_details"]:
        if not author.get("name") or not isinstance(author.get("affiliations", []), list):
            raise ValueError("Author details need a name and affiliation list")
        if metadata.get("authors") and wpf.norm(author["name"]) not in {wpf.norm(a) for a in metadata["authors"]}:
            raise ValueError("Author is not in this paper's verified metadata")
    for name in metadata.get("authors", []):
        if wpf.norm(name) not in {wpf.norm(a["name"]) for a in bibliography["author_details"]}:
            bibliography["author_details"].append({"name": name, "affiliations": [], "roles": []})
    abstract = research.setdefault("abstract", {})
    abstract.setdefault("original", metadata.get("abstract", ""))
    abstract.setdefault("translation_zh", "")
    abstract.setdefault("source_url", metadata.get("metadata_url", "") if abstract["original"] else "")
    abstract.setdefault("kind", "original_abstract")
    if abstract["kind"] != "original_abstract":
        raise ValueError("Only the original abstract belongs in abstract; keep TL;DR/summary in notes")
    if abstract.get("source_url"):
        url(abstract["source_url"])
    if abstract["translation_zh"]:
        if not abstract["original"] or not abstract.get("source_url") or abstract["kind"] != "original_abstract":
            raise ValueError("Chinese abstract translation needs an original abstract and source; TL;DR is not an abstract")
    impact = research.setdefault("impact_factor", {})
    if impact.get("value") is not None:
        if isinstance(impact["value"], bool) or float(impact["value"]) <= 0:
            raise ValueError("Impact factor must be a positive number")
        if not isinstance(impact.get("metric_year"), int) or isinstance(impact["metric_year"], bool) or not 1900 <= impact["metric_year"] <= 2100:
            raise ValueError("Impact factor requires its metric year")
        if wpf.norm(impact.get("journal")) != wpf.norm(metadata.get("venue")) or not impact.get("journal"):
            raise ValueError("Impact factor belongs to a different or unspecified journal")
        url(impact.get("source_url", ""))
        if not impact.get("checked_at"):
            raise ValueError("Impact factor requires a lookup date")
    research["connected_papers"] = connected_papers(paper, research.get("connected_papers"))
    coverage = research.setdefault("coverage", [])
    if not isinstance(coverage, list):
        raise ValueError("Coverage must be a list of actually inspected sources")
    for source in coverage:
        url(source.get("source_url", ""))
        if source.get("scope") not in {"publisher_preview", "abstract", "full_text", "methods", "supplement", "repository", "journal_metrics", "graph", "other"} or not source.get("checked_at"):
            raise ValueError("Each inspected source requires scope and checked_at")
    resources = research.setdefault("resources", [])
    if not isinstance(resources, list):
        raise ValueError("Resources must be a list")
    for resource in resources:
        if resource.get("kind") not in KINDS or resource.get("status", "needs_review") not in {"verified", "needs_review"}:
            raise ValueError("Invalid resource kind/status")
        resource.setdefault("status", "needs_review")
        resource.setdefault("scope", "not_assessed")
        resource.setdefault("access", "unknown")
        if resource["scope"] not in SCOPES or resource["access"] not in ACCESS:
            raise ValueError("Invalid resource ownership/access")
        if resource.get("url"):
            url(resource["url"])
        if resource.get("owner_doi"):
            resource["owner_doi"] = wpf.normalize_doi(resource["owner_doi"])
            if not resource["owner_doi"]:
                raise ValueError("Resource owner DOI is invalid")
            if resource["scope"] == "author_provided" and resource["owner_doi"] != wpf.normalize_doi(metadata.get("doi", "")):
                raise ValueError("An author-provided resource must belong to this paper")
        proven = evidence_checked(resource.get("evidence", []))
        if resource["scope"] == "cited_work":
            owner = wpf.normalize_doi(resource.get("owner_doi", "")) or resource.get("owner_arxiv_id")
            if not owner:
                raise ValueError("Cited-work resources require the actual owner's DOI/arXiv ID")
            if wpf.normalize_doi(resource.get("owner_doi", "")) == wpf.normalize_doi(metadata.get("doi", "")) and metadata.get("doi"):
                raise ValueError("A cited-work resource cannot belong to the origin paper")
        if resource["status"] == "verified":
            if paper.get("verification", {}).get("status") != "verified":
                raise ValueError("Verify the paper before confirming resource ownership")
            if not resource.get("name") or not proven or resource["scope"] == "not_assessed":
                raise ValueError("Verified resource needs a name, ownership and evidence")
            if not any(resource.get(key) for key in ["url", "accession", "details"]):
                raise ValueError("Verified resource needs a link, accession or reported details")
    checks = research.setdefault("checks", {})
    for kind in KINDS:
        item = checks.setdefault(kind, {"status": "not_checked", "reason": ""})
        if item.get("status") not in STATUSES:
            raise ValueError("Invalid resource check status")
        has_verified = any(r["kind"] == kind and r["status"] == "verified" for r in resources)
        if item["status"] == "verified" and not has_verified:
            raise ValueError("A completed check requires a verified resource record")
        if item["status"] in {"not_found", "not_public", "not_applicable"}:
            if not item.get("reason") or not evidence_checked(item.get("evidence", [])):
                raise ValueError("Negative/not-applicable checks require a reason and source evidence")
            inspected = {source["source_url"] for source in coverage}
            if not any(e["source_url"] in inspected for e in item["evidence"]):
                raise ValueError("Negative checks must cite a source in actual inspection coverage")
            if has_verified:
                raise ValueError("A negative check conflicts with an existing verified resource")
    research.setdefault("notes", [])
    research["prepared_at"] = wpf.now()
    return research


def scan_resources(path, source_url, doi=""):
    """Find leads in already-converted Markdown; never infer ownership or completeness."""
    path = Path(path)
    if path.suffix.casefold() not in {".md", ".txt"}:
        raise ValueError("Convert documents to Markdown with the configured parser first")
    source_url = url(source_url)
    candidates, seen = [], set()
    heading = ""
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if line.startswith("#"):
            heading = wpf.clean(line.lstrip("#"))
        # Markdown destinations first, then ordinary URLs; hints are reviewed by the agent.
        links = re.findall(r"\]\((https?://[^\s]+?)\)", line)
        links += re.findall(r"https?://[^\s<>\"]+", line)
        for raw in links:
            candidate = raw.rstrip(".,;:，。；：)")
            try:
                candidate = url(candidate)
            except ValueError:
                continue
            if candidate in seen:
                continue
            host = urllib.parse.urlsplit(candidate).hostname or ""
            text = (heading + " " + line).casefold()
            hint = "code" if host in {"github.com", "gitlab.com", "bitbucket.org"} else "unknown"
            if "proteomexchange" in host or "ebi.ac.uk/pride" in candidate or "ncbi.nlm.nih.gov/geo" in candidate or "ncbi.nlm.nih.gov/sra" in candidate:
                hint = "data"
            elif host == "protocols.io" or host.endswith(".protocols.io"):
                hint = "protocol"
            elif candidate.casefold().endswith(".pdf") and ("supplement" in text or "补充" in text):
                hint = "supplement"
            if hint == "unknown" and not any(word in text for word in ["data", "code", "software", "supplement", "protocol", "仪器", "材料", "数据", "代码"]):
                continue
            seen.add(candidate)
            candidates.append({"url": candidate, "kind_hint": hint, "status": "needs_review", "scope": "not_assessed", "evidence": [{"source_url": source_url, "location": f"{path.name}:line {line_number}; {heading}", "quote": line.strip()}]})
    return {"schema_version": 1, "task": "resource_candidates", "origin_doi": wpf.normalize_doi(doi), "candidates": candidates, "notes": ["URL discovery only; inspect resource pages and paper availability statements before adding verified records. No dataset/code execution or download occurred."]}


def evidence_links(items):
    return "；".join(wpf.markdown_link(wpf.md(item["location"]), item["source_url"]) for item in items)


def render_report(manifest, outdir):
    rows = ["# 论文研究准备报告", "", "资源记录依据已查阅来源整理；条件齐全程度不等于实际复现成功。", ""]
    checklist = []
    for paper in manifest["papers"]:
        metadata, research = paper.get("metadata", {}), paper["research"]
        bibliography, abstract, impact = research["bibliography"], research["abstract"], research["impact_factor"]
        rows += [f"## {wpf.md(paper['id'])} · {wpf.md(metadata.get('title') or paper.get('raw_title'))}", "", "### 基本信息", "",
                 "- DOI：" + wpf.doi_display(paper), "- 论文核验：" + wpf.md(paper.get("verification", {}).get("status", "unresolved")),
                 "- 与输入来源的对应关系：" + wpf.md(paper.get("association", {}).get("status", "未另行标注")),
                 "- 中文题名：" + wpf.md(bibliography.get("title_zh") or "待翻译"),
                 "- 期刊：" + wpf.md(metadata.get("venue") or "待确认"),
                 "- 年份／日期：" + wpf.md(bibliography.get("published_date") or metadata.get("year") or "待确认"),
                 "- 文章类型：" + wpf.md(bibliography.get("article_type") or "待核实；书目类型 " + metadata.get("type", "unknown")),
                 "- 作者：" + wpf.md("；".join(metadata.get("authors", [])) or "待确认"),
                 "- 原文：" + (wpf.markdown_link("出版社／论文页面", metadata.get("publisher_url", "")) or "未查到"),
                 "- 正文获取状态：" + wpf.md(paper.get("download", {}).get("status", "not_requested"))]
        if bibliography["author_details"]:
            rows += ["", "| 作者 | 发表时所属机构 | 作者角色 |", "|---|---|---|"]
            for author in bibliography["author_details"]:
                rows.append(f"| {wpf.md(author['name'])} | {wpf.md('；'.join(author.get('affiliations', [])) or '未报告／待核实')} | {wpf.md('；'.join(author.get('roles', [])))} |")
        else:
            rows += ["- 作者所属机构：未查到／待核实"]
        if bibliography.get("evidence"):
            rows += ["", "书目信息依据：" + evidence_links(bibliography["evidence"])]
        if impact.get("value") is not None:
            rows += ["", f"期刊影响因子（JIF）：**{wpf.md(impact['value'])}（{impact['metric_year']}）**；查询日期：{wpf.md(impact['checked_at'])}。" + wpf.markdown_link("指标来源", impact["source_url"])]
        else:
            rows += ["", "期刊影响因子（JIF）：未查到／待核实；不从推文标题推定数值或年份。"]
        rows += ["", "### 摘要中文翻译", "", abstract["translation_zh"] or ("已取得摘要，待翻译。" if abstract["original"] else "原始摘要未取得，待补充。")]
        if abstract.get("source_url"):
            rows += ["", wpf.markdown_link("原始摘要来源", abstract["source_url"])]
        graph = research["connected_papers"]
        graph_labels = {"search_only": "仅检索入口；尚未核验图谱", "provided": "用户提供的图谱链接；待核验", "verified": "已核验起点论文的图谱", "unavailable": "图谱暂不可用"}
        rows += ["", "### 关联文献入口", "", "- 状态：" + graph_labels[graph["status"]]]
        if graph.get("url"):
            rows += ["- " + wpf.markdown_link("Connected Papers 图谱", graph["url"])]
        if graph["search_url"]:
            rows += ["- " + wpf.markdown_link("Connected Papers 检索入口", graph["search_url"])]
        rows += ["- " + wpf.md(graph["note"]), "", "### 复现准备清单", "", "| 条件 | 检查状态 | 已核实资源数 | 缺失信息／下一步 |", "|---|---|---|---|"]
        article_type = bibliography.get("article_type", "").casefold()
        if any(label in article_type for label in ["review", "perspective", "综述", "观点"]):
            rows += ["| 范围说明 | 综述／观点类文章 | — | 本文资源与引用研究资源分别记录；逐篇复现需选择原始研究。 |"]
        for kind, label in KINDS.items():
            check = research["checks"][kind]
            count = sum(resource["kind"] == kind and resource["status"] == "verified" for resource in research["resources"])
            status = check["status"]
            effective = "已核实部分资源；类别检查尚未完成" if status == "not_checked" and count else STATUSES[status]
            reason = check.get("reason") or ("继续核对可用性声明、方法或附件" if status in {"not_checked", "needs_review"} else "")
            rows.append(f"| {label} | {effective} | {count} | {wpf.md(reason)} |")
            category_resources = [resource for resource in research["resources"] if resource["kind"] == kind]
            checklist.append([paper["id"], metadata.get("doi", ""), label, effective, count, reason,
                              "；".join(r.get("name", "") for r in category_resources),
                              "；".join(r.get("url", "") for r in category_resources),
                              "；".join(r.get("version") or r.get("accession", "") for r in category_resources),
                              "；".join(r.get("scope", "") for r in category_resources),
                              "；".join(e["source_url"] + " · " + e["location"] for r in category_resources for e in r.get("evidence", []))])
            if check.get("evidence"):
                rows += [f"| {label}依据 | | | {evidence_links(check['evidence'])} |"]
        rows += ["", "### 资源明细", ""]
        if not research["resources"]:
            rows += ["尚未记录资源；这不表示作者没有提供资源。"]
        for index, resource in enumerate(research["resources"], 1):
            scopes = {"author_provided": "本文作者提供", "third_party": "第三方实现", "cited_work": "引用研究的资源", "dependency": "所用通用依赖／设备", "not_assessed": "归属待核验"}
            rows += [f"#### {index}. {wpf.md(resource.get('name') or '待核实资源')}（{KINDS[resource['kind']]}）", "",
                     "- 记录状态：" + STATUSES[resource["status"]] + "；访问：" + resource["access"],
                     "- 归属：" + scopes[resource["scope"]],
                     "- 所属论文 DOI：" + (wpf.markdown_link(wpf.md(resource.get("owner_doi")), "https://doi.org/" + resource["owner_doi"]) if resource.get("owner_doi") else (wpf.doi_display(paper) if resource["scope"] in {"author_provided", "dependency"} else "未查到／待确认"))]
            if resource.get("owner_arxiv_id"):
                rows += ["- 所属论文 arXiv：" + wpf.md(resource["owner_arxiv_id"])]
            if resource.get("url"):
                rows += ["- 链接：" + wpf.markdown_link("资源入口", resource["url"])]
            for key, label in [("accession", "登录号"), ("version", "版本／提交"), ("details", "原文报告的要求"), ("note", "说明")]:
                if resource.get(key):
                    rows += ["- " + label + "：" + wpf.md(resource[key])]
            rows += ["- 证据：" + (evidence_links(resource.get("evidence", [])) or "待补充"), ""]
        rows += ["### 已检查的来源与范围", ""]
        if not research["coverage"]:
            rows += ["尚未登记查阅范围；不能据此作出资源不存在的结论。"]
        for source in research["coverage"]:
            rows += ["- " + wpf.markdown_link(wpf.md(source["scope"]), source["source_url"]) + "；" + wpf.md(source["checked_at"]) + "；" + wpf.md(source.get("note"))]
        for note in research["notes"]:
            rows += ["- " + wpf.md(note)]
        rows += [""]
    outdir = Path(outdir)
    (outdir / "research-report.md").write_text("\n".join(rows), encoding="utf-8")
    with (outdir / "reproduction-checklist.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["paper_id", "doi", "条件", "检查状态", "已核实资源数", "缺失信息或下一步", "资源名称", "资源链接", "版本或登录号", "资源归属", "证据位置"])
        # Keep arbitrary source text as text when opened in spreadsheet applications.
        writer.writerows([["'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value for value in row] for row in checklist])


def prepare_report(manifest, outdir, details=None):
    result = copy.deepcopy(manifest)
    if details is not None:
        if details.get("schema_version") != 1 or not isinstance(details.get("papers"), list):
            raise ValueError("Details require schema_version=1 and papers list")
        seen = set()
        by_id = {paper["id"]: paper for paper in result["papers"]}
        for entry in details["papers"]:
            identifier = entry.get("id")
            if identifier in seen or identifier not in by_id or not isinstance(entry.get("research"), dict):
                raise ValueError("Details need unique matching paper IDs and research objects")
            seen.add(identifier)
            paper = by_id[identifier]
            metadata = paper.get("metadata", {})
            doi = wpf.normalize_doi(metadata.get("doi", ""))
            if doi and wpf.normalize_doi(entry.get("doi", "")) != doi:
                raise ValueError("Details DOI must match this paper's metadata")
            if not doi and (not metadata.get("arxiv_id") or entry.get("arxiv_id") != metadata["arxiv_id"]):
                raise ValueError("Without DOI, bind details to the exact arXiv ID/version")
            paper["research"] = merge(paper.get("research", {}), entry["research"])
    for paper in result["papers"]:
        paper["research"] = normalize_research(paper)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    wpf.export(result, outdir)
    wpf.write_json(outdir / "research-details.json", {"schema_version": 1, "papers": [{"id": p["id"], "doi": p.get("metadata", {}).get("doi", ""), "arxiv_id": p.get("metadata", {}).get("arxiv_id", ""), "research": p["research"]} for p in result["papers"]]})
    render_report(result, outdir)
    return result
