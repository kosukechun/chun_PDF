"""Build, launch the packaged GUI self-test, then generate both distributable ZIPs."""

import argparse
import hashlib
from importlib import metadata
from pathlib import Path
import os
import shutil
import subprocess
import sys
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def notices(dest):
    dest.mkdir(exist_ok=True)
    for name in ["PyMuPDF", "Pillow", "pywin32", "tkinterdnd2", "PyInstaller"]:
        dist = metadata.distribution(name)
        for f in dist.files or []:
            if (
                f.name.lower().startswith(("license", "copying"))
                and dist.locate_file(f).is_file()
            ):
                shutil.copyfile(
                    dist.locate_file(f), dest / (name + "-" + "-".join(f.parts))
                )
    for name, src in [
        ("Python", Path(sys.base_prefix) / "LICENSE.txt"),
        ("Tcl", Path(sys.base_prefix) / "tcl" / "tcl8.6" / "license.terms"),
        ("Tk", Path(sys.base_prefix) / "tcl" / "tk8.6" / "license.terms"),
        ("tessdata", ROOT / "assets" / "tessdata" / "LICENSE"),
    ]:
        if src.is_file():
            shutil.copyfile(src, dest / (name + ".txt"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--iscc",
        default=shutil.which("iscc")
        or str(
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe"
        ),
    )
    args = parser.parse_args()
    run(sys.executable, "-m", "pytest", "-q")
    run(sys.executable, "make_icon.py")
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--noupx",
        "--name",
        "chunPDF",
        "--icon",
        "assets/app.ico",
        "--add-data",
        "assets;assets",
        "--collect-data",
        "tkinterdnd2",
        "--hidden-import",
        "PIL._tkinter_finder",
        "app.py",
    )
    package = ROOT / "dist" / "chunPDF"
    for name in ["README.md", "LICENSE", "THIRD_PARTY_LICENSES.md"]:
        shutil.copyfile(ROOT / name, package / name)
    shutil.copytree(ROOT / "docs", package / "docs", dirs_exist_ok=True)
    notices(package / "licenses")
    run(str(package / "chunPDF.exe"), "--self-test")
    run(str(Path(args.iscc).resolve()), "installer.iss")
    output = ROOT / "downloads"
    output.mkdir(exist_ok=True)
    portable = output / "chunPDF-Portable-x64.zip"
    setup = output / "chunPDF-Setup-x64.zip"
    with ZipFile(portable, "w", ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(package.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(package))
    with ZipFile(setup, "w", ZIP_DEFLATED) as z:
        exe = ROOT / "build" / "installer" / "chunPDF-Setup-x64.exe"
        z.write(exe, exe.name)
    lines = []
    for path in [setup, portable]:
        with ZipFile(path) as z:
            if z.testzip():
                raise RuntimeError("Invalid ZIP: " + str(path))
        if path.stat().st_size > 100 * 1024 * 1024:
            raise RuntimeError("ZIP exceeds GitHub's file size limit")
        lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
