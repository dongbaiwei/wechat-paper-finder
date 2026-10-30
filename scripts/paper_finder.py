#!/usr/bin/env python3
"""Evidence-preserving paper lookup for an agent-assisted WeChat skill."""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
from html.parser import HTMLParser
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

VERSION = "0.3.0"
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s<>\"`\u201c\u201d\u3002\uFF0C\uFF1B]+", re.I)
ARXIV_RE = re.compile(r"(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)([a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?|\d{4}\.\d{4,5}(?:v\d+)?)", re.I)
ROLES = {"main", "background", "related", "unknown"}


class PaperError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())


def norm(value):
    return "".join(c for c in clean(value).casefold() if c.isalnum())


def normalize_doi(value):
    value = urllib.parse.unquote(html.unescape(str(value))).strip()
    match = DOI_RE.search(value)
    if not match:
        return ""
    doi = match.group().split("](", 1)[0].rstrip(".,;:!?，。；：！？'`）】")
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1]
    while doi.endswith("]") and doi.count("]") > doi.count("["):
        doi = doi[:-1]
    while doi.endswith("}") and doi.count("}") > doi.count("{"):
        doi = doi[:-1]
    return doi.casefold()


def public_url(url, check_dns=False):
    """Restrict all requests, including redirects, to public HTTP(S) destinations."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise PaperError("Only absolute HTTP(S) URLs are supported")
    if parts.username or parts.password:
        raise PaperError("Credentials in URLs are not supported")
    host = parts.hostname.rstrip(".").casefold()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise PaperError("Local/private URLs are not supported")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = []
        if check_dns:
            try:
                addresses = [ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)]
            except OSError as exc:
                raise PaperError("DNS lookup failed") from exc
    if any(not address.is_global for address in addresses):
        raise PaperError("Local/private URLs are not supported")
    return urllib.parse.urlunsplit(parts._replace(fragment=""))


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl, check_dns=True)
        if req.full_url.startswith("https:") and newurl.startswith("http:"):
            raise PaperError("HTTPS downgrade redirect refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, cache=None, email="", timeout=25):
        self.cache = Path(cache) if cache else None
        self.email = email
        self.timeout = timeout
        self.opener = urllib.request.build_opener(PublicRedirect())
        self.last_request = {}

    def fetch(self, url, limit=8 * 1024 * 1024, accept="application/json", use_cache=True):
        url = public_url(url, check_dns=True)
        cache_file = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".json") if self.cache and use_cache else None
        if cache_file and cache_file.exists() and time.time() - cache_file.stat().st_mtime < 86400:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            import base64
            return base64.b64decode(cached["data"]), cached["type"], cached["url"]
        host = urllib.parse.urlsplit(url).hostname
        interval = 3.1 if host == "export.arxiv.org" else 0.35
        delay = interval - (time.monotonic() - self.last_request.get(host, 0))
        if delay > 0:
            time.sleep(delay)
        headers = {"User-Agent": f"wechat-paper-finder/{VERSION}" + (f" (mailto:{self.email})" if self.email else ""), "Accept": accept}
        for attempt in range(3):
            try:
                self.last_request[host] = time.monotonic()
                with self.opener.open(urllib.request.Request(url, headers=headers), timeout=self.timeout) as response:
                    length = response.headers.get("Content-Length", "0")
                    if length.isdigit() and int(length) > limit:
                        raise PaperError("Response exceeds configured size limit")
                    data = response.read(limit + 1)
                    if len(data) > limit:
                        raise PaperError("Response exceeds configured size limit")
                    content_type = response.headers.get("Content-Type", "")
                    final_url = response.geturl()
                if cache_file:
                    import base64
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps({"data": base64.b64encode(data).decode(), "type": content_type, "url": final_url}), encoding="utf-8")
                return data, content_type, final_url
            except urllib.error.HTTPError as exc:
                if exc.code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(min(4, 1 + attempt * 2))
                    continue
                raise PaperError(f"HTTP {exc.code} from {host}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise PaperError(f"Network request failed for {host}: {type(exc).__name__}") from exc
        raise PaperError("Request failed")

    def json(self, url):
        data, _, _ = self.fetch(url)
        try:
            return json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise PaperError("Expected JSON but received another format") from exc


class ArticleParser(HTMLParser):
    def __init__(self, base_url="", content_only=False):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.content_only = content_only
        self.depth = 0
        self.root_depth = None
        self.suppress = 0
        self.parts = []
        self.links = []
        self.images = []
        self.metadata = {}
        self.anchor = None
        self.identities = []

    def active(self):
        return not self.content_only or self.root_depth is not None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        void = tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
        if not void:
            self.depth += 1
        if attrs.get("id") == "js_content":
            self.root_depth = self.depth
        if tag in {"script", "style", "noscript"}:
            self.suppress += 1
        identity_keys = {"js_name": "account_name", "publish_time": "published_at", "activity-name": "article_title"}
        if attrs.get("id") in identity_keys:
            self.identities.append({"depth": self.depth, "key": identity_keys[attrs["id"]], "parts": []})
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name", "")
            if key in {"og:title", "citation_title", "citation_doi", "citation_pdf_url"}:
                self.metadata[key] = attrs.get("content", "")
        if not self.active() or self.suppress:
            return
        if tag in {"p", "div", "section", "br", "h1", "h2", "h3", "li", "tr"}:
            self.parts.append("\n")
        if tag == "a":
            href = attrs.get("href") or attrs.get("data-url", "")
            if href and not href.startswith(("javascript:", "#")):
                self.anchor = {"url": urllib.parse.urljoin(self.base, href), "text": ""}
                self.links.append(self.anchor)
        if tag == "img":
            src = attrs.get("data-src") or attrs.get("src", "")
            if src and not src.startswith("data:"):
                self.images.append({"url": urllib.parse.urljoin(self.base, src), "alt": attrs.get("alt", "")})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for capture in list(self.identities):
            if capture["depth"] == self.depth:
                self.metadata[capture["key"]] = clean("".join(capture["parts"]))
                self.identities.remove(capture)
        if self.active() and not self.suppress and tag in {"p", "div", "section", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")
        if tag == "a":
            self.anchor = None
        if tag in {"script", "style", "noscript"}:
            self.suppress = max(0, self.suppress - 1)
        if self.root_depth == self.depth and tag not in {"br", "img", "meta", "link", "hr", "input", "source"}:
            self.root_depth = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if not self.suppress:
            for capture in self.identities:
                capture["parts"].append(data)
        if self.active() and not self.suppress:
            self.parts.append(data)
            if self.anchor is not None:
                self.anchor["text"] += data

    def text(self):
        return "\n".join(line for line in (clean(x) for x in "".join(self.parts).splitlines()) if line)


def parse_html(value, base_url=""):
    only = bool(re.search(r"\bid\s*=\s*['\"]js_content['\"]", value, re.I))
    parser = ArticleParser(base_url, only)
    parser.feed(value)
    parser.close()
    return parser


def discovery_plan(share):
    """Build reproducible search queries; an agent/search tool executes them."""
    if "cards" in share:
        if not isinstance(share["cards"], list) or not share["cards"]:
            raise PaperError("cards must be a nonempty list")
        plans, seen = [], set()
        for index, card in enumerate(share["cards"], 1):
            if not isinstance(card, dict) or "cards" in card:
                raise PaperError("Each card must be a single share-card object")
            card = copy.deepcopy(card)
            card_id = card.setdefault("card_id", f"card_{index:03d}")
            if not isinstance(card_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", card_id) or card_id in seen:
                raise PaperError("Card IDs must be unique alphanumeric identifiers")
            seen.add(card_id)
            if "vision_provenance" in share:
                card.setdefault("vision_provenance", share["vision_provenance"])
            plans.append(discovery_plan(card))
        return {"schema_version": 1, "task": "share_card_batch", "created_at": now(), "cards": plans, "search_queries": [query for plan in plans for query in plan["search_queries"]], "status": "search_needed", "card_count": len(plans), "notes": ["Discover and verify each card independently; one post may contain multiple papers."]}
    title = clean(share.get("visible_title", ""))
    account = clean(share.get("account_name", ""))
    snippet = clean(share.get("visible_snippet", ""))
    fragments = [x.strip() for x in re.split(r"\.{2,}|…+", title) if len(norm(x)) >= 4]
    longest = max(fragments, key=len) if fragments else title
    if not title and not (account and snippet) and not share.get("article_url"):
        raise PaperError("Insufficient share-card clues: need a visible title, article URL, or account plus snippet")
    queries = []
    if longest:
        queries.append(f'site:mp.weixin.qq.com "{longest}"' + (f' "{account}"' if account else ""))
        queries.append(f'"{longest}"' + (f' "{account}"' if account else "") + " 微信公众号")
        if account:
            queries.append(f'site:mp.weixin.qq.com "{longest}"')
    if account and snippet:
        queries.append(f'"{account}" "{snippet[:100]}"')
    return {"schema_version": 1, "task": "share_card_discovery", "created_at": now(), "share_card": share, "search_queries": list(dict.fromkeys(queries)), "candidate_articles": [], "status": "search_needed", "notes": ["Queries are a plan; no search or article verification has happened yet.", "Chat sender/time are not account name/publication date.", "Prefer official WeChat URLs; verify title and account against the actual page before paper lookup."]}


def choose_discovery(discovery, card_id=None):
    if "cards" not in discovery:
        return discovery
    if not card_id:
        raise PaperError("A batch discovery requires --card to bind this article to one share card")
    selected = next((p for p in discovery["cards"] if p.get("share_card", {}).get("card_id") == card_id), None)
    if selected is None:
        raise PaperError("Card ID not found in discovery batch")
    return selected


def compare_article(discovery, metadata, text, url):
    share = discovery["share_card"]
    visible = clean(share.get("visible_title", ""))
    title = metadata.get("article_title") or metadata.get("og:title", "")
    account = share.get("account_name", "")
    fragments = [norm(x) for x in re.split(r"\.{2,}|…+", visible) if len(norm(x)) >= 4]
    truncated = share.get("title_truncated", False) or bool(re.search(r"\.{2,}|…", visible))
    title_match = bool(fragments and norm(title) and (all(x in norm(title) for x in fragments) if truncated else norm(visible) == norm(title)))
    account_match = bool(account and metadata.get("account_name") and norm(account) == norm(metadata["account_name"]))
    account_conflict = bool(account and metadata.get("account_name") and not account_match)
    title_conflict = bool(visible and title and not title_match)
    snippet = norm(share.get("visible_snippet", ""))
    snippet_match = bool(len(snippet) >= 12 and snippet in norm(text))
    direct_match = bool(share.get("article_url") and share["article_url"].rstrip("/") == url.rstrip("/"))
    sufficient_title = len(norm(visible)) >= (10 if truncated else 6)
    verified = not account_conflict and not title_conflict and (direct_match or (title_match and sufficient_title and (account_match or snippet_match)))
    return {"status": "verified" if verified else "needs_review", "checked_at": now(), "article_url": url, "visible_title": visible, "resolved_title": title, "resolved_account": metadata.get("account_name", ""), "title_agrees": title_match, "title_conflict": title_conflict, "account_agrees": account_match, "account_conflict": account_conflict, "snippet_agrees": snippet_match, "direct_url_agrees": direct_match, "note": "Source identity is separate from paper identity. Review missing/conflicting clues before using this page as the original post."}


def new_paper(index, **kwargs):
    return {"id": f"paper_{index:03d}", "role": "unknown", "raw_title": "", "doi": "", "arxiv_id": "", "author_hint": "", "year_hint": None, "venue_hint": "", "evidence": [], **kwargs}


def extract_document(text, source="", links=None, images=None, metadata=None):
    links, images, metadata = links or [], images or [], metadata or {}
    papers, seen = [], set()
    searchable = text + "\n" + "\n".join(x["url"] for x in links)
    if metadata.get("citation_doi"):
        searchable += "\n" + metadata["citation_doi"]
    for match in DOI_RE.finditer(urllib.parse.unquote(searchable)):
        doi = normalize_doi(match.group())
        if doi and doi not in seen:
            seen.add(doi)
            start = searchable.casefold().find(match.group().casefold())
            snippet = searchable[max(0, start - 160):start + len(match.group()) + 160]
            papers.append(new_paper(len(papers) + 1, doi=doi, evidence=[{"kind": "literal_doi", "quote": snippet, "source": source}]))
    for match in ARXIV_RE.finditer(searchable):
        identifier = match.group(1)
        key = "arxiv:" + identifier.casefold()
        if key not in seen:
            seen.add(key)
            papers.append(new_paper(len(papers) + 1, arxiv_id=identifier, evidence=[{"kind": "literal_arxiv", "quote": match.group(), "source": source}]))
    # Explicit labels are useful hints; semantic title inference belongs to the agent.
    for match in re.finditer(r"(?im)^\s*(?:论文题目|论文标题|原文标题|英文标题|paper title|title)\s*[:：]\s*(.{8,400})$", text):
        title = match.group(1).strip().strip('“”"')
        papers.append(new_paper(len(papers) + 1, raw_title=title, role="main", evidence=[{"kind": "title_label", "quote": match.group(), "source": source}]))
    return {"schema_version": 1, "created_at": now(), "source": source, "document": {"text": text, "links": links, "images": images, "metadata": metadata}, "papers": papers, "warnings": ["Classify main/background/related and merge title/DOI hints belonging to the same paper before resolving."]}


def crossref_record(item):
    def first(value):
        return value[0] if isinstance(value, list) and value else ""
    date = item.get("published", item.get("published-online", item.get("issued", {}))).get("date-parts", [[]])
    doi = normalize_doi(item.get("DOI", ""))
    authors = [clean(" ".join(filter(None, [a.get("given"), a.get("family")]))) or a.get("name", "") for a in item.get("author", [])]
    author_details = [{"name": name, "affiliations": [clean(a.get("name", "")) for a in author.get("affiliation", []) if a.get("name")], "orcid": author.get("ORCID", ""), "roles": []} for name, author in zip(authors, item.get("author", []))]
    abstract = parse_html(item.get("abstract", "")).text() if item.get("abstract") else ""
    return {"doi": doi, "title": clean(first(item.get("title", []))), "authors": authors, "author_details": author_details, "abstract": abstract, "year": date[0][0] if date and date[0] else None, "published_date_parts": date[0] if date else [], "venue": clean(first(item.get("container-title", []))), "issn": sorted(item.get("ISSN", [])), "publisher": item.get("publisher", ""), "type": item.get("type", ""), "version": "preprint" if item.get("type") == "posted-content" else "published_record", "doi_url": f"https://doi.org/{doi}" if doi else "", "publisher_url": item.get("resource", {}).get("primary", {}).get("URL") or item.get("URL", ""), "metadata_source": "Crossref", "metadata_url": "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")}


def title_similarity(a, b):
    a, b = norm(a), norm(b)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def assess(paper, candidate, direct_id=False):
    reasons, conflicts = [], []
    raw_title = paper.get("raw_title", "")
    english_hint = bool(re.search(r"[a-zA-Z]{4}", raw_title)) and not re.search(r"[\u4e00-\u9fff]", raw_title)
    similarity = title_similarity(raw_title, candidate.get("title", ""))
    corroboration = 0
    if paper.get("year_hint") and candidate.get("year"):
        if abs(int(paper["year_hint"]) - int(candidate["year"])) <= 1:
            reasons.append("Year agrees (online/print dates may differ by one year)")
            corroboration += 1
        else:
            conflicts.append("Publication year conflicts")
    if paper.get("author_hint"):
        hint = norm(paper["author_hint"])
        if hint and any(hint in norm(a) for a in candidate.get("authors", [])):
            reasons.append("Author hint agrees")
            corroboration += 1
        elif candidate.get("authors"):
            conflicts.append("Author hint could not be corroborated")
    if paper.get("venue_hint"):
        if norm(paper["venue_hint"]) in norm(candidate.get("venue", "")):
            reasons.append("Venue hint agrees")
            corroboration += 1
        else:
            conflicts.append("Venue hint could not be corroborated")
    if english_hint and similarity < 0.80:
        conflicts.append("English title conflicts")
    if direct_id:
        reasons.append("Supplied identifier resolves to this metadata record; its association with the source must be checked separately")
    else:
        reasons.append(f"Title similarity: {similarity:.3f}; ranking metric, not probability")
    status = "verified" if (direct_id or (similarity >= 0.96 and corroboration > 0)) and not conflicts else "needs_review"
    return {"status": status, "reasons": reasons, "conflicts": conflicts, "title_similarity": round(similarity, 4)}


def arxiv_record(identifier, client):
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({"id_list": identifier})
    data, _, _ = client.fetch(url, accept="application/atom+xml")
    root = ET.fromstring(data)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entry = root.find("a:entry", ns)
    if entry is None:
        raise PaperError("arXiv record not found")
    record_id = entry.findtext("a:id", "", ns)
    if "/abs/" not in record_id:
        raise PaperError("arXiv returned an error entry")
    resolved = record_id.split("/abs/")[-1]
    if re.sub(r"v\d+$", "", resolved).casefold() != re.sub(r"v\d+$", "", identifier).casefold() or (re.search(r"v\d+$", identifier) and resolved.casefold() != identifier.casefold()):
        raise PaperError("arXiv identifier/version mismatch")
    title = clean(entry.findtext("a:title", "", ns))
    doi = normalize_doi(entry.findtext("{http://arxiv.org/schemas/atom}doi", ""))
    return {"arxiv_id": resolved, "doi": doi, "title": title, "abstract": clean(entry.findtext("a:summary", "", ns)), "authors": [clean(a.findtext("a:name", "", ns)) for a in entry.findall("a:author", ns)], "year": int(entry.findtext("a:published", "0000", ns)[:4]), "venue": "arXiv", "version": "preprint", "publisher_url": "https://arxiv.org/abs/" + resolved, "doi_url": "https://doi.org/" + doi if doi else "", "metadata_source": "arXiv", "metadata_url": url, "fulltext_url": "https://arxiv.org/pdf/" + resolved, "access_basis": "open_access", "fulltext_source": "arXiv"}


def resolve_papers(intake, client):
    result = copy.deepcopy(intake)
    result["resolved_at"] = now()
    seen = {}
    for paper in result.get("papers", []):
        paper["role"] = paper.get("role", "unknown")
        if paper["role"] not in ROLES:
            raise PaperError("Invalid paper role")
        doi = normalize_doi(paper.get("doi", ""))
        arxiv_id = paper.get("arxiv_id", "")
        key = ("arxiv:" + arxiv_id.casefold()) if arxiv_id else doi
        if key and key in seen:
            paper["duplicate_of"] = seen[key]
            paper["verification"] = {"status": "duplicate", "reasons": ["Same identifier; evidence retained in this row"]}
            continue
        if key:
            seen[key] = paper["id"]
        try:
            if arxiv_id:
                metadata = arxiv_record(arxiv_id, client)
                verification = assess(paper, metadata, True)
            elif doi:
                record = client.json("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe=""))["message"]
                metadata = crossref_record(record)
                if metadata["doi"] != doi:
                    raise PaperError("Identifier returned by Crossref differs from requested DOI")
                verification = assess(paper, metadata, True)
            elif paper.get("raw_title"):
                query = " ".join(str(paper.get(field) or "") for field in ["raw_title", "author_hint", "year_hint", "venue_hint"])
                url = "https://api.crossref.org/works?" + urllib.parse.urlencode({"query.bibliographic": query, "rows": 5})
                records = [crossref_record(x) for x in client.json(url)["message"]["items"]]
                records.sort(key=lambda x: title_similarity(paper["raw_title"], x["title"]), reverse=True)
                paper["candidates"] = records[:3]
                if not records:
                    raise PaperError("No metadata candidates found")
                metadata = records[0]
                verification = assess(paper, metadata)
                if len(records) > 1 and title_similarity(paper["raw_title"], records[1]["title"]) >= 0.93:
                    verification["status"] = "needs_review"
                    verification["reasons"].append("Multiple similarly titled records; compare versions and authors")
            else:
                raise PaperError("No usable identifier or title; agent must add evidence-based search hints")
            paper["metadata"] = metadata
            paper["verification"] = {**verification, "checked_at": now(), "evidence_url": metadata.get("metadata_url", "")}
            paper.pop("error", None)
        except (PaperError, ValueError, KeyError, ET.ParseError) as exc:
            paper["verification"] = {"status": "unresolved", "reasons": [str(exc)]}
            paper["error"] = str(exc)
    return result


def oa_locations(metadata, client, email=""):
    if metadata.get("fulltext_url") and metadata.get("access_basis") in {"open_access", "user_authorized"}:
        return [{"url": metadata["fulltext_url"], "source": metadata.get("fulltext_source", "explicit"), "version": metadata.get("version", "unknown"), "license": metadata.get("license"), "access_basis": metadata["access_basis"]}], []
    doi = metadata.get("doi")
    if not doi:
        return [], ["No DOI for OA lookup"]
    locations, errors = [], []
    # Europe PMC exposes explicit OA PDF links for its life-science subset.
    try:
        query = urllib.parse.urlencode({"query": f'DOI:"{doi}"', "format": "json", "resultType": "core", "pageSize": 5})
        result = client.json("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + query)
        for item in result.get("resultList", {}).get("result", []):
            if normalize_doi(item.get("doi", "")) != doi or item.get("isOpenAccess", "").upper() != "Y":
                continue
            for link in item.get("fullTextUrlList", {}).get("fullTextUrl", []):
                if link.get("documentStyle", "").casefold() == "pdf" and link.get("availability", "").casefold() == "open access" and link.get("url"):
                    locations.append({"url": link["url"], "source": "Europe PMC OA", "version": "unknown", "license": None, "access_basis": "open_access"})
    except PaperError as exc:
        errors.append(str(exc))
    if email:
        try:
            result = client.json("https://api.unpaywall.org/v2/" + urllib.parse.quote(doi, safe="") + "?" + urllib.parse.urlencode({"email": email}))
            if normalize_doi(result.get("doi", "")) != doi:
                raise PaperError("Unpaywall DOI mismatch")
            ordered = [result.get("best_oa_location")] + result.get("oa_locations", [])
            for location in ordered:
                if location and location.get("url_for_pdf"):
                    locations.append({"url": location["url_for_pdf"], "source": "Unpaywall:" + str(location.get("host_type", "unknown")), "version": location.get("version", "unknown"), "license": location.get("license"), "access_basis": "open_access"})
        except PaperError as exc:
            errors.append(str(exc))
    else:
        errors.append("Unpaywall skipped: set UNPAYWALL_EMAIL to enable cross-disciplinary OA lookup")
    unique = {location["url"]: location for location in reversed(locations)}
    return list(reversed(list(unique.values()))), errors


def safe_name(value, max_length=100):
    value = clean(value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" ._")[:max_length].rstrip(" .")
    if not value:
        value = "paper"
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        value = "_" + value
    return value


def title_in_text(title, text):
    needle, haystack = norm(title), norm(text)
    if len(needle) < 12:
        return False
    if needle in haystack:
        return True
    words = clean(title).casefold().split()
    text_words = clean(text).casefold().split()
    if len(words) < 5:
        return False
    width = len(words)
    for start in range(min(len(text_words), 1400)):
        candidate = " ".join(text_words[start:start + width])
        if title_similarity(title, candidate) >= 0.94:
            return True
    return False


def validate_pdf(data, metadata):
    if not data.lstrip().startswith(b"%PDF-"):
        raise PaperError("not_pdf: server returned HTML or another file type")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PaperError("pdf_parser_missing: install this project with the [pdf] extra") from exc
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise PaperError("encrypted_pdf: cannot verify article identity")
        count = len(reader.pages)
        if not count:
            raise PaperError("empty_pdf")
        first = reader.pages[0].extract_text() or ""
        text = first + "\n" + "\n".join(reader.pages[i].extract_text() or "" for i in range(1, min(count, 3)))
    except PaperError:
        raise
    except Exception as exc:
        raise PaperError("invalid_pdf: parsing failed") from exc
    # A DOI in a reference list is insufficient: require the expected title up front.
    frontmatter = re.split(r"(?im)^\s*(?:abstract|references|bibliography|1[.\s]+introduction)\b", first[:16000], maxsplit=1)[0]
    if not metadata.get("title") or not title_in_text(metadata["title"], frontmatter):
        raise PaperError("identity_unverified: expected title not found on first page; OCR/manual check needed")
    doi = normalize_doi(metadata.get("doi", ""))
    return {"pages": count, "identity_basis": "first_page_title", "doi_present": bool(doi and norm(doi) in norm(text)), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def download_papers(manifest, outdir, client, email="", include_related=False, max_mb=80):
    result = copy.deepcopy(manifest)
    pdfdir = Path(outdir) / "PDFs"
    for paper in result.get("papers", []):
        if result.get("source_discovery") and result.get("source_verification", {}).get("status") != "verified":
            paper["download"] = {"status": "skipped_source_unverified", "reason": "Confirm the original article identity before automatic full-text download"}
            continue
        if paper.get("verification", {}).get("status") != "verified":
            paper["download"] = {"status": "skipped_unverified"}
            continue
        if paper.get("role") != "main" and not (include_related and paper.get("role") in {"related", "background"}):
            paper["download"] = {"status": "skipped_role", "reason": "Classify role=main, or explicitly include related/background papers"}
            continue
        metadata = paper["metadata"]
        identity = metadata.get("arxiv_id") or metadata.get("doi") or metadata["title"]
        suffix = hashlib.sha256(identity.encode()).hexdigest()[:8]
        author = metadata.get("authors", ["Unknown"])[0] if metadata.get("authors") else "Unknown"
        filename = safe_name(f"{author.split()[-1]}_{metadata.get('year') or 'nd'}_{metadata['title']}", 110) + "_" + suffix + ".pdf"
        target = pdfdir / filename
        if target.exists():
            try:
                validation = validate_pdf(target.read_bytes(), metadata)
                paper["download"] = {**paper.get("download", {}), "status": "already_present", "path": "PDFs/" + filename, "checked_at": now(), **validation}
                continue
            except PaperError:
                # Preserve an existing file for review; do not overwrite it.
                paper["download"] = {"status": "existing_file_needs_review", "path": "PDFs/" + filename}
                continue
        locations, errors = oa_locations(metadata, client, email)
        paper["fulltext_locations"] = locations
        attempts = []
        for location in locations[:5]:
            try:
                data, content_type, final_url = client.fetch(location["url"], limit=max_mb * 1024 * 1024, accept="application/pdf", use_cache=False)
                validation = validate_pdf(data, metadata)
                pdfdir.mkdir(parents=True, exist_ok=True)
                part = target.with_suffix(".pdf.part")
                try:
                    part.write_bytes(data)
                    part.replace(target)
                finally:
                    part.unlink(missing_ok=True)
                paper["download"] = {"status": "downloaded", "path": "PDFs/" + filename, "source_url": location["url"], "final_url": final_url, "content_type": content_type, "source": location["source"], "version": location["version"], "license": location.get("license"), "access_basis": location["access_basis"], "checked_at": now(), **validation, "attempts": attempts, "lookup_notes": errors}
                break
            except PaperError as exc:
                attempts.append({"url": location["url"], "error": str(exc)})
        else:
            paper["download"] = {"status": "download_failed" if locations else "no_oa_pdf_found", "attempts": attempts, "lookup_notes": errors, "checked_at": now()}
    return result


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def collect_manifests(paths, outdir):
    """Summarize many posts without losing per-post evidence or version identity."""
    outdir = Path(outdir).resolve()
    posts, work_map = [], {}
    rows = ["# 多推文论文清单", "", "每张分享卡片独立核验；同一推文可以对应零篇、一篇或多篇论文。", "", "| 推文 | 题名／线索 | DOI | 原文 | 推文核验 | 论文核验 | 全文 |", "|---|---|---|---|---|---|---|"]
    for index, path in enumerate(paths, 1):
        path = Path(path).resolve()
        data = read_json(path)
        post_id = f"post_{index:03d}"
        source_status = data.get("source_verification", {}).get("status", "not_applicable")
        source_title = data.get("source_verification", {}).get("resolved_title") or data.get("source_verification", {}).get("visible_title") or data.get("document", {}).get("metadata", {}).get("og:title") or path.parent.name
        post = {"id": post_id, "manifest_path": str(path), "source": data.get("source", ""), "title": source_title, "source_verification": data.get("source_verification"), "papers": data["papers"]}
        posts.append(post)
        if not data["papers"]:
            rows.append(f"| {md(post_id)} | {md(source_title)}（尚未识别论文） | 未查到／待确认 | | {md(source_status)} | unresolved | |")
        for paper in data["papers"]:
            metadata = paper.get("metadata", {})
            identity = ("arxiv:" + metadata["arxiv_id"]) if metadata.get("arxiv_id") else normalize_doi(metadata.get("doi", ""))
            if identity and paper.get("verification", {}).get("status") == "verified":
                work_map.setdefault(identity, []).append({"post_id": post_id, "paper_id": paper["id"]})
            title = metadata.get("title") or paper.get("raw_title") or paper.get("doi") or paper.get("arxiv_id")
            link = markdown_link("原文", metadata.get("publisher_url") or metadata.get("doi_url", ""))
            download = paper.get("download", {})
            fulltext = md(download.get("status", "not_requested"))
            relative = download.get("path", "")
            if relative.startswith("PDFs/") and ".." not in Path(relative).parts:
                target = (path.parent / relative).resolve()
                if target.is_relative_to(path.parent) and target.is_file() and download.get("status") in {"downloaded", "already_present"}:
                    fulltext = f"[PDF]({urllib.parse.quote(Path(os.path.relpath(target, outdir)).as_posix())})"
            rows.append(f"| {md(post_id)} / {md(paper['id'])} | {md(title)} | {doi_display(paper)} | {link} | {md(source_status)} | {md(paper.get('verification', {}).get('status', 'unresolved'))} | {fulltext} |")
    collection = {"schema_version": 1, "created_at": now(), "posts": posts, "unique_verified_works": [{"identifier": key, "occurrences": occurrences} for key, occurrences in work_map.items()]}
    write_json(outdir / "collection.json", collection)
    rows.extend(["", f"推文数：{len(posts)}；论文条目数：{sum(len(p['papers']) for p in posts)}；唯一已核验作品数：{len(work_map)}。", "", "完整证据和候选保留在各推文的 papers.json 中；同一 DOI 的多个来源保留关联，预印本及版本单独记录。", ""])
    (outdir / "report.md").write_text("\n".join(rows), encoding="utf-8")
    return collection


def read_json(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1 or not isinstance(data.get("papers"), list):
        raise PaperError("Expected a schema_version=1 document with a papers list")
    ids = [p.get("id") for p in data["papers"]]
    if not all(isinstance(i, str) and re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in ids) or len(ids) != len(set(ids)):
        raise PaperError("Paper IDs must be unique nonempty alphanumeric identifiers")
    return data


def md(value):
    return clean(value).replace("|", "\\|").replace("[", "\\[").replace("]", "\\]").replace("<", "&lt;").replace(">", "&gt;")


def markdown_link(label, url):
    try:
        url = public_url(url)
    except (PaperError, ValueError):
        return ""
    return f"[{label}]({urllib.parse.quote(url, safe=':/?=&%#+,;@~_-')})"


def bib_escape(value):
    mapping = {"\\": "\\textbackslash{}", "{": "\\{", "}": "\\}", "&": "\\&", "%": "\\%", "#": "\\#", "_": "\\_", "$": "\\$"}
    return "".join(mapping.get(c, c) for c in clean(value))


def doi_display(paper):
    """Keep the full DOI visible, distinguishing metadata from unverified hints."""
    metadata = paper.get("metadata", {})
    metadata_doi = normalize_doi(metadata.get("doi") or metadata.get("doi_url", ""))
    doi = metadata_doi or normalize_doi(paper.get("doi", ""))
    if not doi:
        return "未查到／待确认"
    label = markdown_link(md(doi), "https://doi.org/" + doi)
    verified = metadata_doi and paper.get("verification", {}).get("status") == "verified"
    return label if verified else label + "（待核验）"


def export(manifest, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    write_json(outdir / "papers.json", manifest)
    rows = ["# 论文识别结果", "", f"生成时间：{now()}（UTC）", ""]
    if manifest.get("source_discovery"):
        source_check = manifest.get("source_verification", {})
        rows.extend(["推文来源核验：" + md(source_check.get("status", "needs_review")), "", "推文：" + md(source_check.get("resolved_title", "")) + "；公众号：" + md(source_check.get("resolved_account", "")), ""])
    rows.extend(["| ID | 角色 | 正式题名／原始线索 | 作者／年份 | DOI | 出版社／原文 | 匹配 | 全文 |", "|---|---|---|---|---|---|---|---|"])
    bib, exported_ids = [], set()
    for paper in manifest["papers"]:
        metadata = paper.get("metadata", {})
        status = paper.get("verification", {}).get("status", "unresolved")
        links = markdown_link("出版社／原文", metadata.get("publisher_url", ""))
        authors = ", ".join(metadata.get("authors", [])[:2])
        download = paper.get("download", {})
        fullname = download.get("status", "not_requested")
        relative = download.get("path", "")
        if relative.startswith("PDFs/") and ".." not in Path(relative).parts and fullname in {"downloaded", "already_present"}:
            fullname = f"[{fullname}]({urllib.parse.quote(relative)})"
        rows.append(f"| {md(paper['id'])} | {md(paper.get('role'))} | {md(metadata.get('title') or paper.get('raw_title') or paper.get('doi') or paper.get('arxiv_id'))} | {md(authors)} / {md(metadata.get('year'))} | {doi_display(paper)} | {links} | {md(status)} | {fullname} |")
        identity = metadata.get("arxiv_id") or metadata.get("doi") or metadata.get("title")
        if status == "verified" and identity and identity not in exported_ids:
            exported_ids.add(identity)
            key = "wpf_" + hashlib.sha256(identity.encode()).hexdigest()[:12]
            fields = {"title": metadata.get("title"), "author": " and ".join(metadata.get("authors", [])), "year": metadata.get("year"), "journal": metadata.get("venue"), "doi": metadata.get("doi"), "url": metadata.get("publisher_url") or metadata.get("doi_url")}
            if metadata.get("arxiv_id"):
                fields.update({"eprint": metadata["arxiv_id"], "archivePrefix": "arXiv", "note": "Preprint"})
            entry_type = "misc" if metadata.get("version") == "preprint" else "article"
            bib.append("@" + entry_type + "{" + key + ",\n" + ",\n".join(f"  {name} = {{{bib_escape(value)}}}" for name, value in fields.items() if value) + "\n}")
    rows.extend(["", "## 匹配证据与未完成事项", ""])
    for paper in manifest["papers"]:
        rows.extend([f"### {md(paper['id'])}", ""])
        for evidence in paper.get("evidence", []):
            rows.append("- 原文证据：" + md(evidence.get("quote", "")))
        verification = paper.get("verification", {})
        for reason in verification.get("reasons", []) + verification.get("conflicts", []):
            rows.append("- " + md(reason))
        for note in paper.get("download", {}).get("lookup_notes", []):
            rows.append("- 全文查询：" + md(note))
        for attempt in paper.get("download", {}).get("attempts", []):
            rows.append("- 下载尝试：" + md(attempt.get("error")))
        if paper.get("metadata", {}).get("version") == "preprint":
            rows.append("- 版本：预印本；与正式发表版分别记录。")
        rows.append("")
    rows.extend(["未确认的候选不导出为正式引用。no_oa_pdf_found 表示当前来源未找到可下载 PDF，不代表不存在合法全文。", ""])
    (outdir / "report.md").write_text("\n".join(rows), encoding="utf-8")
    (outdir / "references.bib").write_text("\n\n".join(bib) + ("\n" if bib else ""), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    discover = commands.add_parser("discover", help="Build an article-discovery plan from OCR/vision share-card clues")
    discover.add_argument("--input", type=Path, required=True, help="JSON with visible_title, account_name, visible_snippet and title_truncated")
    discover.add_argument("--out", type=Path, required=True)
    extract = commands.add_parser("extract", help="Extract source text, links and literal paper identifiers")
    group = extract.add_mutually_exclusive_group(required=True)
    group.add_argument("--url")
    group.add_argument("--input", type=Path)
    extract.add_argument("--out", type=Path, required=True)
    extract.add_argument("--discovery", type=Path, help="Attach share-card provenance and compare the fetched article identity")
    extract.add_argument("--card", help="Card ID when --discovery contains multiple share cards")
    resolve = commands.add_parser("resolve", help="Resolve DOI/arXiv/title hints; keep ambiguous candidates")
    resolve.add_argument("--input", type=Path, required=True)
    resolve.add_argument("--out", type=Path, required=True)
    resolve.add_argument("--cache", type=Path)
    confirm = commands.add_parser("confirm", help="Record evidence-based review of a specific candidate")
    confirm.add_argument("--manifest", type=Path, required=True)
    confirm.add_argument("--paper", required=True)
    confirm.add_argument("--candidate", type=int, required=True, help="1-based candidate index")
    confirm.add_argument("--evidence-url", required=True)
    confirm.add_argument("--note", required=True)
    download = commands.add_parser("download", help="Download only verified selected papers from OA/authorized links")
    download.add_argument("--manifest", type=Path, required=True)
    download.add_argument("--out", type=Path, required=True)
    download.add_argument("--cache", type=Path)
    download.add_argument("--include-related", action="store_true")
    download.add_argument("--max-mb", type=int, default=80)
    report = commands.add_parser("report", help="Rebuild reports and BibTeX from a manifest")
    report.add_argument("--manifest", type=Path, required=True)
    report.add_argument("--out", type=Path, required=True)
    collect = commands.add_parser("collect", help="Build a many-post, many-paper summary while preserving per-post provenance")
    collect.add_argument("--manifests", type=Path, nargs="+", required=True)
    collect.add_argument("--out", type=Path, required=True)
    collect.add_argument("--profile", choices=["basic", "full"], default="full")
    collect.add_argument("--jif-cache", type=Path, help="Shared journal metrics cache; defaults to work/jif-cache")
    prepare = commands.add_parser("prepare", help="Create a research dossier, graph entry and evidence-backed reproduction checklist")
    origin = prepare.add_mutually_exclusive_group(required=True)
    origin.add_argument("--manifest", type=Path)
    origin.add_argument("--doi", help="Resolve a DOI directly, then create a research dossier")
    origin.add_argument("--arxiv-id", help="Resolve an explicit arXiv ID/version")
    prepare.add_argument("--details", type=Path, help="Agent-reviewed research details bound to matching paper IDs and DOI/arXiv identifiers")
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--cache", type=Path)
    prepare.add_argument("--profile", choices=["basic", "full"], default="full")
    prepare.add_argument("--jif-cache", type=Path, help="Shared journal metrics cache; defaults to work/jif-cache")
    scan = commands.add_parser("scan-resources", help="Find unverified resource URL leads in already-converted Markdown")
    scan.add_argument("--input", type=Path, required=True)
    scan.add_argument("--source-url", required=True)
    scan.add_argument("--doi", default="")
    scan.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    email = os.environ.get("UNPAYWALL_EMAIL", "")
    try:
        client = Client(getattr(args, "cache", None), email)
        if args.command == "prepare":
            from research_prepare import prepare_report
            if args.manifest:
                if args.manifest.resolve().parent != args.out.resolve():
                    raise PaperError("Prepare --out must be the manifest directory to preserve PDF paths")
                intake = read_json(args.manifest)
            else:
                doi = normalize_doi(args.doi or "")
                if args.doi and not doi:
                    raise PaperError("A valid DOI is required")
                intake = resolve_papers({"schema_version": 1, "source": args.doi or args.arxiv_id, "papers": [new_paper(1, role="main", doi=doi, arxiv_id=args.arxiv_id or "")]}, client)
            details = json.loads(args.details.read_text(encoding="utf-8-sig")) if args.details else None
            result = prepare_report(intake, args.out, details, profile=args.profile, jif_cache=args.jif_cache or Path("work/jif-cache"))
            summary = {"status": "prepared", "profile": args.profile, "papers": len(result["papers"]), "verified": sum(p.get("verification", {}).get("status") == "verified" for p in result["papers"]), "path": str(args.out), "note": "Missing fields remain pending; basic profile only requires bibliography, affiliations and journal metrics." if args.profile == "basic" else "Agent must inspect sources, verify resource ownership and translate abstracts; empty fields remain pending."}
        elif args.command == "scan-resources":
            from research_prepare import scan_resources
            result = scan_resources(args.input, args.source_url, args.doi)
            write_json(args.out, result)
            summary = {"status": "resource_candidates", "candidates": len(result["candidates"]), "path": str(args.out)}
        elif args.command == "discover":
            share = json.loads(args.input.read_text(encoding="utf-8-sig"))
            result = discovery_plan(share)
            write_json(args.out, result)
            summary = {"status": "search_needed", "queries": result["search_queries"], "path": str(args.out)}
        elif args.command == "extract":
            source = args.url or str(args.input.resolve())
            if args.url:
                data, content_type, _ = client.fetch(args.url, accept="text/html", use_cache=False)
                raw = data.decode("utf-8-sig", errors="replace")
                if "html" not in content_type.casefold() and not raw.lstrip().startswith("<"):
                    raise PaperError("URL did not return HTML; use document/OCR tools for files")
                is_html = True
            else:
                if args.input.suffix.casefold() not in {".txt", ".md", ".html", ".htm"}:
                    raise PaperError("Convert PDF/Word to Markdown with MinerU; run OCR for images first")
                raw = args.input.read_text(encoding="utf-8-sig")
                is_html = args.input.suffix.casefold() in {".html", ".htm"}
            if is_html:
                parsed = parse_html(raw, args.url or "")
                text = parsed.text()
                if len(norm(text)) < 60:
                    raise PaperError("source_unreadable: page may require login/verification; provide screenshots or text")
                if args.url and urllib.parse.urlsplit(args.url).hostname == "mp.weixin.qq.com" and not re.search(r"\bid\s*=\s*['\"]js_content['\"]", raw, re.I):
                    raise PaperError("source_unreadable: WeChat article body missing; provide screenshots or text")
                result = extract_document(text, source, parsed.links, parsed.images, parsed.metadata)
            else:
                result = extract_document(raw, source)
            if args.discovery:
                discovery = choose_discovery(json.loads(args.discovery.read_text(encoding="utf-8-sig")), args.card)
                if not isinstance(discovery.get("share_card"), dict):
                    raise PaperError("Invalid discovery file: share_card object required")
                result["source_discovery"] = discovery
                result["source_verification"] = compare_article(discovery, result["document"]["metadata"], result["document"]["text"], source)
            write_json(args.out, result)
            summary = {"status": "extracted", "papers": len(result["papers"]), "images": len(result["document"]["images"]), "path": str(args.out)}
        elif args.command == "resolve":
            result = resolve_papers(read_json(args.input), client)
            export(result, args.out)
            summary = {"status": "resolved", "papers": len(result["papers"]), "verified": sum(p.get("verification", {}).get("status") == "verified" for p in result["papers"]), "path": str(args.out)}
        elif args.command == "confirm":
            result = read_json(args.manifest)
            public_url(args.evidence_url)
            if len(clean(args.note)) < 12:
                raise PaperError("Provide a meaningful note explaining the matching evidence")
            paper = next((p for p in result["papers"] if p["id"] == args.paper), None)
            if not paper or not 1 <= args.candidate <= len(paper.get("candidates", [])):
                raise PaperError("Paper/candidate not found")
            selected = paper["candidates"][args.candidate - 1]
            if paper.get("research") and (paper.get("metadata", {}).get("doi"), paper.get("metadata", {}).get("arxiv_id")) != (selected.get("doi"), selected.get("arxiv_id")):
                raise PaperError("Research dossier belongs to the previous candidate; review/reset it before changing paper identity")
            paper["metadata"] = selected
            paper["verification"] = {"status": "verified", "method": "reviewed", "checked_at": now(), "evidence_url": args.evidence_url, "reasons": [args.note]}
            write_json(args.manifest, result)
            export(result, args.manifest.parent)
            summary = {"status": "reviewed", "paper": args.paper}
        elif args.command == "download":
            if not 1 <= args.max_mb <= 300:
                raise PaperError("--max-mb must be between 1 and 300")
            if args.manifest.resolve().parent != args.out.resolve():
                raise PaperError("Download --out must be the manifest directory, so existing file paths remain valid")
            result = download_papers(read_json(args.manifest), args.out, client, email, args.include_related, args.max_mb)
            if any(p.get("research") for p in result["papers"]):
                from research_prepare import prepare_report
                prepare_report(result, args.out)
            else:
                export(result, args.out)
            summary = {"status": "download_batch_finished", "results": {p["id"]: p.get("download", {}).get("status") for p in result["papers"]}, "path": str(args.out)}
        elif args.command == "collect":
            if args.profile == "basic":
                from basic_cards import collect_basic
                result = collect_basic(args.manifests, args.out, args.jif_cache or Path("work/jif-cache"))
            else:
                result = collect_manifests(args.manifests, args.out)
            summary = {"status": "collected", "posts": len(result["posts"]), "unique_verified_works": len(result["unique_verified_works"]), "path": str(args.out)}
        else:
            result = read_json(args.manifest)
            if any(p.get("research") for p in result["papers"]):
                from research_prepare import prepare_report
                prepare_report(result, args.out)
            else:
                export(result, args.out)
            summary = {"status": "reported", "path": str(args.out)}
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except (PaperError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
