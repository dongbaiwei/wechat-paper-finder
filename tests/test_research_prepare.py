import copy
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import paper_finder as wpf
import research_prepare as rp

DOI = "10.1234/example.2026"
SOURCE = "https://publisher.example/article"
TITLE = "A distinctive study of protein folding with deep learning"


def manifest():
    record = {"DOI": DOI, "title": [TITLE], "author": [{"given": "Alex", "family": "Chen", "affiliation": [{"name": "Example University"}]}], "container-title": ["Example Journal"], "published": {"date-parts": [[2026, 1, 2]]}, "type": "journal-article", "abstract": "<jats:p>We measure <jats:italic>protein</jats:italic> folding.</jats:p>", "resource": {"primary": {"URL": SOURCE}}}
    return {"schema_version": 1, "source": "synthetic", "papers": [{**wpf.new_paper(1, role="main", doi=DOI), "metadata": wpf.crossref_record(record), "verification": {"status": "verified"}, "vision_provenance": {"tool_used": "synthetic"}, "download": {"status": "not_requested"}}]}


def evidence(location="Code Availability"):
    return [{"source_url": SOURCE, "location": location, "quote": "Synthetic supporting statement"}]


def resource(kind="code", scope="author_provided"):
    return {"kind": kind, "name": "Author analysis code", "url": "https://github.com/example/research", "status": "verified", "scope": scope, "access": "open", "version": "v1.0", "evidence": evidence()}


def details(research):
    return {"schema_version": 1, "papers": [{"id": "paper_001", "doi": DOI, "research": research}]}


class ResearchTests(unittest.TestCase):
    def prepare(self, research=None):
        with tempfile.TemporaryDirectory() as folder:
            result = rp.prepare_report(manifest(), folder, details(research) if research is not None else None)
            report = (Path(folder) / "research-report.md").read_text(encoding="utf-8")
            return result, report

    def test_metadata_preserves_abstract_and_author_affiliations(self):
        data = manifest()["papers"][0]["metadata"]
        self.assertEqual(data["author_details"][0]["affiliations"], ["Example University"])
        self.assertEqual(data["abstract"], "We measure protein folding.")

    def test_changed_metadata_cannot_reuse_previous_paper_dossier(self):
        result, _ = self.prepare({"resources": [resource()]})
        result["papers"][0]["metadata"]["doi"] = "10.1234/different"
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError, "another paper"):
            rp.prepare_report(result, folder)

    def test_author_resource_cannot_claim_a_different_owner(self):
        with self.assertRaisesRegex(ValueError, "must belong"):
            self.prepare({"resources": [{**resource(), "owner_doi": "10.1234/other"}]})

    def test_default_dossier_is_pending_not_an_invented_completed_report(self):
        result, report = self.prepare()
        paper = result["papers"][0]
        self.assertIn(f"[{DOI}](https://doi.org/{DOI})", report)
        self.assertIn("待翻译", report)
        self.assertIn("Example University", report)
        self.assertEqual(paper["research"]["connected_papers"]["status"], "search_only")
        self.assertNotIn("/main/", report)
        self.assertIn("尚未检查", report)
        self.assertEqual(paper["vision_provenance"]["tool_used"], "synthetic")
        self.assertEqual(paper["download"]["status"], "not_requested")

    def test_connected_papers_search_uses_full_title_even_with_identifiers(self):
        paper = manifest()["papers"][0]
        paper["metadata"]["arxiv_id"] = "2601.00001"
        paper["metadata"]["title"] = TITLE + ": RNA & protein, single-cell?"
        graph = rp.connected_papers(paper, {"search_url": "https://www.connectedpapers.com/search?q=" + DOI})
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(graph["search_url"]).query)
        self.assertEqual(query, {"q": [paper["metadata"]["title"]]})
        self.assertEqual(graph["status"], "search_only")

    def test_connected_papers_missing_title_does_not_use_doi_or_post_headline(self):
        paper = manifest()["papers"][0]
        paper["metadata"]["title"] = ""
        paper["raw_title"] = "公众号中文导读标题"
        self.assertEqual(rp.connected_papers(paper, {})["search_url"], "")

    def test_reviewed_computational_article_reports_resources_and_original_translation(self):
        result, report = self.prepare({"bibliography": {"article_type": "Article"}, "abstract": {"translation_zh": "我们测量蛋白质折叠。"}, "resources": [resource()], "checks": {"code": {"status": "verified", "reason": "Repository inspected; execution not tested"}}})
        self.assertIn("我们测量蛋白质折叠。", report)
        self.assertIn("v1.0", report)
        self.assertEqual(result["papers"][0]["research"]["checks"]["code"]["status"], "verified")

    def test_experimental_materials_and_equipment_do_not_need_a_repository_url(self):
        rows = [dict(resource(kind), url="", details=info, scope="dependency") for kind, info in [("equipment", "Example mass spectrometer model X"), ("materials", "Example sample and reagent catalogue number R1")]]
        _, report = self.prepare({"resources": rows})
        self.assertIn("model X", report)
        self.assertIn("catalogue number R1", report)

    def test_perspective_preserves_cited_resource_ownership(self):
        row = resource("raw_data", "cited_work")
        row["owner_doi"] = "10.1234/original-study"
        _, report = self.prepare({"bibliography": {"article_type": "Perspective"}, "resources": [row]})
        self.assertIn("综述／观点类文章", report)
        self.assertIn("引用研究的资源", report)
        self.assertIn("10.1234/original-study", report)
        with self.assertRaisesRegex(ValueError, "actual owner's"):
            row.pop("owner_doi")
            self.prepare({"resources": [row]})

    def test_mismatched_details_do_not_write_or_overwrite_exports(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "papers.json"
            target.write_text("original", encoding="utf-8")
            value = details({})
            value["papers"][0]["doi"] = "10.1234/wrong"
            with self.assertRaisesRegex(ValueError, "DOI must match"):
                rp.prepare_report(manifest(), folder, value)
            self.assertEqual(target.read_text(encoding="utf-8"), "original")
            self.assertFalse((Path(folder) / "research-report.md").exists())

    def test_details_reject_unknown_and_duplicate_paper_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            value = details({})
            value["papers"].append(copy.deepcopy(value["papers"][0]))
            with self.assertRaises(ValueError):
                rp.prepare_report(manifest(), folder, value)
            value["papers"] = [dict(value["papers"][0], id="paper_999")]
            with self.assertRaises(ValueError):
                rp.prepare_report(manifest(), folder, value)

    def test_impact_factor_requires_year_source_and_matching_journal(self):
        metric = {"value": 2.1, "metric_year": 2025, "journal": "Example Journal", "source_url": "https://publisher.example/metrics", "checked_at": "2026-10-14"}
        _, report = self.prepare({"impact_factor": metric})
        self.assertIn("2.1（2025）", report)
        for key in ["metric_year", "source_url", "journal", "checked_at"]:
            invalid = copy.deepcopy(metric)
            invalid.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.prepare({"impact_factor": invalid})

    def test_translation_rejects_tldr_and_missing_original(self):
        for invalid in [{"kind": "tldr", "translation_zh": "推测"}, {"original": "", "translation_zh": "推测"}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.prepare({"abstract": invalid})

    def test_graph_requires_origin_match_and_inspection_evidence(self):
        graph = {"url": "https://www.connectedpapers.com/main/" + "a" * 40 + "/graph", "status": "provided"}
        _, report = self.prepare({"connected_papers": graph})
        self.assertIn("用户提供的图谱链接；待核验", report)
        graph.update({"status": "verified", "origin_doi": DOI, "checked_at": "2026-10-14", "evidence": evidence("Graph origin")})
        self.prepare({"connected_papers": graph})
        for patch in [{"origin_doi": "10.1234/wrong"}, {"evidence": []}, {"url": "https://publisher.example/graph"}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.prepare({"connected_papers": {**graph, **patch}})

    def test_resources_reject_verified_without_evidence_and_unsafe_urls(self):
        for patch in [{"evidence": []}, {"scope": "not_assessed"}, {"url": "http://127.0.0.1/private"}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.prepare({"resources": [{**resource(), **patch}]})

    def test_negative_checks_need_actual_coverage_and_cannot_conflict_with_resources(self):
        check = {"status": "not_found", "reason": "No code link in the publisher preview; full text not read", "evidence": evidence("Preview")}
        with self.assertRaisesRegex(ValueError, "coverage"):
            self.prepare({"checks": {"code": check}})
        scope = [{"source_url": SOURCE, "scope": "publisher_preview", "checked_at": "2026-10-14"}]
        _, report = self.prepare({"checks": {"code": check}, "coverage": scope})
        self.assertIn("在已检查范围内未找到", report)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.prepare({"checks": {"code": check}, "coverage": scope, "resources": [resource()]})

    def test_scanner_emits_unverified_leads_including_reference_section(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "paper.md"
            source.write_text("# Code Availability\n[code](https://github.com/example/project).\n# References\nPrevious code: https://github.com/example/previous\n# Data\nDataset https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123\nBad data http://localhost/private\n", encoding="utf-8")
            result = rp.scan_resources(source, SOURCE, DOI)
            self.assertEqual(len(result["candidates"]), 3)
            self.assertTrue(all(r["status"] == "needs_review" and r["scope"] == "not_assessed" for r in result["candidates"]))
            self.assertIn("References", result["candidates"][1]["evidence"][0]["location"])
            self.assertEqual(result["candidates"][2]["kind_hint"], "data")
            with self.assertRaises(ValueError):
                rp.scan_resources(Path(folder) / "paper.pdf", SOURCE)

    def test_csv_and_cli_roundtrip_preserve_reviewed_details(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wpf.write_json(root / "papers.json", manifest())
            wpf.write_json(root / "details.json", details({"resources": [resource()]}))
            args = [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "paper_finder.py"), "prepare", "--manifest", str(root / "papers.json"), "--details", str(root / "details.json"), "--out", str(root)]
            result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "prepared")
            saved = wpf.read_json(root / "papers.json")
            self.assertEqual(saved["papers"][0]["research"]["resources"][0]["version"], "v1.0")
            csv_path = root / "reproduction-checklist.csv"
            self.assertTrue(csv_path.read_bytes().startswith(b"\xef\xbb\xbf"))
            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(len(rows), 9)
            self.assertEqual(rows[1][1], DOI)
            code_row = next(row for row in rows if len(row) > 2 and row[2] == "代码")
            self.assertIn("https://github.com/example/research", code_row[7])
            self.assertIn("v1.0", code_row[8])
            self.assertEqual(wpf.main(["report", "--manifest", str(root / "papers.json"), "--out", str(root)]), 0)


if __name__ == "__main__":
    unittest.main()
