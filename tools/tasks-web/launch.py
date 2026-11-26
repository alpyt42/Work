#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Open Corvus (the local actions app), starting its server first when it is not running (macOS, Windows, Linux).

Run from Work with: uv run --script tools/tasks-web/launch.py
The entries that install-app.py creates (Windows shortcut, Linux .desktop file, the macOS bundle through --prepare-window)
and launcher.sh run it. Standard library only.

1. When http://127.0.0.1:8765/api/actions answers like the actions server, the page is opened (step 4).
2. When another program owns port 8765, wait 5 seconds for it to become the actions server, else refuse:
   never a second server, never someone else's page.
3. Otherwise start `uv run tools/tasks-web/tasks-web.py --port 8765` from the Work root, detached (its own session
   on macOS and Linux; on Windows its own process group and a console with no window, so neither it nor the Git
   and uv commands it runs ever show a window), output in agents/tasks-web.log (emptied first, then only appended to),
   PID in agents/tasks-web.pid (for information: nothing reads it); wait up to 10 seconds for it to answer, then open
   the page.
4. The page opens through a chain, the first step that works, each outcome written to agents/tasks-web.log:
   (a) the native window, tools/tasks-web/window.py (pywebview, run by uv; the first run downloads pywebview), on
       macOS and Windows. On macOS the Corvus.app that install-app.py built is opened first, by its path in the
       artifacts folder (never by bundle id, which an archived copy shares), and the launcher is done: the bundle
       shows its own window, or its own fallback. window.py is run directly only when that app is not there. Linux
       skips (a): uv's isolated environment cannot reach the system's GTK or Qt bindings;
   (b) a Chrome app window (`--app=URL`): Google Chrome, else Microsoft Edge, else Chromium or Brave;
   (c) the default browser.

Modes: --browser skips (a). --prepare-window (the macOS bundle) starts the server, makes sure window.py can run
(`window.py --check`, which may download pywebview) and prints only the path of the Python that runs it, for the bundle
to exec; when that fails it opens (b) or (c) itself and prints nothing.

uv is the one running this script (the UV variable uv sets), else the one on PATH, else the usual install places.
An error goes to stderr, to agents/tasks-web.log and to a native dialog (osascript on macOS, a message box on
Windows, zenity, kdialog or notify-send on Linux); --no-dialog leaves the dialog out.
"""

from __future__ import annotations

import argparse
import importlib.util
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
TITLE = "Corvus"
MAC_APP = Path("internal/setup/tasks-dock-app/Corvus.app")  # in the artifacts folder: where install-app.py builds it
WINDOW_SCRIPT = Path("tools/tasks-web/window.py")
WINDOW_WAIT = 20.0  # seconds a prepared window may take to show
WINDOW_FIRST_WAIT = 180.0  # the same when its environment is not prepared yet: uv may download pywebview
CHECK_TIMEOUT = 180.0  # seconds for `window.py --check`, which may download pywebview
READY_FILE = "tasks-web-window.ready"  # in agents/: window.py writes it once its window is shown
PREPARED_FILE = "tasks-web-window.prepared"  # in agents/: window.py has run here, so its environment is in uv's cache
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


def windowless_uv(uv: str | Path) -> Path | None:
    """Windows: the uvw.exe (no console window) next to uv.exe, else next to the file uv.exe links to (a WinGet link
    or a Scoop shim seen through a symlink); None when there is none."""
    path = Path(uv)
    places = [path.with_name("uvw.exe")]
    try:
        places.append(path.resolve().with_name("uvw.exe"))
    except (OSError, RuntimeError):  # a link loop, a drive that is gone
        pass
    return next((place for place in places if place.is_file()), None)


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


def start_detached(command: list[str], cwd: Path, log: Path, environment: dict[str, str] | None = None,
                   append: bool = False) -> subprocess.Popen:
    """Start `command` so that it outlives this launcher and never holds its streams or its console.

    Its output goes to `log`, which a fresh server start empties and the native window (`append`) only extends. The log
    is always written in append mode, so that the lines launch.py and window.py add later are not overwritten by it.
    """
    options: dict = {"cwd": cwd, "env": environment or utf8_environment(), "stdin": subprocess.DEVNULL, "stderr": subprocess.STDOUT}
    if not append:
        open(log, "wb").close()
    with open(log, "ab") as output:
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


def log_line(work: Path, message: str) -> None:
    """One line at the end of agents/tasks-web.log; never raises."""
    try:
        (work / "agents").mkdir(parents=True, exist_ok=True)
        with open(work / "agents/tasks-web.log", "a", encoding="utf-8") as log:
            log.write(f"[launch.py {datetime.now().isoformat(timespec='seconds')}] {message}\n")
    except OSError:
        pass


def open_page(port: int, opener) -> None:
    if not opener(page_url(port)):
        raise LaunchError(f"Could not open Corvus. Open {page_url(port)} in your browser.")


# --- the page: native window, else a Chrome app window, else the default browser

MAC_BROWSERS = ("Google Chrome", "Microsoft Edge", "Chromium", "Brave Browser")
LINUX_BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser")
WINDOWS_BROWSERS = ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe", "Chromium/Application/chrome.exe",
                    "BraveSoftware/Brave-Browser/Application/brave.exe")


def app_mode_command(url: str, system: str | None = None, environ: dict[str, str] | None = None, home: Path | None = None,
                     which=shutil.which, exists=Path.exists) -> list[str] | None:
    """The command that opens `url` as an app window (`--app=URL`: no tabs, no address bar) in Google Chrome, else
    Microsoft Edge, else Chromium or Brave; None when none of them is installed."""
    environ = os.environ if environ is None else environ
    system = system or system_name()
    home = Path.home() if home is None else home
    argument = f"--app={url}"
    if system == "macos":
        for name in MAC_BROWSERS:
            for folder in (Path("/Applications"), home / "Applications"):
                if exists(folder / f"{name}.app"):
                    return ["open", "-na", name, "--args", argument]
    elif system == "windows":
        roots = [Path(environ[name]) for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA") if environ.get(name)]
        for relative in WINDOWS_BROWSERS:
            for root in roots:
                if exists(root / relative):
                    return [str(root / relative), argument]
    else:
        for name in LINUX_BROWSERS:
            found = which(name, path=environ.get("PATH"))
            if found:
                return [found, argument]
    return None


def start_browser(command: list[str]) -> bool:
    """Run a browser command (macOS `open` is waited for, the others are detached); True when it started."""
    try:
        if command[0] == "open":
            return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False).returncode == 0
        options: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            options["creationflags"] = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        else:
            options["start_new_session"] = True
        subprocess.Popen(command, **options)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def open_fallback(url: str, work: Path = WORK, command_for=app_mode_command, starter=start_browser, browser=webbrowser.open) -> str:
    """Open the page without the native window: a Chrome app window ('app-mode'), else the default browser ('browser');
    '' when neither worked. The step used is written to agents/tasks-web.log."""
    command = command_for(url)
    if command is None:
        log_line(work, "No Chrome, Edge, Chromium or Brave found for an app window.")
    elif starter(command):
        log_line(work, f"Page opened in an app window: {command[2] if command[0] == 'open' else Path(command[0]).name}.")
        return "app-mode"
    else:
        log_line(work, f"The app window ({command[0]}) could not start.")
    if browser(url):
        log_line(work, "Page opened in the default browser.")
        return "browser"
    log_line(work, "The default browser did not open the page.")
    return ""


def window_command(uv: str, work: Path, port: int, system: str | None = None) -> list[str]:
    """`<uv> run --quiet --script window.py --port N --no-fallback` (launch.py runs the fallback itself); on Windows the
    windowless uvw.exe (`--gui-script`) when there is one."""
    system = system or system_name()
    program, flag = uv, "--script"
    windowless = windowless_uv(uv) if system == "windows" else None
    if windowless is not None:
        program, flag = str(windowless), "--gui-script"
    return [program, "run", "--quiet", flag, str(work / WINDOW_SCRIPT), "--port", str(port), "--no-fallback"]


def stop_process(process: subprocess.Popen) -> None:
    """Stop a window that did not show, with the children uv started; never raises."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, check=False)
        else:
            import signal

            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def artifacts_dir(work: Path) -> Path:
    """The artifacts folder of `work`, resolved as install-app.py does (tools/machine/work_config.py of this checkout)."""
    spec = importlib.util.spec_from_file_location("tasks_launch_work_config", WORK / "tools/machine/work_config.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.artifacts_dir(work)


def installed_app(work: Path = WORK, folder=artifacts_dir) -> Path | None:
    """macOS: the Corvus.app that install-app.py built in the artifacts folder; None when it is not there.

    Found by its path, never by its bundle id: LaunchServices may pick an archived copy (an "Actions Brain.app" or an
    older Corvus.app moved to archive/) that has the same id.
    """
    try:
        app = folder(work) / MAC_APP
    except Exception:  # noqa: BLE001 - an invalid configuration: no app to open, window.py runs instead
        return None
    return app if (app / "Contents/Info.plist").is_file() else None


def open_bundle(app: Path) -> bool:
    """macOS: `open <app>`: starts that Corvus.app, or activates it when it already runs; True when `open` succeeded."""
    try:
        return subprocess.run(["open", str(app)], stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
                              check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def open_native_window(port: int = PORT, work: Path = WORK, uv: str | None = None, starter=start_detached, wait: float | None = None,
                       delay: float = DELAY, system: str | None = None, stopper=stop_process, bundle_opener=open_bundle,
                       app_finder=installed_app) -> bool:
    """Open the native window; False (with the reason in the log) when it cannot show.

    macOS with the installed Corvus.app: open it and return True at once (the bundle shows its own window, or its own
    fallback). Linux: False (no native window). Otherwise run window.py detached and wait for its ready file. Without
    `wait` the wait is WINDOW_WAIT, or WINDOW_FIRST_WAIT while no window ever showed here, because uv may then download
    pywebview. A window.py that exits with 0 raised the window that was already open, or was closed at once.
    """
    system = system or system_name()
    if system == "linux":
        log_line(work, "Native window skipped: none on Linux (uv's environment has no GTK or Qt bindings).")
        return False
    if system == "macos":
        app = app_finder(work)
        if app is not None:
            if bundle_opener(app):
                log_line(work, f"Opened {app.name}: it shows the page in its own window.")
                return True
            log_line(work, f"{app.name} could not be opened: window.py runs directly.")
    agents = work / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    ready, prepared = agents / READY_FILE, agents / PREPARED_FILE
    first_run = not prepared.exists()
    wait = (WINDOW_FIRST_WAIT if first_run else WINDOW_WAIT) if wait is None else wait
    uv = uv or find_uv()
    if uv is None:
        log_line(work, "Native window skipped: uv was not found.")
        return False
    ready.unlink(missing_ok=True)
    environment = utf8_environment()
    environment["PATH"] = tool_path(uv=uv)
    try:
        process = starter(window_command(uv, work, port, system), work, agents / "tasks-web.log", environment=environment, append=True)
    except OSError as error:
        log_line(work, f"Native window skipped: it could not start ({error.strerror or error}).")
        return False
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if ready.exists():
            prepared.write_text("window.py ran here\n", encoding="utf-8")
            log_line(work, "Page opened in the native window.")
            return True
        code = process.poll()
        if code is not None:
            if code == 0:  # a second start: the window that was open has been raised
                log_line(work, "The native window was already open: it was raised.")
                return True
            log_line(work, f"Native window skipped: window.py stopped with code {code} (see above).")
            return False
        time.sleep(delay)
    stopper(process)
    if not first_run:
        prepared.unlink(missing_ok=True)  # the next start waits long again: uv's cache may have been cleared
    log_line(work, f"Native window skipped: it did not show within {wait:g} s.")
    return False


def default_opener(port: int, work: Path, native: bool = True):
    """The opener of launch(): the native window when `native`, then the fallback chain."""
    def opener(url: str) -> bool:
        if native and open_native_window(port, work):
            return True
        return bool(open_fallback(url, work))
    return opener


def prepare_window(port: int = PORT, work: Path = WORK, command: list[str] | None = None, runner=None,
                   opener=None, **options) -> str | None:
    """For the macOS bundle: start the server if needed, then run `window.py --check` (uv may download pywebview).

    Returns the path of the Python that runs window.py. When the window cannot run, opens the page through the fallback
    chain (or `opener`) and returns None. LaunchError when the server cannot start.
    """
    ensure_server(port, work, command, **options)
    uv = find_uv()
    reason = "uv was not found"
    if uv:
        try:
            result = (runner or subprocess.run)([uv, "run", "--quiet", "--script", str(work / WINDOW_SCRIPT), "--check"], cwd=work, env=utf8_environment(),
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=CHECK_TIMEOUT)
        except subprocess.TimeoutExpired:
            reason = f"window.py --check took more than {CHECK_TIMEOUT:g} s"
        except (OSError, subprocess.SubprocessError) as error:
            reason = f"window.py --check could not run: {getattr(error, 'strerror', None) or error}"
        else:
            lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
            if result.returncode == 0 and lines and Path(lines[-1]).is_file():
                (work / "agents").mkdir(parents=True, exist_ok=True)
                (work / "agents" / PREPARED_FILE).write_text("window.py ran here\n", encoding="utf-8")
                return lines[-1]
            reason = f"window.py --check failed (code {result.returncode}): {((result.stderr or '').strip().splitlines() or ['no message'])[-1]}"
    log_line(work, f"Native window unavailable ({reason}); using the fallback.")
    if not (opener or (lambda url: open_fallback(url, work)))(page_url(port)):
        raise LaunchError(f"Could not open Corvus. Open {page_url(port)} in your browser.")
    return None


def ensure_server(port: int = PORT, work: Path = WORK, command: list[str] | None = None, busy_attempts: int = BUSY_ATTEMPTS,
                  start_attempts: int = START_ATTEMPTS, delay: float = DELAY) -> str:
    """Make sure the actions server answers on `port`: 'running' when it already did, 'started' otherwise.

    `command` replaces the server command (tests); by default it is `<uv> run tools/tasks-web/tasks-web.py --port N`.
    LaunchError when another program owns the port or the server cannot start.
    """
    if ready(port):
        return "running"
    if port_owned(port):
        for _ in range(busy_attempts):
            if ready(port):
                return "running"
            time.sleep(delay)
        raise LaunchError(f"Port {port} is already used by another application. Close it before starting Corvus.")
    uv = None
    if command is None:
        uv = find_uv()
        if uv is None:
            raise LaunchError("uv was not found. Install or restore uv, then start Corvus again.")
        command = [uv, "run", str(work / SERVER_SCRIPT), "--port", str(port)]
    agents = work / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    environment = utf8_environment()
    environment["PATH"] = tool_path(uv=uv)  # the tools of the user's terminal, even when the Dock started this launcher
    try:
        process = start_detached(command, work, agents / "tasks-web.log", environment=environment)
    except OSError as error:
        raise LaunchError(f"Corvus could not start: {error.strerror or error}.") from None
    (agents / "tasks-web.pid").write_text(f"{process.pid}\n", encoding="utf-8")
    for _ in range(start_attempts):
        if ready(port):
            return "started"
        if process.poll() is not None and not port_owned(port):  # it stopped, and no other start (a double click) is under way
            break
        time.sleep(delay)
    raise LaunchError("Corvus did not start. See agents/tasks-web.log in Work.")


def launch(port: int = PORT, work: Path = WORK, command: list[str] | None = None, opener=None, busy_attempts: int = BUSY_ATTEMPTS,
           start_attempts: int = START_ATTEMPTS, delay: float = DELAY, native: bool = True) -> str:
    """Open the page, starting the server first when needed: 'opened' or 'started'. LaunchError when it cannot.

    `opener(url) -> bool` replaces the chain of default_opener (tests): the native window unless `native` is False, then a
    Chrome app window, then the default browser.
    """
    state = ensure_server(port, work, command, busy_attempts, start_attempts, delay)
    open_page(port, opener or default_opener(port, work, native))
    return "opened" if state == "running" else state


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
    log_line(work, message)
    if dialog:
        show_dialog(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=PORT, help=f"local port (default: {PORT})")
    parser.add_argument("--no-dialog", action="store_true", help="report an error on stderr and in the log only")
    parser.add_argument("--browser", action="store_true", help="skip the native window: a Chrome app window, else the default browser")
    parser.add_argument("--prepare-window", action="store_true",
                        help="macOS bundle: start the server, check window.py, print the path of the Python that runs it on stdout")
    args = parser.parse_args(argv)
    try:
        if args.prepare_window:
            python = prepare_window(args.port, WORK)
            if python and sys.stdout is not None:
                print(python, flush=True)  # the only thing ever printed on stdout in this mode
        else:
            launch(args.port, native=not args.browser)
    except LaunchError as error:
        report(str(error), WORK, not args.no_dialog)
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(WORK / "tools/machine"))
    import work_config  # tools/machine/work_config.py

    work_config.utf8_stdio()
    raise SystemExit(main())
