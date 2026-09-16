"""Package only project sources, excluding runtime databases and credentials."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    root = Path(__file__).resolve().parent.parent
    target = root / "dist" / "taiwan-attendance-v0.1.0.zip"
    target.parent.mkdir(exist_ok=True)
    files = [root / name for name in ("README.md", "pyproject.toml", "Dockerfile", ".gitignore", ".dockerignore")]
    for name in ("attendance", "web", "tests", "docs", "data", "scripts", ".github"):
        for file in (root / name).rglob("*"):
            if file.is_file() and "__pycache__" not in file.parts and file.suffix in {".py", ".html", ".css", ".js", ".md", ".json", ".yml"}:
                files.append(file)
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for file in sorted(files):
            archive.write(file, Path("taiwan-attendance") / file.relative_to(root))
    print(target)


if __name__ == "__main__":
    main()
