import json

import pytest

from convert_to_ascii.config import DEFAULTS, load_config, settings_hash, validate_config
from convert_to_ascii.versioning import plan_output, versioned_path


def test_defaults_are_valid():
    assert validate_config({}) == DEFAULTS


@pytest.mark.parametrize(
    "bad",
    [
        {"ramp": "Foo"},
        {"width": None, "height": None},
        {"width": 0},
        {"invert": "yes"},
        {"nonsense": 1},
    ],
)
def test_bad_config_rejected(bad):
    with pytest.raises(ValueError):
        validate_config(bad)


def test_case_insensitive_options_and_numeric_density():
    cfg = validate_config({"ramp": "blocks", "row_density": 1.4})
    assert cfg["ramp"] == "Blocks" and cfg["row_density"] == "1.4"


def test_load_config_default_and_explicit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg, base = load_config(None)
    assert cfg == DEFAULTS and base == tmp_path
    (tmp_path / "convert-to-ascii.json").write_text('{"width": 50}')
    cfg, base = load_config(None)
    assert cfg["width"] == 50
    with pytest.raises(ValueError):
        load_config(tmp_path / "missing.json")


def test_settings_hash_ignores_non_generation_keys():
    a = validate_config({})
    b = validate_config({"input_dirs": ["elsewhere"]})
    c = validate_config({"width": 80})
    assert settings_hash(a) == settings_hash(b) != settings_hash(c)


def _write(out_dir, src, version, shash, sethash):
    out_dir.mkdir(exist_ok=True)
    versioned_path(out_dir, src.stem, version).write_text(
        json.dumps({"source": src.name, "source_hash": shash, "settings_hash": sethash})
    )


def test_versioning(tmp_path):
    out, src = tmp_path / "out", tmp_path / "cat.gif"
    assert plan_output(out, src, "s1", "c1", False) == ("create", out / "cat.json", 1)
    _write(out, src, 1, "s1", "c1")
    assert plan_output(out, src, "s1", "c1", False)[0] == "skip"
    assert plan_output(out, src, "s1", "c1", True)[0] == "overwrite"
    # new settings -> next version, old one untouched
    assert plan_output(out, src, "s1", "c2", False) == ("create", out / "cat.v2.json", 2)
    _write(out, src, 2, "s1", "c2")
    # switching back reuses version 1; a changed source gets a new version
    assert plan_output(out, src, "s1", "c1", False)[2] == 1
    assert plan_output(out, src, "s2", "c1", False) == ("create", out / "cat.v3.json", 3)


def test_headerless_old_output_never_matches(tmp_path):
    out, src = tmp_path / "out", tmp_path / "cat.gif"
    out.mkdir()
    (out / "cat.json").write_text('{"format": "ascii-animation/v1"}')
    assert plan_output(out, src, "s1", "c1", False) == ("create", out / "cat.v2.json", 2)
