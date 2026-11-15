import json
from pathlib import Path

from converter.config import DEFAULTS, load_config, save_config


def test_load_defaults_when_missing(tmp_path: Path):
    cfg = load_config(tmp_path / "nope.json")
    assert cfg["preset"] == DEFAULTS["preset"]
    assert cfg["layout"] == "mirror"
    assert cfg["workers"] >= 1


def test_save_and_load_roundtrip(tmp_path: Path):
    p = tmp_path / "config.json"
    cfg = dict(DEFAULTS)
    cfg.update({"preset": "fast", "layout": "flat", "workers": 4,
                "text_only": True, "skip_existing": False,
                "output_folder": str(tmp_path / "Out")})
    save_config(cfg, p)
    assert p.exists()
    loaded = load_config(p)
    assert loaded["preset"] == "fast"
    assert loaded["layout"] == "flat"
    assert loaded["workers"] == 4
    assert loaded["text_only"] is True
    assert loaded["skip_existing"] is False


def test_corrupt_config_falls_back_to_defaults(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text("{ not json !!", encoding="utf-8")
    cfg = load_config(p)
    assert cfg["preset"] == DEFAULTS["preset"]


def test_partial_config_merges(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"preset": "best"}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["preset"] == "best"
    assert cfg["layout"] == DEFAULTS["layout"]
