"""UI layers: pluggable desktop environments / window managers / apps launched via WSLg.

A layer is a JSON file. Built-ins ship in ``builtin_layers/``; users drop their own
into ``%APPDATA%/WSL-GUI/layers`` (or ``~/.config/wsl-gui/layers``) or import one from the GUI.
Fields:
  id, name, description
  install: {"apt": "...", "dnf": "...", "pacman": "...", "zypper": "...", "apk": "..."}
  launch:  shell command run inside the distro (as the regular user)
  mode:    "nested" (desktop in one window, uses Xephyr/weston) or "apps" (windows integrate with Windows via WSLg)
  requires: optional list of extra commands that must exist (e.g. ["Xephyr"])
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_MANAGERS = ("apt", "dnf", "pacman", "zypper", "apk")
MODES = ("nested", "apps")


class LayerError(ValueError):
    pass


@dataclass(frozen=True)
class UILayer:
    id: str
    name: str
    launch: str
    install: dict[str, str] = field(default_factory=dict)
    description: str = ""
    mode: str = "apps"
    builtin: bool = False

    def install_command(self, pm: str) -> str:
        try:
            return self.install[pm]
        except KeyError:
            raise LayerError(f"Layer '{self.name}' has no install recipe for '{pm}'") from None

    def launch_command(self) -> str:
        return self.launch


def layer_from_dict(data: dict, builtin: bool = False) -> UILayer:
    for key in ("id", "name", "launch"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise LayerError(f"Layer is missing required string field '{key}'")
    lid = data["id"].strip()
    if not all(c.isalnum() or c in "-_" for c in lid):
        raise LayerError("Layer id may only contain letters, digits, '-' and '_'")
    install = data.get("install", {})
    if not isinstance(install, dict) or any(
        k not in PACKAGE_MANAGERS or not isinstance(v, str) for k, v in install.items()
    ):
        raise LayerError(f"'install' must map {', '.join(PACKAGE_MANAGERS)} to shell commands")
    mode = data.get("mode", "apps")
    if mode not in MODES:
        raise LayerError(f"'mode' must be one of {MODES}")
    return UILayer(lid, data["name"], data["launch"], install, data.get("description", ""), mode, builtin)


def user_layers_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "WSL-GUI" / "layers"
    return Path.home() / ".config" / "wsl-gui" / "layers"


def _load_dir(path: Path, builtin: bool) -> dict[str, UILayer]:
    layers: dict[str, UILayer] = {}
    if not path.is_dir():
        return layers
    for f in sorted(path.glob("*.json")):
        try:
            layer = layer_from_dict(json.loads(f.read_text(encoding="utf-8")), builtin)
        except (OSError, ValueError) as e:  # bad user file must not break the app
            print(f"Skipping layer file {f}: {e}")
            continue
        layers[layer.id] = layer
    return layers


def load_layers(user_dir: Path | None = None) -> list[UILayer]:
    """Built-ins first; a user layer with the same id overrides the built-in."""
    layers = _load_dir(Path(__file__).parent / "builtin_layers", True)
    layers.update(_load_dir(user_dir or user_layers_dir(), False))
    return list(layers.values())


def import_layer(src: Path, user_dir: Path | None = None) -> UILayer:
    layer = layer_from_dict(json.loads(src.read_text(encoding="utf-8")))
    dest = user_dir or user_layers_dir()
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{layer.id}.json").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return layer
