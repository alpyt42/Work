#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pywebview>=6"]
# ///
"""Corvus's native window: the local actions page (http://127.0.0.1:8765/) in a window of its own.

Run from Work with: uv run --script tools/tasks-web/window.py [--port N]
launch.py starts it (Windows, Linux) and the macOS bundle execs it with the Python that `--check` reports, after
launch.py --prepare-window has started the server. The window is a pywebview window: WKWebView on macOS, WebView2 on
Windows, GTK or Qt on Linux. The window never starts the server and closing it leaves the server running; the page's
Quit stops the server, and the window follows. An in-page Update restarts the server in place (an exec: same PID), so a
closed port alone is not a Quit. The window closes when the port has stopped answering three times in a row, one second
apart, AND the server process is gone (the PID in agents/tasks-web.pid, written by launch.py: the `uv run tasks-web.py`
process, which survives the restart and exits on Quit). While that PID is alive the window waits, with no limit. With
no usable pid file (a server started by hand) it closes only after the port stayed closed for 90 s, longer than the
page's own restart wait.

- --check imports pywebview, prints the path of this Python on stdout and exits 0 (how launch.py finds the interpreter
  of the script environment, and downloads pywebview the first time).
- Private mode is off, so the page's localStorage (the view, the filters, the collapsed groups) survives between runs; the
  store lives in the system's web view data (~/Library/WebKit/<bundle id>/ on macOS).
- Windows and Linux allow one window: it holds agents/tasks-web-window.lock; a second start touches
  agents/tasks-web-window.raise, which the open window polls (twice a second) to restore and show itself, then exits.
  macOS needs none: opening the bundle again activates the running one.
- agents/tasks-web-window.ready is written once the window is shown, and removed when it closes: launch.py waits for it.
- When the window cannot be created or started, the error goes to agents/tasks-web.log and the page opens through the
  fallback chain of launch.py (a Chrome app window, else the default browser), unless --no-fallback (launch.py does it
  itself then); the exit code is 1.

The page's content security policy refuses eval, so nothing here evaluates JavaScript in the page.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1]
AGENTS = WORK / "agents"
PORT = 8765
HOST = "127.0.0.1"
TITLE = "Corvus"
APP_ID = "local.work.tasks-brain"  # the bundle id, and the Windows AppUserModelID that groups the taskbar icon
ICON = HERE / "static/icon.png"  # used by the GTK and Qt backends
SIZE = (1280, 840)
MIN_SIZE = (720, 480)
LOCK_FILE = "tasks-web-window.lock"
RAISE_FILE = "tasks-web-window.raise"
READY_FILE = "tasks-web-window.ready"
GONE_LIMIT = 3  # consecutive failed checks before the window closes
GONE_INTERVAL = 1.0  # seconds between two checks
RAISE_INTERVAL = 0.5  # seconds between two looks at the raise file
PID_FILE = "tasks-web.pid"  # in agents/: the server's process (launch.py writes it)
NO_PID_WAIT = 90.0  # seconds the port may stay closed when there is no pid to ask: longer than the page's restart wait (60 s)


def page_url(port: int = PORT) -> str:
    return f"http://{HOST}:{port}/"


def window_url(port: int = PORT, platform: str | None = None) -> str:
    """The page as the window opens it: on macOS with ?shell=mac, so that the page leaves room for the window buttons
    under the transparent title bar (static/window-shell.js) and gives a strip to drag the window by."""
    return page_url(port) + ("?shell=mac" if (platform or sys.platform) == "darwin" else "")


def blend_title_bar(native) -> None:
    """macOS, like the other Mac apps: the page runs under a transparent title bar, the title is hidden and the window
    buttons sit on the sidebar. `native` is the NSWindow; call it on the main thread."""
    import AppKit

    native.setStyleMask_(native.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
    native.setTitlebarAppearsTransparent_(True)
    native.setTitleVisibility_(AppKit.NSWindowTitleHidden)
    # An empty unified toolbar makes the title row 52 px tall, the window buttons centred in it (19 to 73 px from the left edge):
    # the page puts its own bar in that row (app.css). Clicks in the row still reach the page.
    toolbar = AppKit.NSToolbar.alloc().initWithIdentifier_("corvus")
    toolbar.setShowsBaselineSeparator_(False)
    native.setToolbar_(toolbar)
    native.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnified)
    # pywebview paints the title bar's container with the window colour (its Cocoa BrowserView, for windows with a frame):
    # left as is, that grey band hides the top of the page. Every view of the frame but the content is made clear.
    content = native.contentView()
    for view in content.superview().subviews():
        if view is not content and view.respondsToSelector_("setBackgroundColor:"):
            view.setBackgroundColor_(AppKit.NSColor.clearColor())


def log(message: str, agents: Path | None = None) -> None:
    """One line at the end of agents/tasks-web.log; never raises."""
    folder = AGENTS if agents is None else agents
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "tasks-web.log", "a", encoding="utf-8") as handle:
            handle.write(f"[window.py {datetime.now().isoformat(timespec='seconds')}] {message}\n")
    except OSError:
        pass


# --- the server went away

def port_open(port: int = PORT, host: str = HOST, timeout: float = 0.5) -> bool:
    """True when a program accepts TCP connections on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)
        try:
            return probe.connect_ex((host, port)) == 0
        except OSError:
            return False


def pid_alive(pid: int) -> bool:
    """True when a process with this PID exists (POSIX: signal 0; Windows: its exit code is still STILL_ACTIVE)."""
    if os.name == "nt":
        import ctypes

        kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, under another user
    except OSError:
        return False
    return True


def server_alive(pid_file: Path, alive: Callable[[int], bool] = pid_alive) -> bool | None:
    """Whether the server process is alive according to its pid file; None when the file is missing or unusable."""
    try:
        pid = int(pid_file.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return alive(pid) if pid > 0 else None


def watch_port(on_gone: Callable[[], None], check: Callable[[], bool] = port_open, stop: threading.Event | None = None,
               interval: float = GONE_INTERVAL, limit: int = GONE_LIMIT, process: Callable[[], bool | None] = lambda: False,
               no_pid_wait: float = NO_PID_WAIT, clock: Callable[[], float] = time.monotonic) -> bool:
    """Call `on_gone` once the server is gone; True when it did.

    Gone means `check` failed `limit` times in a row, `interval` seconds apart, and `process()` says the server process
    is dead (False). While it is alive (True, a restart in progress) the wait has no limit. With None (no pid to ask) the
    port must stay closed for `no_pid_wait` seconds. A successful check resets everything. Returns False when `stop`
    is set first (the window closed by itself).
    """
    stop = stop or threading.Event()
    failures, closed_since = 0, None
    while not stop.wait(interval):
        if check():
            failures, closed_since = 0, None
            continue
        failures += 1
        closed_since = clock() if closed_since is None else closed_since
        if failures < limit:
            continue
        state = process()
        if state is False or (state is None and clock() - closed_since >= no_pid_wait):
            on_gone()
            return True
    return False


# --- one window (Windows and Linux)

class InstanceLock:
    """An exclusive lock on a file of agents/ that the system drops when the process ends, however it ends."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        handle, self.handle = self.handle, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def request_raise(path: Path) -> None:
    """Ask the open window to come to the front (a second start)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{time.time()}\n", encoding="utf-8")


def take_raise_request(path: Path) -> bool:
    """True, and the request is consumed, when a second start asked for the window."""
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def watch_raise(path: Path, on_raise: Callable[[], None], stop: threading.Event | None = None, interval: float = RAISE_INTERVAL) -> None:
    """Call `on_raise` each time a raise request shows up, until `stop` is set."""
    stop = stop or threading.Event()
    while not stop.wait(interval):
        if take_raise_request(path):
            on_raise()


# --- the window

def set_app_id() -> None:
    """Windows, best effort: the taskbar groups this process under the same id as the shortcut's app."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - cosmetic only
        pass


def fall_back(port: int) -> None:
    """The fallback opener of launch.py (a Chrome app window, else the default browser)."""
    try:
        spec = importlib.util.spec_from_file_location("tasks_launch", HERE / "launch.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.open_fallback(module.page_url(port), WORK)
    except Exception as error:  # noqa: BLE001 - the original error is already logged
        log(f"The fallback could not open the page either: {error}")


def run_window(port: int, agents: Path) -> None:
    """Create the window and block until it closes. Raises when pywebview cannot show it."""
    import webview  # imported here: --check and the helpers above need no GUI

    set_app_id()
    stop = threading.Event()
    ready = agents / READY_FILE
    window = webview.create_window(TITLE, window_url(port), width=SIZE[0], height=SIZE[1], min_size=MIN_SIZE)

    def blend() -> None:
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(blend_title_bar, window.native)
        except Exception as error:  # noqa: BLE001 - cosmetic: the window keeps its usual title bar
            log(f"Could not blend the title bar: {error}", agents)

    def destroy() -> None:
        log("The server is gone: closing the window.", agents)
        window.destroy()

    def bring_forward() -> None:
        try:
            window.restore()
            window.show()
        except Exception as error:  # noqa: BLE001 - a window being closed
            log(f"Could not raise the window: {error}", agents)

    def shown() -> None:
        ready.write_text(f"{os.getpid()}\n", encoding="utf-8")

    def background() -> None:
        threading.Thread(target=watch_port, args=(destroy, lambda: port_open(port), stop),
                         kwargs={"process": lambda: server_alive(agents / PID_FILE)}, daemon=True).start()
        if sys.platform != "darwin":
            threading.Thread(target=watch_raise, args=(agents / RAISE_FILE, bring_forward, stop), daemon=True).start()

    window.events.shown += shown
    # The page marks the empty parts of its bar .pywebview-drag-region: only a press on such a part itself moves the window,
    # not one on a button, the search or the title's links inside it.
    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
    if sys.platform == "darwin":
        window.events.before_show += blend
    try:
        webview.start(background, private_mode=False, icon=str(ICON))
    finally:
        stop.set()
        ready.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=PORT, help=f"port of the local server (default: {PORT})")
    parser.add_argument("--check", action="store_true", help="import pywebview, print this Python's path and exit")
    parser.add_argument("--no-fallback", action="store_true", help="do not open the page elsewhere when the window fails (launch.py does)")
    args = parser.parse_args(argv)
    if args.check:
        import webview  # noqa: F401

        print(sys.executable)
        return 0
    lock = None
    if sys.platform != "darwin":
        lock = InstanceLock(AGENTS / LOCK_FILE)
        if not lock.acquire():
            request_raise(AGENTS / RAISE_FILE)
            return 0
    try:
        run_window(args.port, AGENTS)
    except Exception as error:  # noqa: BLE001 - whatever stops the window, the page must still open
        log(f"The native window failed: {type(error).__name__}: {error}")
        if not args.no_fallback:
            fall_back(args.port)
        return 1
    finally:
        if lock is not None:
            lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
