"""Thin, testable wrapper around ``wsl.exe``."""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterator, Sequence

CREATE_NO_WINDOW = 0x08000000


class WslError(RuntimeError):
    pass


@dataclass(frozen=True)
class Distro:
    name: str
    state: str
    version: int
    default: bool = False


@dataclass(frozen=True)
class OnlineDistro:
    name: str
    friendly_name: str


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str], bytes | None], CommandResult]


def decode_output(raw: bytes) -> str:
    """wsl.exe management commands emit UTF-16LE; commands run inside a distro emit UTF-8."""
    if not raw:
        return ""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    # UTF-16LE without BOM: ASCII text has a NUL every other byte.
    if len(raw) >= 2 and raw[1:2] == b"\x00" and raw.count(b"\x00") >= len(raw) // 3:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def default_runner(args: Sequence[str], stdin: bytes | None = None) -> CommandResult:
    flags = CREATE_NO_WINDOW if hasattr(subprocess, "STARTUPINFO") else 0
    try:
        p = subprocess.run(
            list(args), input=stdin, capture_output=True, creationflags=flags
        )
    except FileNotFoundError as e:
        raise WslError("wsl.exe was not found. Is WSL installed and enabled?") from e
    return CommandResult(p.returncode, decode_output(p.stdout), decode_output(p.stderr))


def parse_list_verbose(text: str) -> list[Distro]:
    distros = []
    for line in text.replace("\x00", "").splitlines():
        if not line.strip() or re.match(r"\s*\*?\s*NAME\s+STATE", line):
            continue
        default = line.lstrip().startswith("*")
        parts = line.replace("*", " ", 1).split()
        if len(parts) < 3 or not parts[-1].isdigit():
            continue
        distros.append(Distro(parts[0], parts[1], int(parts[-1]), default))
    return distros


def parse_list_online(text: str) -> list[OnlineDistro]:
    out, in_table = [], False
    for line in text.replace("\x00", "").splitlines():
        if re.match(r"\s*NAME\s+FRIENDLY NAME", line):
            in_table = True
            continue
        if not in_table or not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            out.append(OnlineDistro(parts[0], parts[1].strip()))
    return out


class Wsl:
    def __init__(self, runner: Runner = default_runner, exe: str = "wsl.exe"):
        self.runner = runner
        self.exe = exe

    def _run(self, *args: str, check: bool = True, stdin: bytes | None = None) -> CommandResult:
        r = self.runner([self.exe, *args], stdin)
        if check and not r.ok:
            raise WslError((r.stderr or r.stdout).strip() or f"wsl {' '.join(args)} failed")
        return r

    # --- distro management -------------------------------------------------
    def list_installed(self) -> list[Distro]:
        r = self._run("--list", "--verbose", check=False)
        return parse_list_verbose(r.stdout)

    def list_online(self) -> list[OnlineDistro]:
        return parse_list_online(self._run("--list", "--online").stdout)

    def install(self, name: str) -> CommandResult:
        return self._run("--install", "--distribution", name, "--no-launch")

    def set_default(self, name: str) -> None:
        self._run("--set-default", name)

    def terminate(self, name: str) -> None:
        self._run("--terminate", name)

    def shutdown(self) -> None:
        self._run("--shutdown")

    def unregister(self, name: str) -> None:
        self._run("--unregister", name)

    def export(self, name: str, path: str) -> None:
        self._run("--export", name, path)

    def import_distro(self, name: str, install_dir: str, tar_path: str) -> None:
        self._run("--import", name, install_dir, tar_path)

    def update(self) -> CommandResult:
        return self._run("--update")

    # --- running things inside a distro -----------------------------------
    def shell_args(self, distro: str, command: str, user: str | None = None) -> list[str]:
        args = [self.exe, "-d", distro]
        if user:
            args += ["-u", user]
        return args + ["--", "sh", "-c", command]

    def run(self, distro: str, command: str, user: str | None = None) -> CommandResult:
        return self.runner(self.shell_args(distro, command, user), None)

    def stream(self, distro: str, command: str, user: str | None = None) -> Iterator[str]:
        """Yield output lines live; raise WslError on non-zero exit."""
        p = subprocess.Popen(
            self.shell_args(distro, command, user),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW if hasattr(subprocess, "STARTUPINFO") else 0,
        )
        assert p.stdout
        for raw in iter(p.stdout.readline, b""):
            yield raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if p.wait() != 0:
            raise WslError(f"command exited with status {p.returncode}")

    def spawn_gui(self, distro: str, command: str) -> subprocess.Popen:
        """Start a long-running command (GUI app / desktop) without waiting for it."""
        return subprocess.Popen(
            self.shell_args(distro, command),
            creationflags=CREATE_NO_WINDOW if hasattr(subprocess, "STARTUPINFO") else 0,
        )

    def open_terminal(self, distro: str) -> subprocess.Popen:
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        return subprocess.Popen([self.exe, "-d", distro], creationflags=flags)

    def detect_package_manager(self, distro: str) -> str | None:
        for pm in ("apt-get", "dnf", "pacman", "zypper", "apk"):
            if self.run(distro, f"command -v {pm}", user="root").ok:
                return {"apt-get": "apt"}.get(pm, pm)
        return None

    def has_command(self, distro: str, cmd: str) -> bool:
        return self.run(distro, f"command -v {shlex.quote(cmd)}").ok

    def wslg_available(self, distro: str) -> bool:
        return self.run(distro, "test -d /mnt/wslg").ok

    @staticmethod
    def explorer_path(distro: str) -> str:
        return rf"\\wsl.localhost\{distro}"
