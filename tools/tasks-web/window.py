#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pywebview==6.2.1"]
# ///
"""Corvus's native window: the local actions page (http://127.0.0.1:8765/) in a window of its own.

Run from Work with: uv run --script tools/tasks-web/window.py [--port N]
launch.py starts it on Windows, and on macOS when no Corvus.app is installed (a run from a terminal); the macOS bundle
execs it with the Python that `--check` reports, after launch.py --prepare-window has started the server. Linux has no
native window: uv's isolated environment cannot reach the system's GTK or Qt bindings, so launch.py opens a Chrome app
window there. The window is a pywebview window: WKWebView on macOS, WebView2 (Edge Chromium) on Windows. It never starts
the server and closing it leaves the server running; the page's Quit stops the server, and the window follows.

- Quit or restart: an in-page Update restarts the server, so a closed port alone is not a Quit. The server's
  /api/shutdown writes agents/tasks-web.quit (a time stamp) before it stops. The window closes when the port has failed
  three checks in a row, one second apart, AND that marker was written after the window started. Otherwise (a restart,
  a server stopped some other way) it closes only once the port has stayed closed for 90 s, longer than the page's own
  60 s restart wait, so that a failed restart leaves the page time to show its error.
- --check imports pywebview and loads what the window needs before it opens (on Windows, the GUI library and WebView2:
  preflight), then prints the path of this Python on stdout and exits 0, or exits 1 with the reason on stderr (how launch.py finds the interpreter
  of the script environment, and downloads pywebview the first time).
- Private mode is off, so the page's localStorage (the view, the filters, the collapsed groups) survives between runs; the
  store lives in the system's web view data (~/Library/WebKit/<bundle id>/ on macOS, the WebView2 profile on Windows).
- One window on every system: it holds agents/tasks-web-window.lock; a second start touches agents/tasks-web-window.raise,
  which the open window polls (twice a second) to come to the front, then exits with 0. Opening the macOS bundle again
  only activates the running one.
- agents/tasks-web-window.ready is written once the window is shown, and removed when it closes: launch.py waits for it.
- When the window cannot be created or started (on Windows, also when the WebView2 runtime is missing), the error goes to
  agents/tasks-web.log and the page opens through the fallback chain of launch.py (a Chrome app window, else the default
  browser), unless --no-fallback (launch.py does it itself then); the exit code is 1.
- Only the macOS page (marked .mac-window) has drag regions, and the web view never opens file:// URLs.

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
SIZE = (1280, 840)
MIN_SIZE = (720, 480)
LOCK_FILE = "tasks-web-window.lock"
RAISE_FILE = "tasks-web-window.raise"
READY_FILE = "tasks-web-window.ready"
QUIT_FILE = "tasks-web.quit"  # in agents/: the server's /api/shutdown writes the time of a Quit there before it stops
GONE_LIMIT = 3  # consecutive failed checks before the window closes after a Quit
GONE_INTERVAL = 1.0  # seconds between two checks
RAISE_INTERVAL = 0.5  # seconds between two looks at the raise file
CLOSED_WAIT = 90.0  # seconds the port may stay closed without a Quit: longer than the page's restart wait (60 s)
RESTART_AFTER = 20.0  # seconds without a server and without a Quit before the window starts the server again
DRAG_REGION_SELECTOR = ".mac-window .pywebview-drag-region"  # only the macOS page, under its transparent title bar


def page_url(port: int = PORT) -> str:
    return f"http://{HOST}:{port}/"


def window_url(port: int = PORT, platform: str | None = None) -> str:
    """The page as the window opens it: on macOS with ?shell=mac, so that the page leaves room for the window buttons
    under the transparent title bar (static/window-shell.js) and gives a strip to drag the window by."""
    return page_url(port) + ("?shell=mac" if (platform or sys.platform) == "darwin" else "")


def icon_path(platform: str | None = None) -> Path:
    """The window's icon: .ico on Windows (WinForms' System.Drawing.Icon reads nothing else), the PNG elsewhere."""
    return HERE / ("static/icon.ico" if (platform or sys.platform) == "win32" else "static/icon.png")


def start_options(platform: str | None = None) -> dict:
    """The keyword arguments of webview.start: localStorage kept, the icon, and on Windows the WebView2 renderer."""
    platform = platform or sys.platform
    options = {"private_mode": False, "icon": str(icon_path(platform))}
    if platform == "win32":
        options["gui"] = "edgechromium"
    return options


def configure(settings) -> None:
    """pywebview's settings for this page (`settings` is webview.settings, which only accepts its own keys)."""
    # The page marks the empty parts of its bar .pywebview-drag-region on every system, and pywebview's drag script also
    # runs in framed windows: only the macOS page, whose title bar is transparent, is draggable from the page. Only a
    # press on such a part itself moves the window, not one on a button, the search or the title's links inside it.
    settings["DRAG_REGION_SELECTOR"] = DRAG_REGION_SELECTOR
    settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
    settings["ALLOW_FILE_URLS"] = False  # a file dropped on the window must not open as a page


def check_renderer(initialize: Callable[[str], object]) -> None:
    """Windows: make sure pywebview uses WebView2. `initialize` is webview.guilib.initialize.

    Without the WebView2 runtime, pywebview 6.2.1 falls back to MSHTML (Internet Explorer) even with gui="edgechromium",
    and this page would be blank there: raising sends it to the fallback chain instead.
    """
    renderer = getattr(initialize("edgechromium"), "renderer", None)
    if renderer != "edgechromium":
        raise RuntimeError(f"the WebView2 runtime is missing (pywebview would use {renderer or 'no renderer'})")


def preflight(platform: str | None = None) -> None:
    """What the window loads before it opens, beyond the import: on Windows, pywebview's GUI library and WebView2.

    run_window and --check share it, so the installer's --check sees a window that would fail, instead of the first click
    falling back to a Chrome app window without a word. Raises on failure.
    """
    if (platform or sys.platform) == "win32":
        # From the submodule: the package's own `guilib` attribute is None until webview.start, and it shadows the module.
        from webview.guilib import initialize

        check_renderer(initialize)


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


def quit_since(path: Path, since: float) -> bool:
    """True when the server's quit marker was written at `since` (a time.time()) or later: a Quit, not a restart."""
    try:
        try:
            stamp = float(path.read_text(encoding="utf-8").split()[0])
        except (ValueError, IndexError):  # not a time stamp: when the file was written
            stamp = path.stat().st_mtime
    except OSError:
        return False
    return stamp >= since


def watch_port(on_gone: Callable[[], None], check: Callable[[], bool] = port_open, stop: threading.Event | None = None,
               interval: float = GONE_INTERVAL, limit: int = GONE_LIMIT, quit_requested: Callable[[], bool] = lambda: False,
               closed_wait: float = CLOSED_WAIT, clock: Callable[[], float] = time.monotonic,
               on_quiet: Callable[[], None] | None = None, restart_after: float = RESTART_AFTER) -> bool:
    """Call `on_gone` once the server is gone for good; True when it did.

    Gone means `check` failed `limit` times in a row, `interval` seconds apart, and either `quit_requested()` (the page's
    Quit) or the port stayed closed for `closed_wait` seconds (a restart that never came back). Without a Quit, once the
    port has been closed for `restart_after` seconds, `on_quiet` is called once for that outage: the window starts the
    server again, so a server that stopped on its own does not leave the window without one (a click on the app icon
    only brings the open window forward). A successful check resets everything. Returns False when `stop` is set first
    (the window closed by itself).
    """
    stop = stop or threading.Event()
    failures, closed_since, restarted = 0, None, False
    while not stop.wait(interval):
        if check():
            failures, closed_since, restarted = 0, None, False
            continue
        failures += 1
        closed_since = clock() if closed_since is None else closed_since
        if failures >= limit and (quit_requested() or clock() - closed_since >= closed_wait):
            on_gone()
            return True
        if on_quiet is not None and not restarted and clock() - closed_since >= restart_after and not quit_requested():
            restarted = True
            on_quiet()
    return False


# --- one window

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
    except OSError:  # FileNotFoundError included: no request
        return False
    return True


def watch_raise(path: Path, on_raise: Callable[[], None], stop: threading.Event | None = None, interval: float = RAISE_INTERVAL) -> None:
    """Call `on_raise` each time a raise request shows up, until `stop` is set."""
    stop = stop or threading.Event()
    while not stop.wait(interval):
        if take_raise_request(path):
            on_raise()


def raise_window(window, minimized: bool, platform: str | None = None) -> None:
    """Bring the open window to the front: restore it only when it is minimized (a restore also leaves a maximized
    window), then show it. Windows does not let a background process take the focus, so the window is also put on top
    for a moment."""
    if minimized:
        window.restore()
    window.show()
    if (platform or sys.platform) == "win32":
        window.on_top = True
        window.on_top = False


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


def launch_module():
    """launch.py (standard library only), loaded from its file: the fallback opener and the server's start live there."""
    spec = importlib.util.spec_from_file_location("tasks_launch", HERE / "launch.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fall_back(port: int) -> None:
    """The fallback opener of launch.py (a Chrome app window, else the default browser)."""
    try:
        module = launch_module()
        module.open_fallback(module.page_url(port), WORK)
    except Exception as error:  # noqa: BLE001 - the original error is already logged
        log(f"The fallback could not open the page either: {error}")


def restart_server(port: int, agents: Path, reload: Callable[[], None]) -> None:
    """Start the server again after it stopped without a Quit, then reload the page; never raises."""
    try:
        log("The server stopped without a Quit: starting it again.", agents)
        launch_module().ensure_server(port, WORK)
        reload()
    except Exception as error:  # noqa: BLE001 - the window then waits, and closes after CLOSED_WAIT
        log(f"Could not start the server again: {error}", agents)


def run_window(port: int, agents: Path) -> None:
    """Create the window and block until it closes. Raises when pywebview cannot show it."""
    import webview  # imported here: --check and the helpers above need no GUI

    started = time.time()  # a quit marker older than this is from an earlier window
    set_app_id()
    preflight()
    stop = threading.Event()
    ready = agents / READY_FILE
    minimized = threading.Event()
    window = webview.create_window(TITLE, window_url(port), width=SIZE[0], height=SIZE[1], min_size=MIN_SIZE)

    def blend() -> None:
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(blend_title_bar, window.native)
        except Exception as error:  # noqa: BLE001 - cosmetic: the window keeps its usual title bar
            log(f"Could not blend the title bar: {error}", agents)

    def destroy() -> None:
        log("The server quit: closing the window.", agents)
        window.destroy()

    def bring_forward() -> None:
        try:
            raise_window(window, minimized.is_set())
        except Exception as error:  # noqa: BLE001 - a window being closed
            log(f"Could not raise the window: {error}", agents)

    def shown() -> None:
        ready.write_text(f"{os.getpid()}\n", encoding="utf-8")

    def background() -> None:
        threading.Thread(target=watch_port, args=(destroy, lambda: port_open(port), stop),
                         kwargs={"quit_requested": lambda: quit_since(agents / QUIT_FILE, started),
                                 "on_quiet": lambda: restart_server(port, agents, lambda: window.load_url(window_url(port)))},
                         daemon=True).start()
        threading.Thread(target=watch_raise, args=(agents / RAISE_FILE, bring_forward, stop), daemon=True).start()

    window.events.shown += shown
    window.events.minimized += minimized.set
    window.events.restored += minimized.clear
    configure(webview.settings)
    if sys.platform == "darwin":
        window.events.before_show += blend
    try:
        webview.start(background, **start_options())
    finally:
        stop.set()
        ready.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=PORT, help=f"port of the local server (default: {PORT})")
    parser.add_argument("--check", action="store_true",
                        help="import pywebview, load what the window needs (Windows: WebView2), print this Python's path and exit")
    parser.add_argument("--no-fallback", action="store_true", help="do not open the page elsewhere when the window fails (launch.py does)")
    args = parser.parse_args(argv)
    if args.check:
        import webview  # noqa: F401

        try:
            preflight()
        except Exception as error:  # noqa: BLE001 - reported, and the exit code tells the caller
            print(f"the native window would fail: {type(error).__name__}: {error}", file=sys.stderr)
            return 1
        print(sys.executable)
        return 0
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
        lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
