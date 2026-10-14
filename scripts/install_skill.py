#!/usr/bin/env python3
"""Install only the reusable skill payload into a Codex skills directory."""
import argparse
import os
from pathlib import Path
import shutil


def install(source, skills_dir, update=False):
    source, skills_dir = Path(source).resolve(), Path(skills_dir).expanduser().resolve()
    target = skills_dir / "wechat-paper-finder"
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Source and installation directory must be separate")
    if target.exists() and not update:
        raise FileExistsError(f"Skill exists: {target}; use --update after reviewing local changes")
    if not (source / "SKILL.md").is_file():
        raise ValueError("Source SKILL.md not found")
    files = [source / "SKILL.md"]
    for folder in ["agents", "references", "scripts"]:
        files.extend(p for p in (source / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"})
    for path in files:
        relative = path.relative_to(source)
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills")
    parser.add_argument("--update", action="store_true", help="Overwrite the skill payload; preserve unrelated files")
    args = parser.parse_args()
    try:
        target = install(Path(__file__).resolve().parent.parent, args.skills_dir, args.update)
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(f"Installed: {target}\nOpen a new Codex chat if the skill is not yet listed.")


if __name__ == "__main__":
    main()
