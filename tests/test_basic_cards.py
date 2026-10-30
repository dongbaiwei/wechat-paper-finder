import copy
import csv
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_research_prepare import manifest, details, DOI
import paper_finder as wpf
import research_prepare as rp
import basic_cards as bc


def metric(days=0, **extra):
    return {"value": 1.2, "metric_year": 2025, "journal": "Example Journal",
            "source_url": "https://publisher.example/metrics",
            "checked_at": (bc.utcnow() - timedelta(days=days)).isoformat(), **extra}


class BasicTests(unittest.TestCase):
    def test_basic_does_not_run_full_modules_and_exports_all_formats(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(rp, "connected_papers", side_effect=AssertionError("graph called")), patch.object(rp, "render_report", side_effect=AssertionError("full called")):
            result = rp.prepare_report(manifest(), folder, profile="basic")
            self.assertNotIn("abstract", result["papers"][0]["research"])
            self.assertNotIn("resources", result["papers"][0]["research"])
            for suffix in ("md", "json", "csv"):
                self.assertTrue((Path(folder) / ("basic-cards." + suffix)).exists())
            data = json.loads((Path(folder) / "basic-cards.json").read_text(encoding="utf-8"))
            self.assertEqual(data["papers"][0]["doi"], DOI)
            self.assertEqual(data["papers"][0]["authors"][0]["affiliations"], ["Example University"])

    def test_verified_duplicates_keep_every_source_and_version(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = []
            for i in range(3):
                data = manifest()
                data["source"] = f"card{i}"
                if i == 2:
                    data["papers"][0]["metadata"]["arxiv_id"] = "2601.00001v1"
                path = root / f"{i}.json"
                wpf.write_json(path, data)
                paths.append(path)
            result = bc.collect_basic(paths, root / "out")
            self.assertEqual(len(result["papers"]), 2)
            self.assertEqual(len(result["papers"][0]["origins"]), 2)

    def test_resolver_duplicate_reuses_verified_metadata_but_conflicting_hint_does_not_merge(self):
        data = manifest()
        data["papers"].append({**wpf.new_paper(2, role="main", doi=DOI), "duplicate_of": "paper_001", "verification": {"status": "duplicate"}})
        bc.expand_duplicates(data["papers"])
        self.assertEqual(data["papers"][1]["verification"]["status"], "verified")
        data["papers"][1]["year_hint"] = 1990
        bc.expand_duplicates(data["papers"])
        self.assertEqual(data["papers"][1]["verification"]["status"], "needs_review")

    def test_similar_candidates_are_not_deduplicated(self):
        data = manifest()
        data["papers"][0]["verification"]["status"] = "needs_review"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "in.json"
            wpf.write_json(path, data)
            result = bc.collect_basic([path, path], Path(folder) / "out")
            self.assertEqual(len(result["papers"]), 2)

    def test_one_post_many_papers_missing_input_and_background(self):
        data = manifest()
        data["papers"] += [{**wpf.new_paper(2, role="main"), "raw_title": "unresolved work"},
                           {**wpf.new_paper(3, role="background"), "raw_title": "background"}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "in.json"
            wpf.write_json(path, data)
            result = bc.collect_basic([path, Path(folder) / "missing.json"], Path(folder) / "out")
            self.assertEqual(len(result["papers"]), 3)
            self.assertIn("DOI", result["papers"][1]["missing_fields"])
            self.assertTrue(any("校验失败" in v for v in result["papers"][2]["missing_fields"]))

    def test_empty_input_remains_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            rp.prepare_report({"papers": [], "source": "empty screenshot"}, folder, profile="basic")
            rows = json.loads((Path(folder) / "basic-cards.json").read_text(encoding="utf-8"))["papers"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["origins"][0]["source"], "empty screenshot")

    def test_missing_affiliations_and_jif_stay_missing(self):
        data = manifest()
        data["papers"][0]["metadata"]["author_details"] = []
        with tempfile.TemporaryDirectory() as folder:
            rp.prepare_report(data, folder, profile="basic")
            row = json.loads((Path(folder) / "basic-cards.json").read_text(encoding="utf-8"))["papers"][0]
            self.assertIn("作者机构对应", row["missing_fields"])
            self.assertIn("JIF及来源", row["missing_fields"])

    def test_invalid_metric_fails_item_without_aborting_batch(self):
        for bad in ({"source_url": ""}, {"metric_year": None}, {"value": float("nan")}, {"checked_at": "bad"}, {"journal": "Other"}):
            data = manifest()
            data["papers"] += [copy.deepcopy(data["papers"][0])]
            data["papers"][1]["id"] = "paper_002"
            data["papers"][0]["research"] = {"impact_factor": metric(**bad)}
            cache = bc.JournalCache()
            bc.normalize_batch(data["papers"], cache)
            self.assertIn("basic_error", data["papers"][0])
            self.assertNotIn("basic_error", data["papers"][1])

    def test_cache_same_batch_reuse_preserves_check_date(self):
        first, second = manifest()["papers"][0], manifest()["papers"][0]
        first["research"] = {"impact_factor": metric(2)}
        original_date = first["research"]["impact_factor"]["checked_at"]
        bc.normalize_batch([second, first], bc.JournalCache())
        self.assertEqual(second["research"]["impact_factor"]["checked_at"], original_date)
        self.assertEqual(second["research"]["impact_factor"]["cache_status"], "fresh")

    def test_expired_cache_and_refresh_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            first = manifest()["papers"][0]
            first["research"] = {"impact_factor": metric(31)}
            bc.normalize_batch([first], bc.JournalCache(folder))
            second = manifest()["papers"][0]
            second["research"] = {"impact_factor": {"refresh_error": "website unavailable"}}
            bc.normalize_batch([second], bc.JournalCache(folder))
            value = second["research"]["impact_factor"]
            self.assertEqual(value["cache_status"], "stale")
            self.assertEqual(value["refresh_error"], "website unavailable")
            self.assertEqual(value["checked_at"], first["research"]["impact_factor"]["checked_at"])

    def test_wrong_journal_not_reused_and_corrupt_cache_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "bad.json").write_text("invalid", encoding="utf-8")
            cache = bc.JournalCache(folder)
            self.assertEqual(len(cache.warnings), 1)
            first = manifest()["papers"][0]
            first["research"] = {"impact_factor": metric()}
            cache.remember(first)
            second = manifest()["papers"][0]
            second["metadata"]["venue"] = "Another Journal"
            cache.apply(second)
            self.assertEqual(second["research"]["impact_factor"], {})

    def test_csv_has_sources_and_preserves_authorship(self):
        with tempfile.TemporaryDirectory() as folder:
            rp.prepare_report(manifest(), folder, details({"impact_factor": metric()}), profile="basic")
            with (Path(folder) / "basic-cards.csv").open(encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertIn("Alex Chen：Example University", row["authors_affiliations"])
            self.assertEqual(row["jif_source"], "https://publisher.example/metrics")
            self.assertTrue(row["jif_checked_at"])

    def test_cli_basic_and_collect(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "papers.json"
            wpf.write_json(path, manifest())
            self.assertEqual(wpf.main(["prepare", "--manifest", str(path), "--out", str(root), "--profile", "basic", "--jif-cache", str(root / "cache")]), 0)
            self.assertEqual(wpf.main(["collect", "--manifests", str(path), "--out", str(root / "batch"), "--profile", "basic", "--jif-cache", str(root / "cache")]), 0)
            self.assertFalse((root / "research-report.md").exists())


if __name__ == "__main__":
    unittest.main()
