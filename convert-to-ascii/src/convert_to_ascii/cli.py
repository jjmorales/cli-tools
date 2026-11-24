"""Command-line interface.

    convert-to-ascii                  convert everything in the configured folders
    convert-to-ascii install          one-time download of the Chromium browser
    convert-to-ascii --init-config    write a default convert-to-ascii.json here
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__
from .config import (
    BACKGROUNDS,
    CONFIG_NAME,
    GEN_KEYS,
    load_config,
    settings_hash,
    file_hash,
    validate_config,
    write_default_config,
)
from .convert import URL, apply_settings, convert_file, find_inputs
from .versioning import plan_output


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="convert-to-ascii",
        description="Convert GIFs and images to per-frame ASCII JSON via ascii-magic.com. "
        "Run `convert-to-ascii install` once first to download the browser.",
    )
    p.add_argument("folders", nargs="*", type=Path,
                   help="input folders (default: input_dirs from the config file)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--config", type=Path,
                   help=f"config file (default: ./{CONFIG_NAME} if it exists, else built-in defaults)")
    p.add_argument("--init-config", action="store_true",
                   help=f"write a default config file (./{CONFIG_NAME}) if missing, then exit")
    p.add_argument("--out", type=Path,
                   help="put all output in this one folder (default: <input folder>/<output_dir_name>)")
    p.add_argument("-r", "--recursive", action="store_true", help="also scan subfolders")
    p.add_argument("--force", action="store_true",
                   help="regenerate in place when identical output already exists (instead of skipping)")
    p.add_argument("--headed", action="store_true", help="show the browser window")
    p.add_argument("--settle-ms", type=int, default=500,
                   help="how long an unchanged output is waited on before treating a frame as identical to the previous one")
    p.add_argument("--timeout-ms", type=int, default=20000, help="per-frame render timeout")
    p.add_argument("--chrome-path", help="use this Chrome/Chromium executable instead of Playwright's bundled one")
    p.add_argument("--url", default=URL, help=argparse.SUPPRESS)
    p.add_argument("--indent", type=int, default=None, help="pretty-print JSON with this indent (default: compact)")
    # settings overrides (None = use the config file)
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--ramp")
    p.add_argument("--contrast", type=int)
    p.add_argument("--brightness", type=int)
    p.add_argument("--background", choices=BACKGROUNDS)
    p.add_argument("--row-density")
    p.add_argument("--invert", action=argparse.BooleanOptionalAction, default=None)
    return p.parse_args(argv)


def install_browser() -> int:
    """Download the Chromium build Playwright drives."""
    print("Installing Chromium for Playwright...")
    return subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "install":
        sys.exit(install_browser())
    args = parse_args(argv)

    if args.init_config:
        path = args.config or Path.cwd() / CONFIG_NAME
        if path.exists():
            print(f"{path} already exists; not overwriting.")
        else:
            write_default_config(path)
            print(f"Wrote default config: {path}")
        return

    try:
        cfg, base_dir = load_config(args.config)
        overrides = {
            k: getattr(args, k) for k in GEN_KEYS if getattr(args, k, None) is not None
        }
        settings = validate_config({**cfg, **overrides})
    except ValueError as e:
        sys.exit(f"Config error: {e}")

    folders = args.folders or [base_dir / d for d in settings["input_dirs"]]
    for f in folders:
        if not f.exists() and not args.folders:
            f.mkdir(parents=True, exist_ok=True)  # e.g. a fresh gifs/ or img/ folder
        if not f.is_dir():
            sys.exit(f"Not a folder: {f}")

    sethash = settings_hash(settings)
    jobs = []  # (src, out_dir, action, target, version, source_hash)
    claimed: dict[tuple[Path, str], Path] = {}
    for folder in folders:
        out_dir = args.out or (folder / settings["output_dir_name"])
        for src in find_inputs(folder, args.recursive):
            if src.parent.name == settings["output_dir_name"]:
                continue
            key = (out_dir.resolve(), src.stem)
            if key in claimed:
                print(f"! skipping {src}: same name as {claimed[key]} (output would collide)", file=sys.stderr)
                continue
            claimed[key] = src
            shash = file_hash(src)
            action, target, version = plan_output(out_dir, src, shash, sethash, args.force)
            jobs.append((src, out_dir, action, target, version, shash))

    if not jobs:
        sys.exit("No images or GIFs found in: " + ", ".join(str(f) for f in folders))
    todo = [j for j in jobs if j[2] != "skip"]
    print(f"{len(jobs)} file(s) found, {len(jobs) - len(todo)} up to date, {len(todo)} to convert")
    for src, _o, action, target, _v, _h in jobs:
        if action == "skip":
            print(f"  skip   {src.name} (already generated with these settings: {target.name})")
    if not todo:
        return

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    failures = []
    with tempfile.TemporaryDirectory(prefix="convert_to_ascii_") as tmp, sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=not args.headed, executable_path=args.chrome_path)
        except PlaywrightError as e:
            if "Executable doesn't exist" in str(e):
                sys.exit("Chromium is not installed. Run once:  convert-to-ascii install")
            raise
        page = browser.new_context(viewport={"width": 1440, "height": 1000}).new_page()
        page.goto(args.url, wait_until="domcontentloaded")
        page.get_by_role("button", name="Reset settings").wait_for(timeout=30000)
        apply_settings(page, settings)

        for n, (src, out_dir, action, target, version, shash) in enumerate(todo, 1):
            label = "regenerate" if action == "overwrite" else f"v{version}"
            print(f"[{n}/{len(todo)}] {src.name} ({label})")
            try:
                result = convert_file(page, src, settings, args, Path(tmp))
                result["version"] = version
                result["source_hash"] = shash
                result["settings_hash"] = sethash
                out_dir.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(result, ensure_ascii=False, indent=args.indent), encoding="utf-8")
                print(f"  -> {target} ({result['frame_count']} frame(s))")
            except Exception as e:  # keep going; report at the end
                failures.append((src.name, e))
                print(f"  FAILED: {e}", file=sys.stderr)
        browser.close()

    if failures:
        print(f"\n{len(failures)} failed:", file=sys.stderr)
        for name, err in failures:
            print(f"  {name}: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
