# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Installer (install-app.py) and launcher (launch.py) of the local actions page.

Everything runs on a fake home, a fake APPDATA, a fake XDG_DATA_HOME, a fake artifacts folder and a fake uv: nothing outside
a temporary folder is written. PowerShell is never run; the macOS app is compiled only on macOS.
"""

import base64
import importlib.util
import io
import json
import os
import plistlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "tools/tasks-web"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


install = load("tasks_install_under_test", WEB / "install-app.py")
launch = load("tasks_launch_under_test", WEB / "launch.py")
REAL_LOGIN_SHELL_PATH = launch.login_shell_path  # LaunchTest patches it out; its own test calls the real one
OSACOMPILE = Path("/usr/bin/osacompile")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class FakeHomes(unittest.TestCase):
    """A temporary folder with a home, Windows profile folders, an XDG data folder, an artifacts folder and fake uv binaries."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.profile = self.root / "winhome"
        self.appdata = self.profile / "AppData/Roaming"
        self.xdg = self.root / "xdg"
        self.artifacts = self.root / "artifacts"
        self.uv = self.root / "bin/uv"
        self.uv_exe = self.root / "winbin/uv.exe"
        for path in (self.uv, self.uv_exe):
            path.parent.mkdir(parents=True)
            path.write_bytes(b"fake uv")
        self.home.mkdir()
        self.environment = patch.dict(os.environ, {
            "HOME": str(self.home), "USERPROFILE": str(self.profile), "APPDATA": str(self.appdata),
            "LOCALAPPDATA": str(self.profile / "AppData/Local"), "XDG_DATA_HOME": str(self.xdg)})
        self.environment.start()
        self.staging = patch.object(install, "STAGING_ROOT", self.root / "staging")
        self.staging.start()

    def tearDown(self):
        self.staging.stop()
        self.environment.stop()
        self.temp.cleanup()

    def installer(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = install.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def snapshot(self) -> dict[str, bytes]:
        """Every file under the temporary root, with its bytes (fake uv binaries included)."""
        return {str(path.relative_to(self.root)): path.read_bytes() for path in sorted(self.root.rglob("*")) if path.is_file()}


class LinuxInstallTest(FakeHomes):
    def entry(self) -> Path:
        return self.xdg / "applications/actions-brain.desktop"

    def icon(self) -> Path:
        return self.xdg / "icons/hicolor/256x256/apps/actions-brain.png"

    def test_the_desktop_entry_runs_the_launcher_with_the_absolute_uv(self):
        with patch.object(install.shutil, "which", return_value=None):
            code, out, err = self.installer("--platform", "linux", "--uv", str(self.uv))
        self.assertEqual(code, 0, err)
        lines = self.entry().read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "[Desktop Entry]")
        for line in ("Type=Application", "Name=Actions Brain", "Terminal=false", "Categories=Office;",
                     f"Path={install.WORK}", f"Icon={self.icon()}", f"X-Actions-Brain={install.MARKER}"):
            self.assertIn(line, lines)
        self.assertIn(f'Exec="{self.uv}" "run" "--quiet" "--script" "{install.LAUNCH}"', lines)
        self.assertEqual(self.icon().read_bytes(), (WEB / "static/icon.png").read_bytes())
        self.assertIn(install.ICON_MARKER, self.icon().read_bytes())
        self.assertIn(str(self.entry()), out)

    def test_exec_arguments_are_quoted_and_escaped_by_the_desktop_entry_rules(self):
        # Quoting level: ", `, $ and \ take a backslash; % is doubled; then the value is escaped as a string (\ doubled).
        self.assertEqual(install.desktop_exec_argument('/opt/a b/$x"`\\%'), '"/opt/a b/\\\\$x\\\\"\\\\`\\\\\\\\%%"')
        self.assertEqual(install.desktop_value("C:\\work"), "C:\\\\work")
        with self.assertRaises(install.InstallError):
            install.desktop_exec_argument("/opt/a\nb")

    def test_a_relative_xdg_data_home_is_ignored(self):
        with patch.dict(os.environ, {"XDG_DATA_HOME": "relative/share"}):
            self.assertEqual(install.xdg_data_home(), self.home / ".local/share")
        with patch.dict(os.environ, {"XDG_DATA_HOME": ""}):
            self.assertEqual(install.xdg_data_home(), self.home / ".local/share")

    def test_dry_run_prints_the_entry_and_writes_nothing(self):
        before = self.snapshot()
        code, out, err = self.installer("--platform", "linux", "--dry-run", "--uv", str(self.uv))
        self.assertEqual(code, 0, err)
        self.assertIn("dry run", out)
        self.assertIn("Exec=", out)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.xdg.exists())

    def test_uninstall_removes_only_the_marked_files(self):
        with patch.object(install.shutil, "which", return_value=None):
            self.assertEqual(self.installer("--platform", "linux", "--uv", str(self.uv))[0], 0)
            self.icon().write_bytes(b"\x89PNG someone else's icon")  # same place, no marker: not ours any more
            code, out, err = self.installer("--platform", "linux", "--uninstall")
        self.assertEqual(code, 0, err)
        self.assertFalse(self.entry().exists())
        self.assertEqual(self.icon().read_bytes(), b"\x89PNG someone else's icon")
        self.assertIn("was not made by install-app.py", out)

    def test_an_entry_that_is_not_ours_is_never_replaced(self):
        self.entry().parent.mkdir(parents=True)
        self.entry().write_text("[Desktop Entry]\nName=Other\n", encoding="utf-8")
        code, _, err = self.installer("--platform", "linux", "--uv", str(self.uv))
        self.assertEqual(code, 1)
        self.assertIn("was not made by install-app.py", err)
        self.assertEqual(self.entry().read_text(encoding="utf-8"), "[Desktop Entry]\nName=Other\n")

    def test_installing_again_updates_our_own_entry(self):
        with patch.object(install.shutil, "which", return_value=None):
            self.assertEqual(self.installer("--platform", "linux", "--uv", str(self.uv))[0], 0)
            other = self.root / "bin/uv2"
            other.write_bytes(b"fake uv")
            self.assertEqual(self.installer("--platform", "linux", "--uv", str(other))[0], 0)
        self.assertIn(f'Exec="{other}"', self.entry().read_text(encoding="utf-8"))


class WindowsInstallTest(FakeHomes):
    def start_menu_link(self) -> Path:
        return self.appdata / "Microsoft/Windows/Start Menu/Programs/Actions Brain.lnk"

    def desktop_link(self) -> Path:
        return self.profile / "Desktop/Actions Brain.lnk"

    def fake_powershell(self, calls: list):
        """Stands for powershell.exe: records the decoded script and writes a .lnk holding the description, as Windows does."""
        def run(argv):
            self.assertEqual(argv[:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand"])
            script = base64.b64decode(argv[4]).decode("utf-16-le")
            calls.append(script)
            link = Path(script.split("CreateShortcut('", 1)[1].split("')", 1)[0].replace("''", "'"))
            link.write_bytes(b"L\0\0\0" + install.DESCRIPTION.encode("utf-16-le"))
            return ""
        return run

    def test_the_powershell_script_creates_the_shortcut_with_quoted_paths(self):
        link = Path("/fake/Start Menu/Programs/Actions Brain.lnk")
        script = install.powershell_script(link, "C:/Users/o'neil/.local/bin/uvw.exe", 'run --gui-script "C:/Work’s/launch.py"',
                                           Path("C:/Work’s"), Path("C:/Work’s/icon.ico"), 1)
        lines = script.splitlines()
        self.assertEqual(lines[:2], ["$ErrorActionPreference = 'Stop'", "$shell = New-Object -ComObject WScript.Shell"])
        self.assertIn(f"$link = $shell.CreateShortcut('{link}')", lines)
        self.assertIn("$link.TargetPath = 'C:/Users/o''neil/.local/bin/uvw.exe'", lines)
        self.assertIn("$link.Arguments = 'run --gui-script \"C:/Work’’s/launch.py\"'", lines)
        self.assertIn("$link.WorkingDirectory = 'C:/Work’’s'", lines)
        self.assertIn("$link.IconLocation = 'C:/Work’’s/icon.ico,0'", lines)
        self.assertIn(f"$link.Description = '{install.DESCRIPTION}'", lines)
        self.assertEqual(lines[-2:], ["$link.WindowStyle = 1", "$link.Save()"])
        command = install.powershell_command(script)
        self.assertEqual(base64.b64decode(command[-1]).decode("utf-16-le"), script)

    def test_dry_run_prints_the_scripts_and_writes_nothing(self):
        (self.uv_exe.parent / "uvw.exe").write_bytes(b"fake uvw")
        before = self.snapshot()
        code, out, err = self.installer("--platform", "windows", "--dry-run", "--desktop", "--uv", str(self.uv_exe))
        self.assertEqual(code, 0, err)
        self.assertIn(str(self.start_menu_link()), out)
        self.assertIn(str(self.desktop_link()), out)
        self.assertIn(f"$link.TargetPath = '{self.uv_exe.parent / 'uvw.exe'}'", out)
        self.assertIn(f"run --gui-script \"{install.LAUNCH}\"", out)
        self.assertEqual(self.snapshot(), before)

    def test_install_targets_uvw_when_present_and_runs_powershell_once_per_shortcut(self):
        (self.uv_exe.parent / "uvw.exe").write_bytes(b"fake uvw")
        calls = []
        with patch.object(install.launch_tool, "system_name", return_value="windows"), \
                patch.object(install, "run_command", side_effect=self.fake_powershell(calls)):
            code, _, err = self.installer("--platform", "windows", "--desktop", "--uv", str(self.uv_exe))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(calls), 2)
        for script in calls:
            self.assertIn(f"$link.TargetPath = '{self.uv_exe.parent / 'uvw.exe'}'", script)
            self.assertIn("$link.WindowStyle = 1", script)
            self.assertIn(f"$link.WorkingDirectory = '{install.WORK}'", script)
            self.assertIn(f"$link.IconLocation = '{WEB / 'static/icon.ico'},0'", script)
        self.assertTrue(self.start_menu_link().is_file())
        self.assertTrue(self.desktop_link().is_file())

    def test_without_uvw_the_shortcut_runs_uv_minimized(self):
        calls = []
        with patch.object(install.launch_tool, "system_name", return_value="windows"), \
                patch.object(install, "run_command", side_effect=self.fake_powershell(calls)):
            code, out, err = self.installer("--platform", "windows", "--uv", str(self.uv_exe))
        self.assertEqual(code, 0, err)
        self.assertIn(f"$link.TargetPath = '{self.uv_exe}'", calls[0])
        self.assertIn("$link.WindowStyle = 7", calls[0])
        self.assertIn("uvw.exe was not found", out)
        self.assertFalse(self.desktop_link().exists())

    def test_a_real_install_needs_windows(self):
        code, _, err = self.installer("--platform", "windows", "--uv", str(self.uv_exe))
        self.assertEqual(code, 1)
        self.assertIn("only be created on Windows", err)
        self.assertFalse(self.appdata.exists())

    def test_uninstall_removes_only_the_marked_shortcuts(self):
        self.start_menu_link().parent.mkdir(parents=True)
        self.start_menu_link().write_bytes(b"L\0\0\0" + install.DESCRIPTION.encode("utf-16-le"))
        self.desktop_link().parent.mkdir(parents=True)
        self.desktop_link().write_bytes(b"L\0\0\0" + "Someone else's shortcut".encode("utf-16-le"))
        code, out, err = self.installer("--platform", "windows", "--uninstall")
        self.assertEqual(code, 0, err)
        self.assertFalse(self.start_menu_link().exists())
        self.assertTrue(self.desktop_link().exists())
        self.assertIn("was not made by install-app.py", out)

    def test_a_shortcut_that_is_not_ours_is_never_replaced(self):
        self.start_menu_link().parent.mkdir(parents=True)
        self.start_menu_link().write_bytes(b"L\0\0\0other")
        with patch.object(install.launch_tool, "system_name", return_value="windows"), \
                patch.object(install, "run_command") as runner:
            code, _, _ = self.installer("--platform", "windows", "--uv", str(self.uv_exe))
        self.assertEqual(code, 1)
        runner.assert_not_called()
        self.assertEqual(self.start_menu_link().read_bytes(), b"L\0\0\0other")


class MacInstallTest(FakeHomes):
    def folder(self) -> Path:
        return self.artifacts / "internal/setup/tasks-dock-app"

    def fake_build(self, source: str, app: Path):
        def build():
            (app / "Contents").mkdir(parents=True)
            with open(app / "Contents/Info.plist", "wb") as handle:
                plistlib.dump({"CFBundleIdentifier": install.BUNDLE_ID, install.PLIST_MARKER_KEY: install.MARKER}, handle)
        return build

    def test_the_applescript_runs_launch_py_with_the_absolute_uv(self):
        source = install.applescript_source('/opt/u"v\\bin/uv', Path("/srv/Work/tools/tasks-web/launch.py"))
        self.assertIn(install.MARKER, source.splitlines()[0])
        self.assertIn('do shell script ((quoted form of "/opt/u\\"v\\\\bin/uv") & " run --quiet --script " & '
                      '(quoted form of "/srv/Work/tools/tasks-web/launch.py") & " --no-dialog")', source)
        self.assertIn('display dialog ("Could not open Actions. " & errorMessage)', source)
        with self.assertRaises(install.InstallError):
            install.applescript_source("/opt/uv\n", Path("/srv/launch.py"))

    def test_dry_run_writes_nothing(self):
        before = self.snapshot()
        code, out, err = self.installer("--platform", "macos", "--dry-run", "--artifacts-dir", str(self.artifacts), "--uv", str(self.uv))
        self.assertEqual(code, 0, err)
        self.assertIn("osacompile", out)
        self.assertIn("do shell script", out)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.artifacts.exists())

    def test_an_existing_app_is_never_overwritten_or_deleted(self):
        old_app = self.folder() / "Actions Brain.app"
        (old_app / "Contents").mkdir(parents=True)
        (old_app / "Contents/Info.plist").write_bytes(b"old plist")
        (self.folder() / "README.md").write_text("old readme\n", encoding="utf-8")
        before = self.snapshot()
        with patch.object(install, "OSACOMPILE", self.uv):
            code, _, err = self.installer("--platform", "macos", "--artifacts-dir", str(self.artifacts), "--uv", str(self.uv))
        self.assertEqual(code, 1)
        self.assertIn("--replace", err)
        self.assertEqual(self.snapshot(), before)
        with patch.object(install, "build_app", side_effect=self.fake_build), patch.object(install, "OSACOMPILE", self.uv):
            code, out, err = self.installer("--platform", "macos", "--replace", "--artifacts-dir", str(self.artifacts), "--uv", str(self.uv))
        self.assertEqual(code, 0, err)
        archived = list((self.artifacts / "archive").glob("tasks-dock-app-*"))
        self.assertEqual(len(archived), 1)
        self.assertEqual((archived[0] / "Actions Brain.app/Contents/Info.plist").read_bytes(), b"old plist")
        self.assertEqual((archived[0] / "README.md").read_text(encoding="utf-8"), "old readme\n")
        self.assertTrue(install.app_is_ours(old_app))
        self.assertIn(install.MARKER, (self.folder() / "README.md").read_text(encoding="utf-8"))
        self.assertIn(install.MARKER, (self.folder() / "launch.applescript").read_text(encoding="utf-8"))
        self.assertIn(str(archived[0]), out)
        # Nothing was deleted: every file present before is still somewhere under the artifacts folder, unchanged.
        contents = list(self.snapshot().values())
        for data in before.values():
            self.assertIn(data, contents)

    def test_uninstall_moves_only_its_own_app_into_the_archive(self):
        app = self.folder() / "Actions Brain.app"
        (app / "Contents").mkdir(parents=True)
        (app / "Contents/Info.plist").write_bytes(b"not ours")
        code, out, err = self.installer("--platform", "macos", "--uninstall", "--artifacts-dir", str(self.artifacts))
        self.assertEqual(code, 0, err)
        self.assertIn("was not made by install-app.py", out)
        self.assertTrue(app.exists())
        shutil.rmtree(app)  # the test's own fixture, in the temporary folder
        with patch.object(install, "build_app", side_effect=self.fake_build), patch.object(install, "OSACOMPILE", self.uv):
            self.assertEqual(self.installer("--platform", "macos", "--artifacts-dir", str(self.artifacts), "--uv", str(self.uv))[0], 0)
        (self.folder() / "notes.txt").write_text("the owner's file\n", encoding="utf-8")
        code, out, err = self.installer("--platform", "macos", "--uninstall", "--artifacts-dir", str(self.artifacts))
        self.assertEqual(code, 0, err)
        archived = next((self.artifacts / "archive").glob("tasks-dock-app-*"))
        self.assertEqual(sorted(path.name for path in archived.iterdir()), ["Actions Brain.app", "README.md", "launch.applescript"])
        self.assertFalse(app.exists())
        self.assertEqual((self.folder() / "notes.txt").read_text(encoding="utf-8"), "the owner's file\n")
        self.assertIn("Nothing is deleted", out)

    def test_options_of_another_system_are_refused(self):
        self.assertEqual(self.installer("--platform", "linux", "--desktop", "--dry-run")[0], 1)
        self.assertEqual(self.installer("--platform", "windows", "--replace", "--dry-run")[0], 1)

    @unittest.skipUnless(sys.platform == "darwin" and OSACOMPILE.is_file(), "the app is compiled by macOS's osacompile")
    def test_the_real_app_carries_its_bundle_id_marker_and_icon(self):
        code, _, err = self.installer("--platform", "macos", "--artifacts-dir", str(self.artifacts), "--uv", str(self.uv))
        self.assertEqual(code, 0, err)
        app = self.folder() / "Actions Brain.app"
        with open(app / "Contents/Info.plist", "rb") as handle:
            info = plistlib.load(handle)
        self.assertEqual(info["CFBundleIdentifier"], install.BUNDLE_ID)
        self.assertEqual(info[install.PLIST_MARKER_KEY], install.MARKER)
        self.assertNotIn("CFBundleIconName", info)
        self.assertEqual((app / "Contents/Resources/applet.icns").read_bytes(), (WEB / "static/icon.icns").read_bytes())
        script = subprocess.run(["/usr/bin/osadecompile", str(app / "Contents/Resources/Scripts/main.scpt")],
                                capture_output=True, text=True, encoding="utf-8", check=True).stdout
        self.assertIn(str(install.LAUNCH), script)
        self.assertIn(str(self.uv), script)
        self.assertEqual(list((self.root / "staging").iterdir()), [])  # the staging folder is cleaned


class StubActions(BaseHTTPRequestHandler):
    body = json.dumps({"actions": [], "registers": [], "owner": "Jane"}).encode("utf-8")

    def do_GET(self):
        self.send_response(200 if self.path == "/api/actions" else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body if self.path == "/api/actions" else b"{}")

    def log_message(self, *args):
        pass


class OtherProgram(StubActions):
    body = b'{"hello": "this is not the actions server"}'


# A server that answers like tasks-web after a short start, run as the "server command" of the launcher.
STUB_SERVER = """
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
time.sleep(0.3)
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"actions": [], "registers": []}).encode())
    def log_message(self, *args):
        pass
print("stub server ready", flush=True)
HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""


class LaunchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.opener = Mock(return_value=True)
        shell = patch.object(launch, "login_shell_path", return_value=[])  # never the tester's own shell startup files
        shell.start()
        self.addCleanup(shell.stop)

    def tearDown(self):
        self.temp.cleanup()

    def test_the_server_gets_the_tools_of_the_login_shell_even_from_the_dock(self):
        # A Dock or desktop launch has only the system folders: uv and npx, installed by Homebrew or nvm, would look missing.
        home = self.work / "home"
        (home / ".local/bin").mkdir(parents=True)
        dock = {"PATH": "/usr/bin:/bin", "SHELL": "/bin/zsh"}
        login = Mock(return_value=["/opt/acme/node/bin", "/usr/bin"])
        path = launch.tool_path(dock, "macos", home, uv="/opt/fake/uv", shell_path=login)
        parts = path.split(os.pathsep)
        self.assertEqual(parts[:3], ["/opt/acme/node/bin", "/usr/bin", "/bin"])  # the shell's order first, each folder once
        self.assertIn("/opt/fake", parts)
        self.assertIn(str(home / ".local/bin"), parts)
        self.assertNotIn(str(home / ".cargo/bin"), parts)  # only the usual places that exist
        login.assert_called_once_with("macos", dock)
        self.assertEqual(launch.tool_path({"PATH": "winbin"}, "windows", home, shell_path=login).split(os.pathsep)[-1], "winbin")  # no usual places added
        # The launcher hands that PATH to the server it starts.
        with patch.object(launch, "find_uv", return_value="/opt/fake/uv"), patch.object(launch, "tool_path", return_value="/x:/y") as tools, \
                patch.object(launch, "start_detached", side_effect=OSError(2, "No such file or directory")) as start, \
                self.assertRaises(launch.LaunchError):
            launch.launch(free_port(), self.work, opener=self.opener)
        tools.assert_called_once_with(uv="/opt/fake/uv")
        self.assertEqual(start.call_args.kwargs["environment"]["PATH"], "/x:/y")
        self.assertEqual(start.call_args.kwargs["environment"]["PYTHONUTF8"], "1")

    def test_the_login_shell_path_is_read_between_marks_and_never_fails(self):
        script = self.work / "fake-shell"
        script.write_text('#!/bin/sh\necho "welcome banner"\nprintf "\\n__ACTIONS_PATH__=/opt/acme/bin:/usr/bin\\n"\n', encoding="utf-8")
        script.chmod(0o755)
        self.assertEqual(REAL_LOGIN_SHELL_PATH("linux", {"SHELL": str(script)}), ["/opt/acme/bin", "/usr/bin"])
        self.assertEqual(REAL_LOGIN_SHELL_PATH("linux", {"SHELL": str(self.work / "missing-shell")}), [])
        self.assertEqual(REAL_LOGIN_SHELL_PATH("windows", {}), [])

    def serve(self, handler) -> int:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_port

    def test_a_running_server_only_opens_the_page(self):
        port = self.serve(StubActions)
        with patch.object(launch, "start_detached") as start:
            self.assertEqual(launch.launch(port, self.work, opener=self.opener), "opened")
        start.assert_not_called()
        self.opener.assert_called_once_with(f"http://127.0.0.1:{port}/")
        self.assertFalse((self.work / "agents").exists())

    def test_a_port_owned_by_another_program_is_refused(self):
        port = self.serve(OtherProgram)
        with patch.object(launch, "start_detached") as start, self.assertRaises(launch.LaunchError) as raised:
            launch.launch(port, self.work, opener=self.opener, busy_attempts=3, delay=0.01)
        self.assertIn(f"Port {port} is already used by another application", str(raised.exception))
        start.assert_not_called()
        self.opener.assert_not_called()
        self.assertFalse((self.work / "agents/tasks-web.pid").exists())

    def test_a_stopped_server_is_started_detached_then_the_page_opens(self):
        port = free_port()
        result = launch.launch(port, self.work, command=[sys.executable, "-c", STUB_SERVER, str(port)], opener=self.opener,
                               start_attempts=100, delay=0.05)
        pid = int((self.work / "agents/tasks-web.pid").read_text(encoding="utf-8"))
        self.addCleanup(self.stop, pid)
        self.assertEqual(result, "started")
        self.opener.assert_called_once_with(f"http://127.0.0.1:{port}/")
        self.assertTrue(launch.ready(port))
        self.assertEqual(os.getsid(pid), pid)  # its own session: closing the launcher's terminal does not stop it
        self.assertIn("stub server ready", (self.work / "agents/tasks-web.log").read_text(encoding="utf-8"))

    def stop(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass

    def test_a_server_that_exits_is_reported_without_waiting(self):
        command = [sys.executable, "-c", "import sys; print('cannot start'); sys.exit(3)"]
        with self.assertRaises(launch.LaunchError) as raised:
            launch.launch(free_port(), self.work, command=command, opener=self.opener, start_attempts=200, delay=0.05)
        self.assertIn("did not start", str(raised.exception))
        self.assertIn("cannot start", (self.work / "agents/tasks-web.log").read_text(encoding="utf-8"))
        self.opener.assert_not_called()

    def test_the_default_command_uses_uv_and_the_server_of_this_work(self):
        port = free_port()
        with patch.object(launch, "find_uv", return_value="/opt/fake/uv"), \
                patch.object(launch, "start_detached", side_effect=OSError(2, "No such file or directory")) as start, \
                self.assertRaises(launch.LaunchError):
            launch.launch(port, self.work, opener=self.opener)
        command, cwd, log = start.call_args.args
        self.assertEqual(command, ["/opt/fake/uv", "run", str(self.work / "tools/tasks-web/tasks-web.py"), "--port", str(port)])
        self.assertEqual((cwd, log), (self.work, self.work / "agents/tasks-web.log"))
        with patch.object(launch, "find_uv", return_value=None), self.assertRaises(launch.LaunchError) as raised:
            launch.launch(free_port(), self.work, opener=self.opener)
        self.assertIn("uv was not found", str(raised.exception))

    def test_errors_go_to_stderr_the_log_and_a_dialog_unless_asked_not_to(self):
        err = io.StringIO()
        with patch.object(launch, "WORK", self.work), patch.object(launch, "launch", side_effect=launch.LaunchError("Broken.")), \
                patch.object(launch, "show_dialog") as dialog, redirect_stderr(err):
            self.assertEqual(launch.main([]), 1)
            dialog.assert_called_once_with("Broken.")
            dialog.reset_mock()
            self.assertEqual(launch.main(["--no-dialog"]), 1)
            dialog.assert_not_called()
        self.assertEqual(err.getvalue().count("Broken."), 2)
        self.assertEqual((self.work / "agents/tasks-web.log").read_text(encoding="utf-8").count("Broken."), 2)

    def test_uv_is_the_one_running_the_launcher_then_path_then_the_usual_places(self):
        root = self.work / "uv"
        running, on_path, usual = root / "running/uv", root / "path/uv", root / ".local/bin/uv"
        for path in (running, on_path, usual):
            path.parent.mkdir(parents=True)
            path.write_bytes(b"")
            path.chmod(0o755)
        self.assertEqual(launch.find_uv({"UV": str(running), "PATH": str(on_path.parent)}, "linux", root), str(running))
        self.assertEqual(launch.find_uv({"PATH": str(on_path.parent)}, "linux", root), str(on_path))
        self.assertEqual(launch.find_uv({"PATH": ""}, "linux", root), str(usual))
        windows = launch.uv_candidates("windows", {"USERPROFILE": "C:/Users/jane", "LOCALAPPDATA": "C:/Users/jane/AppData/Local"})
        self.assertEqual(windows[0], Path("C:/Users/jane/.local/bin/uv.exe"))
        self.assertIn(Path("C:/Users/jane/AppData/Local/Microsoft/WinGet/Links/uv.exe"), windows)
        self.assertIn(Path("/opt/homebrew/bin/uv"), launch.uv_candidates("macos", {}, root))

    def test_a_windowless_uvw_gives_way_to_the_console_uv_for_the_server(self):
        uvw, uv = self.work / "uvw.exe", self.work / "uv.exe"
        uvw.write_bytes(b"")
        self.assertEqual(launch.console_uv(uvw), uvw)
        uv.write_bytes(b"")
        self.assertEqual(launch.console_uv(uvw), uv)


if __name__ == "__main__":
    unittest.main()
