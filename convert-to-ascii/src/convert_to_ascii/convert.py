"""Frame extraction and driving the ascii-magic.com page with Playwright."""
from __future__ import annotations

import hashlib
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence
from playwright.sync_api import Page

from .config import GEN_KEYS

URL = "https://www.ascii-magic.com/tools/image-to-ascii"
IMAGE_EXTS = {".gif", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}
CALIBRATION_WIDTH = 100  # column count used to measure the page's rows-per-aspect factor
STATS_RE = re.compile(r"^\s*(\d[\d,]*) x (\d[\d,]*) characters\s*$")


# ----------------------------------------------------------------------------
# Input -> frames
# ----------------------------------------------------------------------------
def find_inputs(folder: Path, recursive: bool):
    it = folder.rglob("*") if recursive else folder.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def extract_frames(src_path: Path, out_dir: Path, matte: str):
    """Split a GIF/image into full-canvas PNGs. Returns (frames, info).

    frames: list of dicts {path, duration_ms, digest}
    Transparent pixels are flattened onto `matte` ("black" or "white") so they
    read as background rather than as whatever colour is hiding under alpha.
    """
    is_gif = src_path.suffix.lower() == ".gif"
    frames = []
    with Image.open(src_path) as im:
        info = {"loop": im.info.get("loop") if is_gif else None, "size": list(im.size)}
        default_ms = 100 if is_gif else 0
        for i, frame in enumerate(ImageSequence.Iterator(im)):
            duration = int(frame.info.get("duration", im.info.get("duration", default_ms)) or default_ms)
            rgba = frame.convert("RGBA")
            if not is_gif:
                rgba = ImageOps.exif_transpose(rgba)
            flat = Image.new("RGBA", rgba.size, matte)
            flat.alpha_composite(rgba)
            rgb = flat.convert("RGB")
            if i == 0:
                info["size"] = list(rgb.size)
            path = out_dir / f"{src_path.stem}_{i:04d}.png"
            rgb.save(path, format="PNG")
            frames.append(
                {
                    "path": path,
                    "duration_ms": duration,
                    "digest": hashlib.sha1(rgb.tobytes()).hexdigest(),
                }
            )
    return frames, info


def resize_png(src: Path, dst: Path, size: tuple[int, int]):
    with Image.open(src) as im:
        im.resize(size, Image.LANCZOS).save(dst, format="PNG")


# ----------------------------------------------------------------------------
# Page driving
# ----------------------------------------------------------------------------
def set_slider(page: Page, name_prefix: str, value: int):
    slider = page.get_by_role("slider", name=re.compile(rf"^{name_prefix}"))
    slider.evaluate(
        """(el, v) => {
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(el, String(v));
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        value,
    )
    got = slider.input_value()
    if str(got) != str(value):
        raise RuntimeError(f"Could not set {name_prefix} to {value} (slider says {got})")


def slider_range(page: Page, name_prefix: str):
    slider = page.get_by_role("slider", name=re.compile(rf"^{name_prefix}"))
    return int(float(slider.get_attribute("min"))), int(float(slider.get_attribute("max")))


def select_by_prefix(page: Page, combo_name_prefix: str, wanted: str):
    combo = page.get_by_role("combobox", name=re.compile(rf"^{combo_name_prefix}"))
    options = combo.locator("option").all_inner_texts()
    match = next((o for o in options if o.strip().lower().startswith(wanted.lower())), None)
    if match is None:
        raise RuntimeError(f"{combo_name_prefix}: no option starting with {wanted!r}. Options: {options}")
    combo.select_option(label=match)


def apply_settings(page: Page, s: dict):
    page.get_by_role("button", name="Reset settings").click()
    page.wait_for_timeout(150)

    # The page has a width slider but no height control. A height-only config
    # starts at a calibration width and is corrected per file (see plan_geometry).
    set_slider(page, "Output width", s["width"] or CALIBRATION_WIDTH)
    set_slider(page, "Contrast", s["contrast"])
    set_slider(page, "Brightness", s["brightness"])

    select_by_prefix(page, "Character ramp", s["ramp"])

    density = str(s["row_density"])
    select_by_prefix(page, "Row density", density if density.lower() == "auto" else f"Line height {density}")

    # Scope to the Background group: "Black"/"White" buttons also exist under Character colour.
    page.get_by_role("group", name="Background").get_by_role("button", name=s["background"], exact=True).click()

    invert_btn = page.get_by_role("button", name=re.compile(r"^Invert light and dark"))
    label = f"{invert_btn.inner_text()} {invert_btn.get_attribute('aria-label') or ''}".upper()
    is_on = bool(re.search(r"\bON\b", label)) and not re.search(r"\bOFF\b", label)
    if is_on != bool(s["invert"]):
        invert_btn.click()

    page.wait_for_timeout(250)


def read_stats(page: Page):
    """Returns (cols, rows) from the '100 x 89 characters' line, or None."""
    loc = page.get_by_text(re.compile(r"^\s*\d[\d,]* x \d[\d,]* characters\s*$"))
    if loc.count() == 0:
        return None
    m = STATS_RE.match(loc.first.inner_text())
    if not m:
        return None
    return int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))


def upload(page: Page, path: Path):
    file_input = page.locator('input[type="file"]')
    if file_input.count() > 0:
        file_input.first.set_input_files(str(path))
    else:  # fall back to the visible "Choose image" button
        with page.expect_file_chooser() as fc:
            page.get_by_role("button", name="Choose image").click()
        fc.value.set_files(str(path))


def wait_for_render(page: Page, prev: str | None, settle_ms: int, timeout_ms: int) -> str:
    """Wait until the output reflects the newly uploaded image.

    - Normal case: output text changes, then holds steady for one short re-read.
    - Identical-to-previous frame: no change will ever happen, so if the text is
      still unchanged after `settle_ms` we accept it as the same art.
    """
    out = page.locator('[aria-label="ASCII output"]')
    start = time.monotonic()
    while True:
        text = out.inner_text()
        elapsed_ms = (time.monotonic() - start) * 1000
        if text and text != prev:
            time.sleep(0.1)
            if out.inner_text() == text:  # stable -> render finished
                return text
        elif text and prev is not None and text == prev and elapsed_ms >= settle_ms:
            return text
        if elapsed_ms > timeout_ms:
            raise TimeoutError("Timed out waiting for the converter to render this frame")
        time.sleep(0.04)


def render_stats(page: Page, path: Path, prev_text: str, args):
    """Upload one image; returns (text, cols, rows)."""
    upload(page, path)
    text = wait_for_render(page, prev_text, args.settle_ms, args.timeout_ms)
    stats = read_stats(page)
    if not stats:
        raise RuntimeError("Could not read the 'N x M characters' line from the page")
    return text, stats[0], stats[1]


def plan_geometry(page: Page, frames: list, size: list, settings: dict, tmp_dir: Path, args, prev_text: str):
    """Make the output come out at the requested width/height.

    The page only controls width; rows follow the image's aspect ratio. To honour
    a height we measure how many rows the page produces for this image (k = rows
    per column-per-aspect), then either pick the width that gives the requested
    rows (height only) or stretch the frames to the aspect that gives them (both).

    Returns (prev_text, effective_width).
    """
    width, height = settings["width"], settings["height"]
    if not height:
        return prev_text, width

    w, h = size
    first = frames[0]["path"]
    prev_text, cols0, rows0 = render_stats(page, first, prev_text, args)
    k = rows0 / (cols0 * h / w)  # rows = cols * k * (img_h / img_w)

    if width is None:
        lo, hi = slider_range(page, "Output width")
        eff_w = min(max(round(height / (k * h / w)), lo), hi)
        if eff_w != cols0:
            set_slider(page, "Output width", eff_w)
            page.wait_for_timeout(250)
        return page.locator('[aria-label="ASCII output"]').inner_text(), eff_w

    # Both given: stretch frames so the rows land on `height`.
    new_h = max(1, round(height * w / (width * k)))
    probe = tmp_dir / "_probe.png"
    for _ in range(6):
        resize_png(first, probe, (w, new_h))
        prev_text, _cols, rows = render_stats(page, probe, prev_text, args)
        if rows == height:
            break
        new_h = max(1, new_h + (1 if rows < height else -1))
    else:
        print(f"  ! could not hit exactly {height} rows (got {rows})", file=sys.stderr)
    for fr in frames:
        resize_png(fr["path"], fr["path"], (w, new_h))
    return prev_text, width


def convert_file(page: Page, src_path: Path, settings: dict, args, tmp_root: Path):
    matte = "white" if settings["background"].lower() == "white" else "black"
    frame_dir = tmp_root / src_path.stem
    frame_dir.mkdir(parents=True, exist_ok=True)
    frames, info = extract_frames(src_path, frame_dir, matte)

    prev_text = page.locator('[aria-label="ASCII output"]').inner_text()
    prev_text, eff_width = plan_geometry(page, frames, info["size"], settings, frame_dir, args, prev_text)

    out_frames = []
    cache: dict[str, str] = {}  # digest -> ascii, so repeated frames skip the browser
    ascii_size = None

    for i, fr in enumerate(frames):
        if fr["digest"] in cache:
            text = cache[fr["digest"]]
        else:
            upload(page, fr["path"])
            text = wait_for_render(page, prev_text, args.settle_ms, args.timeout_ms)
            stats = read_stats(page)
            if stats:
                ascii_size = {"cols": stats[0], "rows": stats[1]}
                if eff_width and stats[0] != eff_width:
                    print(f"  ! frame {i}: width {stats[0]} != requested {eff_width}", file=sys.stderr)
                if settings["height"] and stats[1] != settings["height"]:
                    print(f"  ! frame {i}: height {stats[1]} != requested {settings['height']}", file=sys.stderr)
            cache[fr["digest"]] = text
            prev_text = text
        out_frames.append(
            {
                "frame": i,
                "label": f"frame_{i:04d}",
                "duration_ms": fr["duration_ms"],
                "ascii": text,
            }
        )
        print(f"  frame {i + 1}/{len(frames)}", end="\r", flush=True)
    print()

    return {
        "format": "ascii-animation/v1",
        "source": src_path.name,
        "source_type": "gif" if src_path.suffix.lower() == ".gif" else "image",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": URL,
        "frame_count": len(out_frames),
        "loop": info["loop"],
        "pixel_size": info["size"],
        "ascii_size": ascii_size,
        "settings": {k: settings[k] for k in GEN_KEYS},
        "frames": out_frames,
    }
