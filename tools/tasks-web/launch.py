#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Open the local actions page, starting its server first when it is not running (macOS, Windows, Linux).

Run from Work with: uv run --script tools/tasks-web/launch.py
The entries that install-app.py creates (macOS app, Windows shortcut, Linux .desktop file) and launcher.sh run it.
Standard library only.

1. When http://127.0.0.1:8765/api/actions answers like the actions server, open the page in the default browser.
2. When another program owns port 8765, wait 5 seconds for it to become the actions server, else refuse:
   never a second server, never someone else's page.
3. Otherwise start `uv run tools/tasks-web/tasks-web.py --port 8765` from the Work root, detached (its own session
   on macOS and Linux; on Windows its own process group and a console with no window, so neither it nor the Git
   and uv commands it runs ever show a window), output in agents/tasks-web.log, PID in agents/tasks-web.pid; wait up
   to 10 seconds for it to answer, then open the page.

uv is the one running this script (the UV variable uv sets), else the one on PATH, else the usual install places.
An error goes to stderr, to agents/tasks-web.log and to a native dialog (osascript on macOS, a message box on
Windows, zenity, kdialog or notify-send on Linux); --no-dialog leaves the dialog out (the macOS app shows its own).
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

WORK = Path(__file__).resolve().parents[2]
SERVER_SCRIPT = Path("tools/tasks-web/tasks-web.py")
PORT = 8765
HOST = "127.0.0.1"
TITLE = "Actions Brain"
BUSY_ATTEMPTS = 25  # x DELAY: how long a busy port may take to become the actions server
START_ATTEMPTS = 50  # x DELAY: how long a new server may take to answer
DELAY = 0.2
SHELL_PATH_TIMEOUT = 4.0  # seconds to read the login shell's PATH; a slow shell startup only costs that, once per start
PATH_MARK = "__ACTIONS_PATH__="  # marks the PATH line among whatever the shell's startup files print
# Windows process creation flags (subprocess has them only on Windows).
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
MB_ICONERROR, MB_SETFOREGROUND = 0x10, 0x10000


class LaunchError(Exception):
    """A reason the page cannot be opened, said to the user."""


def system_name(platform: str | None = None) -> str:
    """'macos', 'windows' or 'linux' (any other POSIX system counts as linux)."""
    platform = platform or sys.platform
    if platform == "darwin":
        return "macos"
    return "windows" if platform.startswith(("win", "cygwin", "msys")) else "linux"


def page_url(port: int = PORT) -> str:
    return f"http://{HOST}:{port}/"


def ready(port: int = PORT, timeout: float = 2.0) -> bool:
    """True when /api/actions answers 200 with the keys of the actions server (no proxy, like `curl --noproxy '*'`)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{page_url(port)}api/actions", timeout=timeout) as response:
            if response.status != 200:
                return False
            body = response.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return False
    return '"actions"' in body and '"registers"' in body


def port_owned(port: int = PORT) -> bool:
    """True when a program accepts connections on 127.0.0.1:<port>."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            return probe.connect_ex((HOST, port)) == 0
        except OSError:
            return False


def uv_candidates(system: str, environ: dict[str, str] | None = None, home: Path | None = None) -> list[Path]:
    """The usual install places of uv on this kind of system, most likely first (they may not exist)."""
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else home
    exe = "uv.exe" if system == "windows" else "uv"
    places: list[Path] = []
    for variable in ("UV_INSTALL_DIR", "XDG_BIN_HOME"):
        if environ.get(variable):
            places += [Path(environ[variable]) / exe, Path(environ[variable]) / "bin" / exe]
    if system == "windows":
        profile = Path(environ["USERPROFILE"]) if environ.get("USERPROFILE") else home
        places += [profile / ".local/bin" / exe, profile / ".cargo/bin" / exe, profile / "scoop/shims" / exe]
        if environ.get("LOCALAPPDATA"):
            local = Path(environ["LOCALAPPDATA"])
            places += [local / "Microsoft/WinGet/Links" / exe, local / "Programs/uv" / exe, local / "uv/bin" / exe]
        if environ.get("ProgramData"):
            places.append(Path(environ["ProgramData"]) / "chocolatey/bin" / exe)
        return places
    places += [home / ".local/bin" / exe, home / ".cargo/bin" / exe]
    if system == "macos":
        places += [Path("/opt/homebrew/bin") / exe, Path("/usr/local/bin") / exe]
    else:
        places += [Path("/usr/local/bin") / exe, Path("/usr/bin") / exe, Path("/home/linuxbrew/.linuxbrew/bin") / exe,
                   Path("/snap/bin") / exe]
    return places


def console_uv(path: Path) -> Path:
    """uv.exe for a windowless uvw.exe that has one next to it: a server needs the console build."""
    sibling = path.with_name("uv.exe")
    return sibling if path.name.lower() == "uvw.exe" and sibling.is_file() else path


def find_uv(environ: dict[str, str] | None = None, system: str | None = None, home: Path | None = None) -> str | None:
    """Absolute path of uv: the one running this script (UV), else PATH, else the usual install places."""
    environ = os.environ if environ is None else environ
    system = system or system_name()
    found: list[Path] = []
    if environ.get("UV"):
        found.append(Path(environ["UV"]))
    on_path = shutil.which("uv", path=environ.get("PATH"))
    if on_path:
        found.append(Path(on_path))
    for path in (*found, *uv_candidates(system, environ, home)):
        if path.is_file():
            return str(console_uv(path).absolute())
    return None


def login_shell_path(system: str | None = None, environ: dict[str, str] | None = None, timeout: float = SHELL_PATH_TIMEOUT) -> list[str]:
    """The PATH of the user's interactive login shell (macOS, Linux); [] when it cannot be read.

    An app started from the Dock or a desktop entry gets only the system folders (/usr/bin:/bin:…), so the tools that
    Homebrew, nvm or the uv installer put elsewhere (uv, npx) would look missing to the server and the Settings view.
    """
    environ = os.environ if environ is None else environ
    system = system or system_name()
    if system == "windows":
        return []
    shell = environ.get("SHELL") or ("/bin/zsh" if system == "macos" else "/bin/sh")
    try:
        result = subprocess.run([shell, "-ilc", f'printf "\\n{PATH_MARK}%s\\n" "$PATH"'], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=timeout, env=dict(environ))
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    for line in reversed(result.stdout.splitlines()):
        if line.startswith(PATH_MARK):
            return [part for part in line[len(PATH_MARK):].split(os.pathsep) if part]
    return []


def tool_path(environ: dict[str, str] | None = None, system: str | None = None, home: Path | None = None, uv: str | None = None,
              shell_path=None) -> str:
    """The PATH given to the server: the login shell's first, then the current one, the folder of uv and the usual
    install places that exist (Homebrew, ~/.local/bin, ~/.cargo/bin, Volta), each folder once."""
    environ = os.environ if environ is None else environ
    system = system or system_name()
    home = Path.home() if home is None else home
    parts = [*(shell_path or login_shell_path)(system, environ), *environ.get("PATH", "").split(os.pathsep)]
    if uv:
        parts.append(str(Path(uv).parent))
    if system != "windows":
        usual = (home / ".local/bin", home / ".cargo/bin", home / ".volta/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin"))
        parts += [str(folder) for folder in usual if folder.is_dir()]
    return os.pathsep.join(dict.fromkeys(part for part in parts if part))


def utf8_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment with Python in UTF-8 mode, so the server's log and pipes are UTF-8 on every system."""
    environment = dict(os.environ if base is None else base)
    environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    return environment


def start_detached(command: list[str], cwd: Path, log: Path, environment: dict[str, str] | None = None) -> subprocess.Popen:
    """Start `command` so that it outlives this launcher and never holds its streams or its console."""
    options: dict = {"cwd": cwd, "env": environment or utf8_environment(), "stdin": subprocess.DEVNULL, "stderr": subprocess.STDOUT}
    with open(log, "wb") as output:
        options["stdout"] = output
        if os.name != "nt":
            return subprocess.Popen(command, start_new_session=True, **options)
        # A hidden console of its own (CREATE_NO_WINDOW): its child processes (Python, Git, uv) inherit it instead of
        # each opening a console window, which DETACHED_PROCESS would cause. Out of uv's job when the job allows it.
        flags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        try:
            return subprocess.Popen(command, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **options)
        except OSError:
            return subprocess.Popen(command, creationflags=flags, **options)


def open_page(port: int, opener) -> None:
    if not opener(page_url(port)):
        raise LaunchError(f"Could not open the browser. Open {page_url(port)} in your browser.")


def launch(port: int = PORT, work: Path = WORK, command: list[str] | None = None, opener=webbrowser.open,
           busy_attempts: int = BUSY_ATTEMPTS, start_attempts: int = START_ATTEMPTS, delay: float = DELAY) -> str:
    """Open the page, starting the server first when needed: 'opened' or 'started'. LaunchError when it cannot.

    `command` replaces the server command (tests); by default it is `<uv> run tools/tasks-web/tasks-web.py --port N`.
    """
    if ready(port):
        open_page(port, opener)
        return "opened"
    if port_owned(port):
        for _ in range(busy_attempts):
            if ready(port):
                open_page(port, opener)
                return "opened"
            time.sleep(delay)
        raise LaunchError(f"Port {port} is already used by another application. Close it before starting Actions.")
    uv = None
    if command is None:
        uv = find_uv()
        if uv is None:
            raise LaunchError("uv was not found. Install or restore uv, then start Actions again.")
        command = [uv, "run", str(work / SERVER_SCRIPT), "--port", str(port)]
    agents = work / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    environment = utf8_environment()
    environment["PATH"] = tool_path(uv=uv)  # the tools of the user's terminal, even when the Dock started this launcher
    try:
        process = start_detached(command, work, agents / "tasks-web.log", environment=environment)
    except OSError as error:
        raise LaunchError(f"Actions could not start: {error.strerror or error}.") from None
    (agents / "tasks-web.pid").write_text(f"{process.pid}\n", encoding="utf-8")
    for _ in range(start_attempts):
        if ready(port):
            open_page(port, opener)
            return "started"
        if process.poll() is not None and not port_owned(port):  # it stopped, and no other start (a double click) is under way
            break
        time.sleep(delay)
    raise LaunchError("Actions did not start. See agents/tasks-web.log in Work.")


def show_dialog(message: str, system: str | None = None) -> None:
    """The error in a native dialog, when the system has one; never raises."""
    system = system or system_name()
    try:
        if system == "macos":
            script = ("on run argv",
                      (f'display dialog (item 1 of argv) with title "{TITLE}" buttons {{"OK"}} default button "OK" with icon stop'),
                      "end run")
            subprocess.run(["/usr/bin/osascript", *(part for line in script for part in ("-e", line)), message],
                           stdin=subprocess.DEVNULL, capture_output=True, check=False)
        elif system == "windows":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, TITLE, MB_ICONERROR | MB_SETFOREGROUND)  # type: ignore[attr-defined]
        else:
            for argv in (["zenity", "--error", f"--title={TITLE}", "--no-markup", f"--text={message}"],
                         ["kdialog", "--title", TITLE, "--error", message],
                         ["notify-send", "--urgency=critical", TITLE, message]):
                if shutil.which(argv[0]):
                    subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, check=False)
                    return
    except Exception:  # noqa: BLE001, S110 - a dialog that fails must not hide the error, already on stderr and in the log
        pass


def report(message: str, work: Path, dialog: bool) -> None:
    """An error, on stderr, at the end of agents/tasks-web.log and, unless `dialog` is False, in a native dialog."""
    if sys.stderr is not None:  # None under a windowless interpreter (pythonw)
        print(message, file=sys.stderr)
    try:
        (work / "agents").mkdir(parents=True, exist_ok=True)
        with open(work / "agents/tasks-web.log", "a", encoding="utf-8") as log:
            log.write(f"[launch.py {datetime.now().isoformat(timespec='seconds')}] {message}\n")
    except OSError:
        pass
    if dialog:
        show_dialog(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=PORT, help=f"local port (default: {PORT})")
    parser.add_argument("--no-dialog", action="store_true", help="report an error on stderr and in the log only")
    args = parser.parse_args(argv)
    try:
        launch(args.port)
    except LaunchError as error:
        report(str(error), WORK, not args.no_dialog)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
