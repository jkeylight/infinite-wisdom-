"""Persistent settings — config.json next to the exe (portable, personal use).

No registry, no AppData, no telemetry. Copy the folder = settings travel with it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CONFIG_NAME = "config.json"

DEFAULTS = {
    "output_folder": "Converted",
    "layout": "mirror",
    "preset": "balanced",
    "workers": 0,  # 0 = auto (cores - 1)
    "text_only": False,
    "skip_existing": True,
}


def app_dir() -> Path:
    """Directory for config/log: exe folder when frozen, else current working dir."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def config_path() -> Path:
    return app_dir() / CONFIG_NAME


def load_config(path: Path | None = None) -> dict:
    cfg = dict(DEFAULTS)
    p = Path(path) if path else config_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: data[k] for k in DEFAULTS if k in data})
    except Exception:
        pass  # corrupt config -> defaults, never crash
    # Resolve relative output folder against app_dir for portability
    out = cfg.get("output_folder") or "Converted"
    if not Path(out).is_absolute():
        cfg["output_folder"] = str(app_dir() / out)
    if not cfg.get("workers"):
        cfg["workers"] = max(1, (os.cpu_count() or 2) - 1)
    return cfg


def save_config(cfg: dict, path: Path | None = None) -> None:
    p = Path(path) if path else config_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Store output as relative if under app_dir (portable across machines)
        data = dict(cfg)
        try:
            out = Path(data.get("output_folder", ""))
            if out.is_absolute():
                data["output_folder"] = str(out.relative_to(app_dir()))
        except ValueError:
            pass
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass  # never crash on save failure
