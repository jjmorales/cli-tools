"""Settings: defaults, config-file loading and validation, hashing."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CONFIG_NAME = "convert-to-ascii.json"

# ---------------------------------------------------------------------------
# DEFAULTS - used for any key missing from the config file.
# Names/values match the controls on the page.
#   width/height: output columns / rows. Set one (the other follows the aspect
#                 ratio), both (the image is stretched to fit), but not neither.
#   ramp:         Standard | Detailed | Blocks | Terminal | Minimal | Binary
#   row_density:  Auto | 1.0 | 1.2 | 1.4 | 1.6 | 1.8
#   background:   Black | White   (also sets character polarity)
# ---------------------------------------------------------------------------
DEFAULTS = {
    "width": 100,
    "height": None,
    "ramp": "Standard",
    "contrast": 120,
    "brightness": 0,
    "background": "Black",
    "invert": False,
    "row_density": "1.2",  # fixed (not Auto) so output is identical run to run
    "input_dirs": ["gifs", "img"],  # relative to the config file's folder
    "output_dir_name": "ascii_json",  # created inside each input folder
}

# Keys that change the generated ASCII (and therefore the settings hash).
GEN_KEYS = ["width", "height", "ramp", "contrast", "brightness", "background", "invert", "row_density"]

RAMPS = ["Standard", "Detailed", "Blocks", "Terminal", "Minimal", "Binary"]
BACKGROUNDS = ["Black", "White"]
DENSITIES = ["Auto", "1.0", "1.2", "1.4", "1.6", "1.8"]


def write_default_config(path: Path):
    path.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")


def _int_or_none(cfg: dict, key: str, minimum: int):
    v = cfg[key]
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ValueError(f"{key}: must be a whole number >= {minimum} or null (got {v!r})")
    return v


def validate_config(cfg: dict) -> dict:
    unknown = sorted(set(cfg) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"unknown config key(s): {', '.join(unknown)}. Valid keys: {', '.join(DEFAULTS)}")
    cfg = {**DEFAULTS, **cfg}

    cfg["width"] = _int_or_none(cfg, "width", 1)
    cfg["height"] = _int_or_none(cfg, "height", 1)
    if cfg["width"] is None and cfg["height"] is None:
        raise ValueError("width and height cannot both be null")
    for key in ("contrast", "brightness"):
        if isinstance(cfg[key], bool) or not isinstance(cfg[key], (int, float)):
            raise ValueError(f"{key}: must be a number (got {cfg[key]!r})")

    def pick(key, options):
        got = str(cfg[key]).strip()
        match = next((o for o in options if o.lower() == got.lower()), None)
        if match is None:
            raise ValueError(f"{key}: {cfg[key]!r} is not valid. Options: {', '.join(options)}")
        cfg[key] = match

    pick("ramp", RAMPS)
    pick("background", BACKGROUNDS)
    if isinstance(cfg["row_density"], (int, float)) and not isinstance(cfg["row_density"], bool):
        cfg["row_density"] = f"{cfg['row_density']:.1f}"
    pick("row_density", DENSITIES)

    if not isinstance(cfg["invert"], bool):
        raise ValueError(f"invert: must be true or false (got {cfg['invert']!r})")
    if not isinstance(cfg["input_dirs"], list) or not all(isinstance(d, str) for d in cfg["input_dirs"]):
        raise ValueError("input_dirs: must be a list of folder paths")
    if not isinstance(cfg["output_dir_name"], str) or not cfg["output_dir_name"].strip():
        raise ValueError("output_dir_name: must be a non-empty folder name")
    return cfg


def load_config(path: Path | None) -> tuple[dict, Path]:
    """Returns (validated settings, base folder that input_dirs are relative to).

    path=None looks for ./convert-to-ascii.json in the current folder and falls
    back to the defaults (base = current folder) when there is none. An explicit
    path must exist.
    """
    explicit = path is not None
    path = path or (Path.cwd() / CONFIG_NAME)
    if not path.exists():
        if explicit:
            raise ValueError(f"config file not found: {path}")
        return validate_config({}), Path.cwd()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return validate_config(raw), path.resolve().parent


def settings_hash(settings: dict) -> str:
    subset = {k: settings[k] for k in GEN_KEYS}
    return hashlib.sha1(json.dumps(subset, sort_keys=True).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
