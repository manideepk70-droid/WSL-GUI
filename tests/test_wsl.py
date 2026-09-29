import json
from pathlib import Path

import pytest

from wsl_gui.layers import LayerError, PACKAGE_MANAGERS, import_layer, layer_from_dict, load_layers
from wsl_gui.wsl import CommandResult, Wsl, WslError, decode_output, parse_list_online, parse_list_verbose

VERBOSE = """  NAME            STATE           VERSION
* Ubuntu          Running         2
  Debian          Stopped         2
"""
ONLINE = """The following is a list of valid distributions that can be installed.
Install using 'wsl.exe --install <Distro>'.

NAME                            FRIENDLY NAME
Ubuntu                          Ubuntu
Debian                          Debian GNU/Linux
kali-linux                      Kali Linux Rolling
"""


def test_decode_utf16():
    assert decode_output("hi\n".encode("utf-16-le")) == "hi\n"
    assert decode_output(b"\xff\xfe" + "hi".encode("utf-16-le")).lstrip("﻿") == "hi"
    assert decode_output(b"hello") == "hello"


def test_parse_verbose():
    d = parse_list_verbose(VERBOSE)
    assert [(x.name, x.state, x.version, x.default) for x in d] == [
        ("Ubuntu", "Running", 2, True), ("Debian", "Stopped", 2, False)]


def test_parse_online():
    o = parse_list_online(ONLINE)
    assert [x.name for x in o] == ["Ubuntu", "Debian", "kali-linux"]
    assert o[1].friendly_name == "Debian GNU/Linux"


def test_wsl_calls_and_errors():
    calls = []

    def runner(args, stdin):
        calls.append(list(args))
        return CommandResult(1, "", "boom") if "--terminate" in args else CommandResult(0, VERBOSE)

    w = Wsl(runner)
    assert len(w.list_installed()) == 2
    w.set_default("Debian")
    assert calls[-1] == ["wsl.exe", "--set-default", "Debian"]
    with pytest.raises(WslError, match="boom"):
        w.terminate("Debian")


def test_detect_package_manager():
    def runner(args, stdin):
        return CommandResult(0 if "command -v dnf" in args[-1] else 1, "")

    assert Wsl(runner).detect_package_manager("Fedora") == "dnf"


def test_builtin_layers_valid():
    layers = load_layers(Path("/nonexistent"))
    assert {"xfce", "kde", "gnome", "lxqt", "weston", "wslg-apps"} <= {l.id for l in layers}
    for l in layers:
        assert set(l.install) <= set(PACKAGE_MANAGERS)
        assert l.install_command("apt")


def test_layer_validation_and_import(tmp_path):
    with pytest.raises(LayerError):
        layer_from_dict({"id": "../x", "name": "x", "launch": "x"})
    with pytest.raises(LayerError):
        layer_from_dict({"id": "x", "name": "x", "launch": "x", "install": {"yum": "y"}})
    src = tmp_path / "my.json"
    src.write_text(json.dumps({"id": "sway", "name": "Sway", "launch": "sway", "install": {"apt": "apt-get install -y sway"}}))
    user = tmp_path / "user"
    import_layer(src, user)
    assert "sway" in {l.id for l in load_layers(user)}
    with pytest.raises(LayerError):
        layer_from_dict({"id": "sway", "name": "S", "launch": "s"}).install_command("apt")
