#!/usr/bin/env python3
"""Reproducible Step 0.1 package-installation baseline snapshot.

Run from the repository root:

    python3 reports/step0.1-environment/snapshot_step01_packages.py

The script only inspects the environment; it never installs anything.
It writes machine-readable baseline files into this directory:

* package_baseline.csv   one row per recommended apt package / observable CLI /
                         Python module / npm global package
* pip_freeze.txt         ``pip list --format=freeze`` output
* npm_global.json        ``npm ls -g --json`` output
* snapshot_meta.json     host, toolchain and writability metadata
"""

from __future__ import annotations

import csv
import importlib.metadata
import importlib.util
import json
import os
import shutil
import site
import subprocess
import sys
import sysconfig
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
STEP01_BUNDLES = ROOT / "reports/bash-behavior-analysis/step01_package_bundles.csv"

# Extra items observed in the current environment and tracked as baseline context.
EXTRA_APT = {
    "python3": "Python 3 interpreter",
    "python3-pip": "pip entry point",
    "python3-numpy": "NumPy (Step 0 carry-over)",
    "python3-pil": "Pillow (Step 0 carry-over)",
    "google-chrome-stable": "Google Chrome (Step 0 carry-over)",
    "chafa": "terminal image viewer (Step 0 carry-over)",
    "imagemagick": "convert/identify/magick (Step 0 carry-over)",
    "tesseract-ocr": "OCR engine (Step 0 carry-over)",
    "tesseract-ocr-eng": "English OCR data (Step 0 carry-over)",
    "ripgrep": "rg",
    "gh": "GitHub CLI",
    "curl": "curl",
    "wget": "wget",
}

# command -> version-flag used to record a readable version
CLI_ITEMS = {
    # step 0.1 core
    "python": {"version": ["--version"], "bundle": "step0.1-core", "recommended": "observed"},
    "python3": {"version": ["--version"], "bundle": "step0.1-core", "recommended": "observed"},
    "pip": {"version": ["--version"], "bundle": "step0.1-core", "recommended": "observed"},
    "pip3": {"version": ["--version"], "bundle": "step0.1-core", "recommended": "observed"},
    "pytest": {"version": ["--version"], "bundle": "step0.1-core", "recommended": "step0.1"},
    "zip": {"version": ["-v"], "bundle": "step0.1-core", "recommended": "step0.1"},
    "unzip": {"version": ["-v"], "bundle": "step0.1-core", "recommended": "step0.1"},
    "pngcheck": {"version": ["--version"], "bundle": "step0.1-core", "recommended": "step0.1"},
    # step 0.1 docs
    "pandoc": {"version": ["--version"], "bundle": "step0.1-docs", "recommended": "step0.1"},
    "pdftotext": {"version": ["-v"], "bundle": "step0.1-docs", "recommended": "step0.1"},
    "pdfinfo": {"version": ["-v"], "bundle": "step0.1-docs", "recommended": "step0.1"},
    "pdftoppm": {"version": ["-v"], "bundle": "step0.1-docs", "recommended": "step0.1"},
    "gs": {"version": ["--version"], "bundle": "step0.1-docs", "recommended": "step0.1"},
    "fc-list": {"version": ["--version"], "bundle": "step0.1-docs", "recommended": "step0.1"},
    "fc-cache": {"version": ["--version"], "bundle": "step0.1-docs", "recommended": "step0.1"},
    "weasyprint": {"version": ["--version"], "bundle": "step0.1-docs", "recommended": "step0.1"},
    # step 0.1 build
    "make": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "step0.1"},
    "gcc": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "step0.1"},
    "g++": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "step0.1"},
    "cmake": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "step0.1"},
    "ctest": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "step0.1"},
    "ninja": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "step0.1"},
    "pkgconf": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "step0.1"},
    "pkg-config": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "observed"},
    "dpkg-deb": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "observed"},
    "meson": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "context"},
    "gfortran": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "context"},
    "clang": {"version": ["--version"], "bundle": "step0.1-build", "recommended": "context"},
    # step 0.1 data / general Python-backed CLI
    "chafa": {"version": ["--version"], "bundle": "step0-legacy", "recommended": "step0"},
    "convert": {"version": ["--version"], "bundle": "step0-legacy", "recommended": "step0"},
    "identify": {"version": ["--version"], "bundle": "step0-legacy", "recommended": "step0"},
    "magick": {"version": ["--version"], "bundle": "step0-legacy", "recommended": "step0"},
    "tesseract": {"version": ["--version"], "bundle": "step0-legacy", "recommended": "step0"},
    "google-chrome": {"version": ["--version"], "bundle": "step0-legacy", "recommended": "step0"},
    # P2 observation set: already present or intentionally watched
    "git": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "gh": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "rg": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "curl": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "wget": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "awk": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "sed": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "perl": {"version": ["-v"], "bundle": "step0.1-p2", "recommended": "observed"},
    "tar": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "file": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "jq": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "watch"},
    "fd": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "watch"},
    "tree": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "watch"},
    "sqlite3": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "watch"},
    "node": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "npm": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "npx": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "pnpm": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "observed"},
    "yarn": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "watch"},
    "tsx": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "watch"},
    "chromium": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "watch"},
    "chromium-browser": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "watch"},
    "firefox": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "watch"},
    "playwright": {"version": ["--version"], "bundle": "step0.1-p2", "recommended": "watch"},
}

PY_MODULE_ITEMS = {
    "pip": ("step0.1-core", "observed"),
    "pytest": ("step0.1-core", "step0.1"),
    "websocket": ("step0.1-core", "step0.1"),
    "websockets": ("step0.1-core", "context"),
    "reportlab": ("step0.1-docs", "step0.1"),
    "fitz": ("step0.1-docs", "step0.1"),
    "pymupdf": ("step0.1-docs", "step0.1"),
    "svglib": ("step0.1-docs", "step0.1"),
    "fontTools": ("step0.1-docs", "step0.1"),
    "weasyprint": ("step0.1-docs", "step0.1"),
    "numpy": ("step0.1-data", "step0"),
    "scipy": ("step0.1-data", "step0.1"),
    "pandas": ("step0.1-data", "step0.1"),
    "matplotlib": ("step0.1-data", "step0.1"),
    "PIL": ("step0.1-data", "step0"),
    "sympy": ("step0.1-data", "context"),
    "sklearn": ("step0.1-data", "watch"),
    "cv2": ("step0.1-p2", "watch"),
    "playwright": ("step0.1-p2", "watch"),
    "selenium": ("step0.1-p2", "watch"),
    "flask": ("step0.1-p2", "watch"),
    "fastapi": ("step0.1-p2", "watch"),
    "uvicorn": ("step0.1-p2", "watch"),
    "requests": ("step0.1-p2", "observed"),
    "httpx": ("step0.1-p2", "watch"),
    "bs4": ("step0.1-p2", "observed"),
    "lxml": ("step0.1-p2", "observed"),
    "yaml": ("step0.1-p2", "observed"),
    "openpyxl": ("step0.1-p2", "observed"),
    "rich": ("step0.1-p2", "observed"),
    "click": ("step0.1-p2", "observed"),
    "pygments": ("step0.1-p2", "observed"),
}


def run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        check=False,
    )


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def dpkg_status(package: str) -> tuple[bool, str]:
    proc = run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}\t${Version}", "--", package])
    if proc.returncode != 0 or not proc.stdout.strip():
        return False, ""
    status, version = (proc.stdout.strip().split("\t", 1) + [""])[:2]
    return status == "ii ", version


def cli_status(command: str, version_args: list[str] | None) -> tuple[bool, str, str]:
    path = shutil.which(command)
    if not path:
        return False, "", ""
    version = ""
    if version_args:
        proc = run([command, *version_args])
        version = first_line(proc.stdout or proc.stderr)
    return True, path, version


def module_status(module: str) -> tuple[bool, str, str]:
    try:
        spec = importlib.util.find_spec(module)
    except (ModuleNotFoundError, ValueError, ImportError):
        spec = None
    if spec is None:
        return False, "", ""
    version = ""
    try:
        version = importlib.metadata.version(module)
    except importlib.metadata.PackageNotFoundError:
        pass
    if not version:
        # Pillow exposes the PIL module while its distribution is named Pillow.
        dist_map = {"PIL": "Pillow", "yaml": "PyYAML", "bs4": "beautifulsoup4"}
        try:
            version = importlib.metadata.version(dist_map.get(module, module))
        except importlib.metadata.PackageNotFoundError:
            pass
    return True, spec.origin or "", version


def parse_step01_bundles() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with STEP01_BUNDLES.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            priority = (row.get("priority") or "").strip()
            domain = (row.get("domain") or "").strip()
            delivery = (row.get("delivery") or "").strip()
            apt_packages = (row.get("apt_packages") or "").strip()
            if priority and domain and apt_packages and apt_packages != "不新增；另设 browser/docs-heavy profile 时再评估":
                bundle_map = {
                    ("P0", "Python 入口、测试与轻量胶水"): "step0.1-core",
                    ("P0", "文档、PDF 与字体"): "step0.1-docs",
                    ("P0", "原生构建与发布"): "step0.1-build",
                    ("P1", "科学计算、数据与绘图"): "step0.1-data",
                }
                bundle = bundle_map.get((priority, domain), "step0.1-other")
                for raw in apt_packages.split(";"):
                    pkg = raw.strip()
                    if pkg:
                        rows.append(
                            {
                                "priority": priority,
                                "domain": domain,
                                "delivery": delivery,
                                "bundle": bundle,
                                "package": pkg,
                            }
                        )
    return rows


def main() -> None:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict[str, str]] = []

    # 1. The Step 0.1 decision matrix: check each recommended apt package.
    for item in parse_step01_bundles():
        installed, version = dpkg_status(item["package"])
        rows.append(
            {
                "bundle": item["bundle"],
                "priority": item["priority"],
                "domain": item["domain"],
                "kind": "apt",
                "item": item["package"],
                "recommended": "step0.1",
                "status": "installed" if installed else "missing",
                "version": version,
                "detail": item["delivery"],
            }
        )

    # 2. Extra apt packages that are part of the current callable surface.
    for package, note in EXTRA_APT.items():
        installed, version = dpkg_status(package)
        rows.append(
            {
                "bundle": "step0.1-context",
                "priority": "",
                "domain": "已存在环境包",
                "kind": "apt",
                "item": package,
                "recommended": "observed",
                "status": "installed" if installed else "missing",
                "version": version,
                "detail": note,
            }
        )

    # 3. Observable CLIs.
    for command, meta in CLI_ITEMS.items():
        available, path, version = cli_status(command, meta.get("version"))
        rows.append(
            {
                "bundle": meta["bundle"],
                "priority": "",
                "domain": "",
                "kind": "cli",
                "item": command,
                "recommended": meta["recommended"],
                "status": "installed" if available else "missing",
                "version": version,
                "detail": path,
            }
        )

    # 4. Python modules.
    for module, (bundle, recommended) in PY_MODULE_ITEMS.items():
        available, path, version = module_status(module)
        rows.append(
            {
                "bundle": bundle,
                "priority": "",
                "domain": "",
                "kind": "python-module",
                "item": module,
                "recommended": recommended,
                "status": "installed" if available else "missing",
                "version": version,
                "detail": path,
            }
        )

    # 5. npm global packages.
    npm_global_path = OUT / "npm_global.json"
    npm_global_proc = run(["npm", "ls", "-g", "--depth=0", "--json"])
    npm_global_data: dict = {}
    if npm_global_proc.returncode == 0:
        npm_global_path.write_text(npm_global_proc.stdout, encoding="utf-8")
        try:
            npm_global_data = json.loads(npm_global_proc.stdout)
        except json.JSONDecodeError:
            npm_global_data = {}
    for name, value in (npm_global_data.get("dependencies") or {}).items():
        rows.append(
            {
                "bundle": "step0.1-p2",
                "priority": "",
                "domain": "",
                "kind": "npm-global",
                "item": name,
                "recommended": "observed",
                "status": "installed",
                "version": str(value.get("version", "")),
                "detail": "npm global",
            }
        )

    # 6. pip freeze for the full Python package surface.
    pip_proc = run(["pip", "list", "--format=freeze"])
    pip_freeze = pip_proc.stdout if pip_proc.returncode == 0 else pip_proc.stderr
    (OUT / "pip_freeze.txt").write_text(pip_freeze, encoding="utf-8")
    pip_count = len([line for line in pip_freeze.splitlines() if "==" in line])

    # 7. Host metadata and writability checks.
    user_site = site.USER_SITE
    purelib = sysconfig.get_path("purelib")
    local_home = Path.home() / ".local"
    apt_status = run(["dpkg-query", "-W", "-f=${db:Status-Abbrev}\n"])
    apt_installed_count = sum(
        1 for line in apt_status.stdout.splitlines() if line.strip() == "ii"
    )
    tesseract_langs_proc = run(["tesseract", "--list-langs"])
    sudo_proc = run(["sudo", "-n", "true"], timeout=5)
    tesseract_langs = [
        line.strip()
        for line in tesseract_langs_proc.stdout.splitlines()
        if line.strip() and not line.startswith("List of available languages")
    ]
    meta = {
        "generated_at": generated_at,
        "repo_root": str(ROOT),
        "uname": " ".join(run(["uname", "-a"]).stdout.strip().split()),
        "user": os.environ.get("USER", ""),
        "shell": os.environ.get("SHELL", ""),
        "python": sys.version.splitlines()[0] if sys.version else "",
        "python_executable": sys.executable,
        "bash": first_line(run(["bash", "--version"]).stdout),
        "apt_installed_count": apt_installed_count,
        "pip_package_count": pip_count,
        "pip_user_site": user_site,
        "pip_user_site_exists": os.path.exists(user_site),
        "system_purelib": purelib,
        "system_purelib_writable": os.access(purelib, os.W_OK),
        "home_local_exists": local_home.exists(),
        "home_local_mode": oct(local_home.stat().st_mode & 0o777) if local_home.exists() else None,
        "home_local_writable": os.access(local_home, os.W_OK),
        "sudo_noninteractive_available": sudo_proc.returncode == 0,
        "node": first_line(run(["node", "--version"]).stdout),
        "npm": first_line(run(["npm", "--version"]).stdout),
        "pnpm": first_line(run(["pnpm", "--version"]).stdout),
        "cjk_font_count": len(
            run(["fc-list", ":lang=zh"]).stdout.splitlines()
        ),
        "tesseract_langs": tesseract_langs,
    }
    meta["bash_binary"] = shutil.which("bash")

    # 8. Write CSV.
    csv_path = OUT / "package_baseline.csv"
    columns = [
        "bundle", "priority", "domain", "kind", "item", "recommended",
        "status", "version", "detail",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "snapshot_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    installed_step01 = sum(
        1 for r in rows if r["kind"] == "apt" and r["recommended"] == "step0.1" and r["status"] == "installed"
    )
    total_step01 = sum(
        1 for r in rows if r["kind"] == "apt" and r["recommended"] == "step0.1"
    )
    print(f"Step 0.1 apt packages: {installed_step01}/{total_step01} installed")
    print(f"Wrote {csv_path.name}, pip_freeze.txt, npm_global.json, snapshot_meta.json")


if __name__ == "__main__":
    main()
