"""Apply the reviewed memory/lifecycle diff after the existing Plus patches."""
from pathlib import Path
import subprocess


def apply(source: Path) -> None:
    patch = Path(__file__).with_name("memory-fixes.patch").resolve()
    # Older generated sources mix BOM, CRLF and LF. The reviewed diff uses
    # UTF-8/LF; normalize only its existing input files before matching hunks.
    patch_text = patch.read_text(encoding="utf-8")
    for line in patch_text.splitlines():
        if line.startswith("--- a/"):
            target = source / line.removeprefix("--- a/")
            target.write_bytes(target.read_text(encoding="utf-8-sig").encode("utf-8"))
    # Explicit work-tree avoids interpreting paths relative to a parent overlay
    # repository when the source was extracted from an archive.
    command = ["git", "--work-tree", str(source.resolve()), "apply", "--whitespace=nowarn"]
    subprocess.run(command + ["--check", "-"], input=patch_text.encode("utf-8"), cwd=source, check=True)
    subprocess.run(command + ["-"], input=patch_text.encode("utf-8"), cwd=source, check=True)
