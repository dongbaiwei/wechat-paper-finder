"""Live DOI metadata smoke test; NOT a model/skill end-to-end speed comparison."""
import argparse
import json
from pathlib import Path
import time

import paper_finder as wpf
from research_prepare import prepare_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if (args.out / "http-cache").exists():
        parser.error("Choose a new output directory to measure a cold cache honestly")
    identifiers = json.loads(args.inputs.read_text(encoding="utf-8"))
    rows = []
    client = wpf.Client(args.out / "http-cache", timeout=12)
    for phase in ("cold", "warm"):
        for i, doi in enumerate(identifiers, 1):
            started = time.perf_counter()
            manifest = wpf.resolve_papers({"schema_version": 1, "source": doi, "papers": [wpf.new_paper(1, role="main", doi=doi)]}, client)
            prepare_report(manifest, args.out / phase / str(i), profile="basic", jif_cache=args.out / "jif-cache")
            p = manifest["papers"][0]
            rows.append({"phase": phase, "input": doi, "elapsed_seconds": round(time.perf_counter() - started, 3),
                         "resolved_doi": p.get("metadata", {}).get("doi"), "status": p.get("verification", {}).get("status"),
                         "title": p.get("metadata", {}).get("title"), "error": p.get("error", "")})
            wpf.write_json(args.out / "metadata-smoke.json", {"kind": "metadata_script_only", "not_model_ab_test": True, "runs": rows})
            print(json.dumps(rows[-1], ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
