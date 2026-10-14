import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import paper_finder as wpf
import install_skill


TITLE = "A distinctive study of protein folding with deep learning"
DOI = "10.1234/example.2026"


def record(title=TITLE, doi=DOI, year=2026):
    return {"DOI": doi, "title": [title], "author": [{"given": "Alex", "family": "Chen"}], "published": {"date-parts": [[year]]}, "container-title": ["Example Journal"], "publisher": "Example Publisher", "type": "journal-article", "URL": "https://doi.org/" + doi}


def intake(papers):
    return {"schema_version": 1, "source": "synthetic test", "papers": papers}


def verified_paper():
    return {**wpf.new_paper(1, role="main", doi=DOI), "metadata": {**wpf.crossref_record(record()), "fulltext_url": "https://publisher.example/paper.pdf", "access_basis": "open_access", "fulltext_source": "synthetic OA"}, "verification": {"status": "verified"}}


class FakeClient:
    def __init__(self, messages=None, data=b"", failure=None):
        self.messages = list(messages or [])
        self.data = data
        self.failure = failure
        self.calls = []

    def json(self, url):
        self.calls.append(url)
        if self.failure:
            raise wpf.PaperError(self.failure)
        if not self.messages:
            raise AssertionError("Unexpected network lookup: " + url)
        return self.messages.pop(0)

    def fetch(self, url, **kwargs):
        self.calls.append(url)
        if self.failure:
            raise wpf.PaperError(self.failure)
        return self.data, "application/pdf", url


def pdf_bytes(title=TITLE, extra=""):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    def escape(value):
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 9 Tf 20 750 Td ({escape(title)}) Tj 0 -20 Td ({escape(extra)}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class ExtractionTests(unittest.TestCase):
    def test_doi_balanced_parentheses_and_url_case(self):
        self.assertEqual(wpf.normalize_doi("https://doi.org/10.1000/ABC(12)."), "10.1000/abc(12)")
        self.assertEqual(wpf.normalize_doi("(10.1000/ABC)."), "10.1000/abc")
        self.assertEqual(wpf.normalize_doi("`10.1000/ABC`"), "10.1000/abc")
        self.assertEqual(wpf.normalize_doi("[10.1000/ABC](https://doi.org/10.1000/ABC)"), "10.1000/abc")

    def test_wechat_body_links_and_images_without_script_noise(self):
        source = '''<html><head><meta property="og:title" content="Recommendation"></head><body>
        <div>Unrelated footer DOI: 10.9999/wrong</div>
        <div id="js_content"><p>论文题目：A distinctive study of protein folding</p>
        <p>DOI: 10.1234/example.2026</p><a href="https://doi.org/10.1234/example.2026">原文</a>
        <img data-src="https://images.example/first-page.png"><script>hidden()</script></div>
        <div>Other articles</div></body></html>'''
        parsed = wpf.parse_html(source, "https://mp.weixin.qq.com/s/demo")
        self.assertNotIn("hidden", parsed.text())
        self.assertNotIn("Unrelated", parsed.text())
        self.assertNotIn("Other articles", parsed.text())
        self.assertEqual(parsed.images[0]["url"], "https://images.example/first-page.png")
        result = wpf.extract_document(parsed.text(), "demo", parsed.links, parsed.images)
        dois = [p["doi"] for p in result["papers"] if p["doi"]]
        self.assertEqual(dois, [DOI])
        self.assertTrue(any(p["raw_title"] for p in result["papers"]))

    def test_identifiers_in_links_and_arxiv_version(self):
        result = wpf.extract_document("See original", "demo", [{"url": "https://doi.org/10.1234/test", "text": "original"}])
        self.assertEqual(result["papers"][0]["doi"], "10.1234/test")
        result = wpf.extract_document("arXiv:1706.03762v2 and https://arxiv.org/abs/1706.03762v2")
        self.assertEqual(len(result["papers"]), 1)
        self.assertEqual(result["papers"][0]["arxiv_id"], "1706.03762v2")

    def test_chinese_heading_is_not_invented_english_title(self):
        result = wpf.extract_document("研究突破！某团队揭示蛋白质折叠的新规律")
        self.assertEqual(result["papers"], [])

    def test_unsafe_destinations(self):
        for url in ["file:///etc/passwd", "http://127.0.0.1/a", "http://[::1]/", "http://192.168.1.1/", "https://localhost/", "https://secret@example.com/"]:
            with self.subTest(url=url), self.assertRaises(wpf.PaperError):
                wpf.public_url(url)


class ResolutionTests(unittest.TestCase):
    def test_explicit_doi_with_consistent_title_verified(self):
        result = wpf.resolve_papers(intake([wpf.new_paper(1, doi=DOI, raw_title=TITLE, role="main")]), FakeClient([{"message": record()}]))
        self.assertEqual(result["papers"][0]["verification"]["status"], "verified")

    def test_wrong_english_title_blocks_direct_doi(self):
        result = wpf.resolve_papers(intake([wpf.new_paper(1, doi=DOI, raw_title="A completely different investigation into planetary orbits")]), FakeClient([{"message": record()}]))
        self.assertEqual(result["papers"][0]["verification"]["status"], "needs_review")

    def test_identifier_mismatch_not_verified(self):
        result = wpf.resolve_papers(intake([wpf.new_paper(1, doi=DOI)]), FakeClient([{"message": record(doi="10.1234/other")}]))
        self.assertEqual(result["papers"][0]["verification"]["status"], "unresolved")

    def test_title_needs_corroboration(self):
        paper = wpf.new_paper(1, raw_title=TITLE)
        result = wpf.resolve_papers(intake([paper]), FakeClient([{"message": {"items": [record()]}}]))
        self.assertEqual(result["papers"][0]["verification"]["status"], "needs_review")
        paper["author_hint"] = "Chen"
        result = wpf.resolve_papers(intake([paper]), FakeClient([{"message": {"items": [record()]}}]))
        self.assertEqual(result["papers"][0]["verification"]["status"], "verified")

    def test_near_identical_records_require_review(self):
        paper = wpf.new_paper(1, raw_title=TITLE, author_hint="Chen")
        result = wpf.resolve_papers(intake([paper]), FakeClient([{"message": {"items": [record(), record(doi="10.1234/preprint")]}}]))
        self.assertEqual(result["papers"][0]["verification"]["status"], "needs_review")
        self.assertEqual(len(result["papers"][0]["candidates"]), 2)

    def test_duplicate_identifier_keeps_original_evidence(self):
        papers = [wpf.new_paper(1, doi=DOI), wpf.new_paper(2, doi=DOI.upper(), evidence=[{"quote": "second occurrence"}])]
        client = FakeClient([{"message": record()}])
        result = wpf.resolve_papers(intake(papers), client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result["papers"][1]["duplicate_of"], "paper_001")
        self.assertEqual(result["papers"][1]["evidence"][0]["quote"], "second occurrence")

    def test_failure_does_not_prevent_next_paper(self):
        papers = [wpf.new_paper(1), wpf.new_paper(2, doi=DOI)]
        result = wpf.resolve_papers(intake(papers), FakeClient([{"message": record()}]))
        self.assertEqual([p["verification"]["status"] for p in result["papers"]], ["unresolved", "verified"])

    def test_arxiv_version_and_preprint_retained(self):
        atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1706.03762v2</id><title>Attention Is All You Need</title><published>2017-06-12T00:00:00Z</published><author><name>Ashish Vaswani</name></author></entry></feed>'''
        metadata = wpf.arxiv_record("1706.03762v2", FakeClient(data=atom))
        self.assertEqual(metadata["version"], "preprint")
        self.assertEqual(metadata["arxiv_id"], "1706.03762v2")
        with self.assertRaises(wpf.PaperError):
            wpf.arxiv_record("1706.03762v1", FakeClient(data=atom))


class ShareCardTests(unittest.TestCase):
    def test_three_cards_keep_independent_plans_and_require_selection(self):
        plan = wpf.discovery_plan({"cards": [
            {"visible_title": "第一张卡片的文章标题", "account_name": "账号甲"},
            {"visible_title": "第二张卡片的文章标题", "account_name": "账号乙"},
            {"visible_title": "第三张卡片的文章标题", "account_name": "账号丙"},
        ], "vision_provenance": {"tool_used": "synthetic"}})
        self.assertEqual(plan["card_count"], 3)
        selected = wpf.choose_discovery(plan, "card_002")
        self.assertEqual(selected["share_card"]["account_name"], "账号乙")
        self.assertNotIn("账号甲", " ".join(selected["search_queries"]))
        self.assertEqual(selected["share_card"]["vision_provenance"]["tool_used"], "synthetic")
        with self.assertRaises(wpf.PaperError):
            wpf.choose_discovery(plan)

    def test_batch_rejects_duplicate_card_ids(self):
        with self.assertRaises(wpf.PaperError):
            wpf.discovery_plan({"cards": [{"card_id": "card_001", "visible_title": "Title one"}, {"card_id": "card_001", "visible_title": "Title two"}]})

    def test_many_posts_many_papers_collect_without_one_to_one_assumption(self):
        first = verified_paper()
        second = verified_paper()
        second["id"] = "paper_002"
        second["metadata"]["doi"] = "10.1234/second"
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / "card1" / "papers.json", Path(folder) / "card2" / "papers.json"]
            wpf.write_json(paths[0], intake([first, second]))
            wpf.write_json(paths[1], intake([first]))
            collection = wpf.collect_manifests(paths, Path(folder) / "summary")
            self.assertEqual(len(collection["posts"]), 2)
            self.assertEqual(sum(len(post["papers"]) for post in collection["posts"]), 3)
            self.assertEqual(len(collection["unique_verified_works"]), 2)
            self.assertEqual(len(collection["unique_verified_works"][0]["occurrences"]), 2)

    def test_plan_uses_visible_fragment_and_account_not_chat_identity(self):
        plan = wpf.discovery_plan({"visible_title": "团队提出蛋白质折叠新方法…", "title_truncated": True, "account_name": "科研账号", "chat_sender": "Private Sender", "chat_timestamp": "2026-10-14 10:00"})
        self.assertEqual(plan["status"], "search_needed")
        self.assertIn("团队提出蛋白质折叠新方法", plan["search_queries"][0])
        self.assertNotIn("Private Sender", " ".join(plan["search_queries"]))
        self.assertNotIn("10:00", " ".join(plan["search_queries"]))

    def test_capture_account_and_title_outside_body(self):
        parsed = wpf.parse_html('<h1 id="activity-name">团队提出蛋白质折叠新方法，取得进展</h1><a id="js_name"><span>科研账号</span></a><em id="publish_time">2026-10-01</em><div id="js_content"><p>Article body text.</p></div>')
        self.assertEqual(parsed.metadata["account_name"], "科研账号")
        self.assertEqual(parsed.metadata["article_title"], wpf.clean("团队提出蛋白质折叠新方法，取得进展"))
        self.assertEqual(parsed.metadata["published_at"], "2026-10-01")
        self.assertNotIn("科研账号", parsed.text())

    def test_truncated_title_and_matching_account_confirm_source(self):
        plan = wpf.discovery_plan({"visible_title": "团队提出蛋白质折叠新方法…", "title_truncated": True, "account_name": "科研账号"})
        check = wpf.compare_article(plan, {"article_title": "团队提出蛋白质折叠新方法，取得进展", "account_name": "科研账号"}, "body", "https://mp.weixin.qq.com/s/demo")
        self.assertEqual(check["status"], "verified")

    def test_same_title_different_account_needs_review(self):
        plan = wpf.discovery_plan({"visible_title": "团队提出蛋白质折叠新方法", "account_name": "原始公众号"})
        check = wpf.compare_article(plan, {"article_title": "团队提出蛋白质折叠新方法", "account_name": "转载公众号"}, "body", "https://mp.weixin.qq.com/s/repost")
        self.assertEqual(check["status"], "needs_review")
        self.assertTrue(check["account_conflict"])

    def test_title_alone_does_not_confirm_article(self):
        plan = wpf.discovery_plan({"visible_title": "团队提出蛋白质折叠新方法"})
        check = wpf.compare_article(plan, {"article_title": "团队提出蛋白质折叠新方法"}, "body", "https://mp.weixin.qq.com/s/demo")
        self.assertEqual(check["status"], "needs_review")

    def test_direct_url_with_conflicting_title_not_confirmed(self):
        url = "https://mp.weixin.qq.com/s/demo"
        plan = wpf.discovery_plan({"visible_title": "团队提出蛋白质折叠新方法", "article_url": url})
        check = wpf.compare_article(plan, {"article_title": "完全无关的细胞研究报告"}, "body", url)
        self.assertEqual(check["status"], "needs_review")

    def test_unconfirmed_original_blocks_automatic_download(self):
        data = intake([verified_paper()])
        data["source_discovery"] = wpf.discovery_plan({"visible_title": "A shared post title"})
        data["source_verification"] = {"status": "needs_review"}
        client = FakeClient()
        with tempfile.TemporaryDirectory() as folder:
            result = wpf.download_papers(data, folder, client)
            self.assertEqual(result["papers"][0]["download"]["status"], "skipped_source_unverified")
            self.assertEqual(client.calls, [])


@unittest.skipUnless(importlib.util.find_spec("pypdf"), "Install the [pdf] extra to test PDF validation")
class DownloadTests(unittest.TestCase):
    def test_real_pdf_title_and_hash_validation(self):
        data = pdf_bytes(extra="DOI: " + DOI)
        result = wpf.validate_pdf(data, verified_paper()["metadata"])
        self.assertEqual(result["pages"], 1)
        self.assertTrue(result["doi_present"])
        self.assertEqual(len(result["sha256"]), 64)

    def test_html_response_rejected(self):
        with self.assertRaisesRegex(wpf.PaperError, "not_pdf"):
            wpf.validate_pdf(b"<html>Sign in</html>", verified_paper()["metadata"])

    def test_target_doi_in_wrong_article_reference_not_enough(self):
        data = pdf_bytes("Unrelated research into orbital dynamics and celestial mechanics", "References: " + DOI)
        with self.assertRaisesRegex(wpf.PaperError, "identity_unverified"):
            wpf.validate_pdf(data, verified_paper()["metadata"])

    def test_target_title_in_reference_section_not_enough(self):
        data = pdf_bytes("Unrelated research into orbital dynamics", "References: " + TITLE + ". DOI: " + DOI)
        with self.assertRaisesRegex(wpf.PaperError, "identity_unverified"):
            wpf.validate_pdf(data, verified_paper()["metadata"])

    def test_corrupted_pdf_rejected(self):
        with self.assertRaisesRegex(wpf.PaperError, "invalid_pdf"):
            wpf.validate_pdf(b"%PDF-1.7\ninvalid", verified_paper()["metadata"])

    def test_download_resume_avoids_network_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient(data=pdf_bytes())
            result = wpf.download_papers(intake([verified_paper()]), folder, client)
            self.assertEqual(result["papers"][0]["download"]["status"], "downloaded")
            self.assertEqual(len(client.calls), 1)
            second_client = FakeClient(failure="Must not request again")
            second = wpf.download_papers(result, folder, second_client)
            self.assertEqual(second["papers"][0]["download"]["status"], "already_present")
            self.assertEqual(second["papers"][0]["download"]["source"], "synthetic OA")
            self.assertEqual(second_client.calls, [])

    def test_download_failed_does_not_write_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            result = wpf.download_papers(intake([verified_paper()]), folder, FakeClient(data=b"<html>Login</html>"))
            self.assertEqual(result["papers"][0]["download"]["status"], "download_failed")
            self.assertEqual(list(Path(folder).rglob("*.pdf")), [])

    def test_unknown_role_and_unverified_papers_skipped(self):
        paper = verified_paper()
        paper["role"] = "unknown"
        client = FakeClient()
        with tempfile.TemporaryDirectory() as folder:
            result = wpf.download_papers(intake([paper, wpf.new_paper(2)]), folder, client)
            self.assertEqual([p["download"]["status"] for p in result["papers"]], ["skipped_role", "skipped_unverified"])
            self.assertEqual(client.calls, [])

    def test_stale_success_not_reported_after_unverification(self):
        paper = verified_paper()
        paper["verification"]["status"] = "needs_review"
        paper["download"] = {"status": "downloaded"}
        with tempfile.TemporaryDirectory() as folder:
            result = wpf.download_papers(intake([paper]), folder, FakeClient())
            self.assertEqual(result["papers"][0]["download"]["status"], "skipped_unverified")

    def test_existing_bad_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            original = wpf.download_papers(intake([verified_paper()]), folder, FakeClient(data=pdf_bytes()))
            path = Path(folder) / original["papers"][0]["download"]["path"]
            path.write_bytes(b"invalid existing file")
            result = wpf.download_papers(original, folder, FakeClient())
            self.assertEqual(result["papers"][0]["download"]["status"], "existing_file_needs_review")
            self.assertEqual(path.read_bytes(), b"invalid existing file")


class OAAndExportTests(unittest.TestCase):
    def test_reports_show_full_doi_and_missing_or_unverified_status(self):
        verified = verified_paper()
        verified["metadata"].pop("doi_url")  # The identifier alone must produce a link.
        pending = wpf.new_paper(2, raw_title="Source hint", doi="10.1234/pending")
        preprint = wpf.new_paper(3, raw_title="Preprint", arxiv_id="1706.03762v2")
        manifest = intake([verified, pending, preprint])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wpf.export(manifest, root / "post")
            wpf.collect_manifests([root / "post" / "papers.json"], root / "summary")
            for report in [root / "post" / "report.md", root / "summary" / "report.md"]:
                with self.subTest(report=report.parent.name):
                    rows = report.read_text(encoding="utf-8").splitlines()
                    first = next(row for row in rows if row.startswith("|") and "paper_001" in row)
                    second = next(row for row in rows if row.startswith("|") and "paper_002" in row)
                    third = next(row for row in rows if row.startswith("|") and "paper_003" in row)
                    self.assertIn(f"[{DOI}](https://doi.org/{DOI})", first)
                    self.assertNotIn("待核验", first)
                    self.assertIn("[10.1234/pending](https://doi.org/10.1234/pending)（待核验）", second)
                    self.assertIn("未查到／待确认", third)
                    self.assertNotIn("doi.org/", third)

    def test_unpaywall_locations_preserve_version_and_license(self):
        client = FakeClient([
            {"resultList": {"result": []}},
            {"doi": DOI, "best_oa_location": {"url_for_pdf": "https://repo.example/paper.pdf", "host_type": "repository", "version": "acceptedVersion", "license": "cc-by"}, "oa_locations": []},
        ])
        locations, _ = wpf.oa_locations({"doi": DOI}, client, "researcher@example.org")
        self.assertEqual(locations[0]["version"], "acceptedVersion")
        self.assertEqual(locations[0]["license"], "cc-by")

    def test_europe_pmc_must_match_doi_and_oa_flag(self):
        client = FakeClient([{"resultList": {"result": [
            {"doi": "10.1234/wrong", "isOpenAccess": "Y", "fullTextUrlList": {"fullTextUrl": [{"documentStyle": "pdf", "availability": "Open access", "url": "https://repo.example/wrong.pdf"}]}},
            {"doi": DOI, "isOpenAccess": "N", "fullTextUrlList": {"fullTextUrl": [{"documentStyle": "pdf", "availability": "Open access", "url": "https://repo.example/closed.pdf"}]}}
        ]}}])
        locations, notes = wpf.oa_locations({"doi": DOI}, client)
        self.assertEqual(locations, [])
        self.assertTrue(any("UNPAYWALL_EMAIL" in n for n in notes))

    def test_bibtex_only_verified_and_duplicate_free(self):
        first = verified_paper()
        second = copy.deepcopy(first)
        second["id"] = "paper_002"
        third = copy.deepcopy(first)
        third["id"] = "paper_003"
        third["metadata"]["title"] = "Unverified contender"
        third["verification"]["status"] = "needs_review"
        with tempfile.TemporaryDirectory() as folder:
            wpf.export(intake([first, second, third]), folder)
            bib = (Path(folder) / "references.bib").read_text(encoding="utf-8")
            self.assertEqual(bib.count("@article"), 1)
            self.assertNotIn("Unverified contender", bib)
            self.assertTrue((Path(folder) / "report.md").exists())

    def test_filename_safe_on_windows(self):
        self.assertEqual(wpf.safe_name("CON"), "_CON")
        self.assertNotIn("/", wpf.safe_name("A/B: a? title"))

    def test_manifest_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            wpf.write_json(path, intake([wpf.new_paper(1), wpf.new_paper(1)]))
            with self.assertRaises(wpf.PaperError):
                wpf.read_json(path)

    def test_review_rejects_missing_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "papers.json"
            wpf.write_json(path, intake([wpf.new_paper(1)]))
            result = wpf.main(["confirm", "--manifest", str(path), "--paper", "paper_001", "--candidate", "1", "--evidence-url", "https://publisher.example/article", "--note", "The original author and title agree with the paper"])
            self.assertEqual(result, 1)

    def test_skill_installer_payload_and_existing_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            target = install_skill.install(ROOT, Path(folder))
            self.assertTrue((target / "SKILL.md").exists())
            self.assertTrue((target / "scripts" / "paper_finder.py").exists())
            self.assertFalse((target / "tests").exists())
            self.assertFalse((target / "README.md").exists())
            with self.assertRaises(FileExistsError):
                install_skill.install(ROOT, Path(folder))

    def test_cli_extract_and_schema_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "intake.json"
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "paper_finder.py"), "extract", "--input", str(ROOT / "examples" / "post.md"), "--out", str(target)], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertGreaterEqual(len(wpf.read_json(target)["papers"]), 1)


if __name__ == "__main__":
    unittest.main()
