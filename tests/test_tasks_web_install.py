# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Installer (install-app.py), launcher (launch.py) and native window (window.py) of Corvus, the local actions app.

Everything runs on a fake home, a fake APPDATA, a fake XDG_DATA_HOME, a fake artifacts folder and a fake uv: nothing outside
a temporary folder is written. PowerShell is never run, no real window is opened and pywebview is never imported.
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
import time
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath, PureWindowsPath
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
window = load("tasks_window_under_test", WEB / "window.py")  # imports pywebview only when a window is created
REAL_PREWARM = install.prewarm  # MacInstallTest patches it out; its own test calls the real one
REAL_LOGIN_SHELL_PATH = launch.login_shell_path  # LaunchTest patches it out; its own test calls the real one


def entry_value(path: Path) -> str:
    """A path as a Desktop Entry value: each `\\` doubled (a Windows host's paths have some, POSIX ones none)."""
    return str(path).replace("\\", "\\\\")


def exec_argument(path: Path) -> str:
    """A path as a quoted Exec argument: `\\` escaped inside the quotes, then again as a value."""
    return '"' + str(path).replace("\\", "\\" * 4) + '"'


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
        return self.xdg / "applications/corvus.desktop"

    def icon(self) -> Path:
        return self.xdg / "icons/hicolor/256x256/apps/corvus.png"

    def test_the_desktop_entry_runs_the_launcher_with_the_absolute_uv(self):
        with patch.object(install.shutil, "which", return_value=None):
            code, out, err = self.installer("--platform", "linux", "--uv", str(self.uv))
        self.assertEqual(code, 0, err)
        lines = self.entry().read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "[Desktop Entry]")
        for line in ("Type=Application", "Name=Corvus", "Terminal=false", "Categories=Office;",
                     f"Path={entry_value(install.WORK)}", f"Icon={entry_value(self.icon())}", f"X-Actions-Brain={install.MARKER}"):
            self.assertIn(line, lines)
        self.assertIn(f'Exec={exec_argument(self.uv)} "run" "--quiet" "--script" {exec_argument(install.LAUNCH)}', lines)
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
        self.assertIn(f'Exec={exec_argument(other)}', self.entry().read_text(encoding="utf-8"))

    def legacy_files(self) -> tuple[Path, Path]:
        entry, icon = self.xdg / "applications/actions-brain.desktop", self.xdg / "icons/hicolor/256x256/apps/actions-brain.png"
        entry.parent.mkdir(parents=True)
        icon.parent.mkdir(parents=True)
        entry.write_text(f"[Desktop Entry]\nName=Actions Brain\nX-Actions-Brain={install.MARKER}\n", encoding="utf-8")
        icon.write_bytes(b"\x89PNG " + install.ICON_MARKER)
        return entry, icon

    def test_an_install_replaces_the_legacy_entry_of_ours_and_the_uninstall_removes_it(self):
        entry, icon = self.legacy_files()
        with patch.object(install.shutil, "which", return_value=None):
            self.assertEqual(self.installer("--platform", "linux", "--uv", str(self.uv))[0], 0)
            self.assertFalse(entry.exists() or icon.exists())
            self.assertTrue(self.entry().is_file())
            entry, icon = self.legacy_files() if not entry.parent.exists() else (entry, icon)
            entry.write_text(f"[Desktop Entry]\nName=Actions Brain\nX-Actions-Brain={install.MARKER}\n", encoding="utf-8")
            code, _, err = self.installer("--platform", "linux", "--uninstall")
        self.assertEqual(code, 0, err)
        self.assertFalse(entry.exists() or self.entry().exists())

    def test_a_legacy_entry_that_is_not_ours_is_left_alone(self):
        entry, icon = self.legacy_files()
        entry.write_text("[Desktop Entry]\nName=Actions Brain\n", encoding="utf-8")
        with patch.object(install.shutil, "which", return_value=None):
            self.assertEqual(self.installer("--platform", "linux", "--uv", str(self.uv))[0], 0)
        self.assertTrue(entry.exists())
        self.assertFalse(icon.exists())  # the icon carries our mark


class WindowsInstallTest(FakeHomes):
    def start_menu_link(self) -> Path:
        return self.appdata / "Microsoft/Windows/Start Menu/Programs/Corvus.lnk"

    def desktop_link(self) -> Path:
        return self.profile / "Desktop/Corvus.lnk"

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
        link = Path("/fake/Start Menu/Programs/Corvus.lnk")
        # Windows paths whatever the host: a Path would print C:/Work’s on macOS and C:\Work’s on Windows.
        script = install.powershell_script(link, "C:/Users/o'neil/.local/bin/uvw.exe", 'run --gui-script "C:/Work’s/launch.py"',
                                           PureWindowsPath("C:/Work’s"), PureWindowsPath("C:/Work’s/icon.ico"), 1)
        lines = script.splitlines()
        self.assertEqual(lines[:2], ["$ErrorActionPreference = 'Stop'", "$shell = New-Object -ComObject WScript.Shell"])
        self.assertIn(f"$link = $shell.CreateShortcut('{link}')", lines)
        self.assertIn("$link.TargetPath = 'C:/Users/o''neil/.local/bin/uvw.exe'", lines)
        self.assertIn("$link.Arguments = 'run --gui-script \"C:/Work’’s/launch.py\"'", lines)
        self.assertIn("$link.WorkingDirectory = 'C:\\Work’’s'", lines)
        self.assertIn("$link.IconLocation = 'C:\\Work’’s\\icon.ico,0'", lines)
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
        # Any host stands for a non-Windows one here: on Windows the real install would run PowerShell.
        with patch.object(install.launch_tool, "system_name", return_value="linux"):
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

    def legacy_link(self) -> Path:
        return self.start_menu_link().with_name("Actions Brain.lnk")

    def test_an_install_removes_the_legacy_shortcut_of_ours(self):
        self.legacy_link().parent.mkdir(parents=True)
        self.legacy_link().write_bytes(b"L\0\0\0" + install.MARKER.encode("utf-16-le"))
        calls = []
        with patch.object(install.launch_tool, "system_name", return_value="windows"), \
                patch.object(install, "run_command", side_effect=self.fake_powershell(calls)):
            code, out, err = self.installer("--platform", "windows", "--uv", str(self.uv_exe))
        self.assertEqual(code, 0, err)
        self.assertFalse(self.legacy_link().exists())
        self.assertTrue(self.start_menu_link().is_file())

    def test_uninstall_also_removes_the_legacy_shortcut_and_keeps_one_that_is_not_ours(self):
        self.legacy_link().parent.mkdir(parents=True)
        self.legacy_link().write_bytes(b"L\0\0\0" + install.MARKER.encode("utf-16-le"))
        self.assertEqual(self.installer("--platform", "windows", "--uninstall")[0], 0)
        self.assertFalse(self.legacy_link().exists())
        self.legacy_link().write_bytes(b"L\0\0\0other")
        self.assertEqual(self.installer("--platform", "windows", "--uninstall")[0], 0)
        self.assertTrue(self.legacy_link().exists())


class MacInstallTest(FakeHomes):
    def folder(self) -> Path:
        return self.artifacts / "internal/setup/tasks-dock-app"

    def setUp(self):
        super().setUp()
        self.system = patch.object(install.launch_tool, "system_name", return_value="macos")  # a real build is macOS's
        self.system.start()
        self.addCleanup(self.system.stop)
        warm = patch.object(install, "prewarm", return_value=lambda: None)  # never download pywebview from a test
        self.warm = warm.start()
        self.addCleanup(warm.stop)
        sign = patch.object(install, "sign")  # nor sign: codesign only matters on the real bundle
        self.sign = sign.start()
        self.addCleanup(sign.stop)

    def build(self, uv: Path | None = None) -> Path:
        code, _, err = self.installer("--platform", "macos", "--artifacts-dir", str(self.artifacts), "--uv", str(uv or self.uv))
        self.assertEqual(code, 0, err)
        return self.folder() / "Corvus.app"

    def make_legacy(self) -> Path:
        """What an install of the AppleScript era left: Actions Brain.app (marked), launch.applescript and the README."""
        old_app = self.folder() / "Actions Brain.app"
        (old_app / "Contents").mkdir(parents=True)
        with open(old_app / "Contents/Info.plist", "wb") as handle:
            plistlib.dump({"CFBundleIdentifier": install.BUNDLE_ID, install.PLIST_MARKER_KEY: install.MARKER}, handle)
        (self.folder() / "launch.applescript").write_text(f"-- Actions Brain: {install.MARKER}.\n", encoding="utf-8")
        (self.folder() / "README.md").write_text(f"old readme {install.MARKER}\n", encoding="utf-8")
        return old_app

    def test_the_bundle_has_the_plist_the_icon_and_an_executable_script(self):
        app = self.build()
        with open(app / "Contents/Info.plist", "rb") as handle:
            info = plistlib.load(handle)
        for key, value in {"CFBundleExecutable": "Corvus", "CFBundleName": "Corvus", "CFBundleDisplayName": "Corvus",
                           "CFBundleIdentifier": "local.work.tasks-brain", "CFBundleIconFile": "icon", "CFBundlePackageType": "APPL",
                           "NSHighResolutionCapable": True, install.PLIST_MARKER_KEY: install.MARKER}.items():
            self.assertEqual(info[key], value, key)
        for key in ("CFBundleShortVersionString", "LSMinimumSystemVersion"):
            self.assertTrue(info[key], key)
        self.assertEqual((app / "Contents/Resources/icon.icns").read_bytes(), (WEB / "static/icon.icns").read_bytes())
        executable = app / "Contents/MacOS/Corvus"
        self.assertTrue(os.access(executable, os.X_OK))
        self.assertEqual(executable.read_text(encoding="utf-8"), install.bundle_script(str(self.uv), install.LAUNCH, install.WINDOW))
        self.assertTrue(install.app_is_ours(app))
        self.assertIn(install.MARKER, (self.folder() / "README.md").read_text(encoding="utf-8"))
        self.assertIn("Corvus", (self.folder() / "README.md").read_text(encoding="utf-8"))
        self.assertEqual(list((self.root / "staging").iterdir()), [])  # the staging folder is cleaned
        self.assertFalse(any(path.is_symlink() for path in app.rglob("*")))  # OneDrive does not sync symlinks
        self.sign.assert_called_once()
        self.warm.assert_called_once_with(str(self.uv))
        self.assertFalse((self.folder() / "launch.applescript").exists())

    def test_the_script_becomes_the_bundle_process_and_quotes_its_paths(self):
        script = install.bundle_script("/opt/u'v dir/uv", PurePosixPath("/srv/My Work/tools/tasks-web/launch.py"),
                                       PurePosixPath("/srv/My Work/tools/tasks-web/window.py"), 8765)
        lines = script.splitlines()
        self.assertEqual(lines[0], "#!/bin/zsh")
        self.assertIn(install.MARKER, lines[1])
        self.assertIn('export CFProcessPath="${0:A}"', lines)
        self.assertIn("python=$('/opt/u'\\''v dir/uv' run --quiet --script '/srv/My Work/tools/tasks-web/launch.py' --prepare-window) || exit 0", lines)
        self.assertIn("[[ -n $python ]] || exit 0", lines)
        self.assertEqual(lines[-1], 'exec "$python" \'/srv/My Work/tools/tasks-web/window.py\' --port 8765')
        self.assertLess(lines.index('export CFProcessPath="${0:A}"'), lines.index(lines[-1]))
        with self.assertRaises(install.InstallError):
            install.bundle_script("/opt/uv\n", Path("/srv/launch.py"), Path("/srv/window.py"))

    @unittest.skipIf(os.name == "nt", "zsh is a macOS and Linux shell")
    @unittest.skipUnless(shutil.which("zsh"), "needs zsh")
    def test_the_quoted_script_hands_odd_paths_to_the_shell_intact(self):
        # Run the script with stand-ins for uv and the Python: the odd paths must reach them as single arguments.
        odd = self.root / "it's a \"dir\" $HOME"
        odd.mkdir()
        record = self.root / "record.txt"
        uv, python = odd / "uv", self.root / "python"  # the interpreter's own path is only echoed, so it stays plain
        uv.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}"\necho "{python}"\n', encoding="utf-8")
        python.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{record}"\n', encoding="utf-8")
        uv.chmod(0o755)
        python.chmod(0o755)
        script = self.root / "Corvus"
        script.write_text(install.bundle_script(str(uv), odd / "launch.py", odd / "window.py", 8765), encoding="utf-8")
        script.chmod(0o755)
        subprocess.run([str(script)], check=True, capture_output=True, timeout=20)
        self.assertEqual(record.read_text(encoding="utf-8").splitlines(),
                         ["run", "--quiet", "--script", str(odd / "launch.py"), "--prepare-window", str(odd / "window.py"), "--port", "8765"])

    def test_nothing_is_compiled_and_no_applescript_is_written(self):
        self.assertFalse(hasattr(install, "OSACOMPILE") or hasattr(install, "applescript_source"))
        with patch.object(install.subprocess, "run") as run:
            self.build()
        run.assert_not_called()  # sign and prewarm are patched: the build itself runs no command
        self.assertFalse(list(self.folder().glob("*.applescript")))

    def test_dry_run_writes_nothing(self):
        before = self.snapshot()
        code, out, err = self.installer("--platform", "macos", "--dry-run", "--artifacts-dir", str(self.artifacts), "--uv", str(self.uv))
        self.assertEqual(code, 0, err)
        self.assertIn("CFProcessPath", out)
        self.assertIn("--prepare-window", out)
        self.assertIn("CFBundleDisplayName", out)
        self.assertNotIn("osacompile", out)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.artifacts.exists())

    def test_a_real_build_needs_macos(self):
        with patch.object(install.launch_tool, "system_name", return_value="linux"):
            code, _, err = self.installer("--platform", "macos", "--artifacts-dir", str(self.artifacts), "--uv", str(self.uv))
        self.assertEqual(code, 1)
        self.assertIn("only be built on macOS", err)
        self.assertFalse(self.artifacts.exists())

    def test_the_prewarm_runs_window_check_and_never_fails_the_install(self):
        passed = Mock(returncode=0, stdout="/env/bin/python\n", stderr="")
        failed = Mock(returncode=1, stdout="", stderr="no wheel\nboom\n")
        outcomes = [(passed, "pywebview is ready"), (failed, "boom"), (OSError(2, "No such file"), "could not run"),
                    (subprocess.TimeoutExpired("uv", 1), "more than")]
        for outcome, expected in outcomes:
            with patch.object(install.subprocess, "run", side_effect=[outcome] if isinstance(outcome, BaseException) else None,
                              return_value=outcome) as run, redirect_stdout(io.StringIO()) as out:
                REAL_PREWARM("/opt/uv")()
            self.assertEqual(run.call_args.args[0], ["/opt/uv", "run", "--quiet", "--script", str(install.WINDOW), "--check"])
            self.assertIn(expected, out.getvalue())

    def test_an_existing_app_is_never_overwritten_or_deleted(self):
        old_app = self.make_legacy()
        before = self.snapshot()
        code, _, err = self.installer("--platform", "macos", "--artifacts-dir", str(self.artifacts), "--uv", str(self.uv))
        self.assertEqual(code, 1)
        self.assertIn("--replace", err)
        self.assertEqual(self.snapshot(), before)
        code, out, err = self.installer("--platform", "macos", "--replace", "--artifacts-dir", str(self.artifacts), "--uv", str(self.uv))
        self.assertEqual(code, 0, err)
        archived = list((self.artifacts / "archive").glob("tasks-dock-app-*"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(sorted(path.name for path in archived[0].iterdir()), ["Actions Brain.app", "README.md", "launch.applescript"])
        self.assertTrue(install.app_is_ours(self.folder() / "Corvus.app"))
        self.assertFalse(old_app.exists())
        self.assertIn(install.MARKER, (self.folder() / "README.md").read_text(encoding="utf-8"))
        self.assertNotIn("old readme", (self.folder() / "README.md").read_text(encoding="utf-8"))
        self.assertIn(str(archived[0]), out)
        # Nothing was deleted: every file present before is still somewhere under the artifacts folder, unchanged.
        contents = list(self.snapshot().values())
        for data in before.values():
            self.assertIn(data, contents)

    def test_replace_also_archives_a_previous_corvus_app(self):
        first = self.build()
        code, out, err = self.installer("--platform", "macos", "--artifacts-dir", str(self.artifacts), "--uv", str(self.uv))
        self.assertEqual(code, 1)
        self.assertIn("--replace", err)
        other = self.root / "bin/uv2"
        other.write_bytes(b"fake uv")
        code, out, err = self.installer("--platform", "macos", "--replace", "--artifacts-dir", str(self.artifacts), "--uv", str(other))
        self.assertEqual(code, 0, err)
        archived = next((self.artifacts / "archive").glob("tasks-dock-app-*"))
        self.assertIn(str(self.uv), (archived / "Corvus.app/Contents/MacOS/Corvus").read_text(encoding="utf-8"))
        self.assertIn(str(other), (first / "Contents/MacOS/Corvus").read_text(encoding="utf-8"))

    def test_uninstall_moves_only_its_own_apps_into_the_archive(self):
        app = self.folder() / "Corvus.app"
        (app / "Contents").mkdir(parents=True)
        (app / "Contents/Info.plist").write_bytes(b"not ours")
        code, out, err = self.installer("--platform", "macos", "--uninstall", "--artifacts-dir", str(self.artifacts))
        self.assertEqual(code, 0, err)
        self.assertIn("was not made by install-app.py", out)
        self.assertTrue(app.exists())
        shutil.rmtree(app)  # the test's own fixture, in the temporary folder
        self.build()
        (self.folder() / "notes.txt").write_text("the owner's file\n", encoding="utf-8")
        code, out, err = self.installer("--platform", "macos", "--uninstall", "--artifacts-dir", str(self.artifacts))
        self.assertEqual(code, 0, err)
        archived = next((self.artifacts / "archive").glob("tasks-dock-app-*"))
        self.assertEqual(sorted(path.name for path in archived.iterdir()), ["Corvus.app", "README.md"])
        self.assertFalse(app.exists())
        self.assertEqual((self.folder() / "notes.txt").read_text(encoding="utf-8"), "the owner's file\n")
        self.assertIn("Nothing is deleted", out)

    def test_uninstall_also_archives_the_legacy_app_of_ours(self):
        old_app = self.make_legacy()
        code, out, err = self.installer("--platform", "macos", "--uninstall", "--artifacts-dir", str(self.artifacts))
        self.assertEqual(code, 0, err)
        archived = next((self.artifacts / "archive").glob("tasks-dock-app-*"))
        self.assertEqual(sorted(path.name for path in archived.iterdir()), ["Actions Brain.app", "README.md", "launch.applescript"])
        self.assertFalse(old_app.exists())

    def test_a_legacy_app_that_is_not_ours_is_left_alone_on_uninstall(self):
        old_app = self.folder() / "Actions Brain.app"
        (old_app / "Contents").mkdir(parents=True)
        (old_app / "Contents/Info.plist").write_bytes(b"not ours")
        code, out, err = self.installer("--platform", "macos", "--uninstall", "--artifacts-dir", str(self.artifacts))
        self.assertEqual(code, 0, err)
        self.assertTrue(old_app.exists())
        self.assertFalse((self.artifacts / "archive").exists())

    def test_options_of_another_system_are_refused(self):
        self.assertEqual(self.installer("--platform", "linux", "--desktop", "--dry-run")[0], 1)
        self.assertEqual(self.installer("--platform", "windows", "--replace", "--dry-run")[0], 1)


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
        self.addCleanup(self.temp.cleanup)  # first in, last out: after a started server let go of its log (Windows)
        self.work = Path(self.temp.name)
        self.opener = Mock(return_value=True)
        shell = patch.object(launch, "login_shell_path", return_value=[])  # never the tester's own shell startup files
        shell.start()
        self.addCleanup(shell.stop)

    def test_the_server_gets_the_tools_of_the_login_shell_even_from_the_dock(self):
        # A Dock or desktop launch has only the system folders: uv and npx, installed by Homebrew or nvm, would look missing.
        home = self.work / "home"
        (home / ".local/bin").mkdir(parents=True)
        dock = {"PATH": os.pathsep.join(["/usr/bin", "/bin"]), "SHELL": "/bin/zsh"}  # the PATH of this host, its separator
        login = Mock(return_value=["/opt/acme/node/bin", "/usr/bin"])
        uv = str(Path("/opt/fake/uv"))
        path = launch.tool_path(dock, "macos", home, uv=uv, shell_path=login)
        parts = path.split(os.pathsep)
        self.assertEqual(parts[:3], ["/opt/acme/node/bin", "/usr/bin", "/bin"])  # the shell's order first, each folder once
        self.assertIn(str(Path(uv).parent), parts)
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

    @unittest.skipIf(os.name == "nt", "a login shell's PATH is read on macOS and Linux only, and Windows cannot run a #! script")
    def test_the_login_shell_path_is_read_between_marks_and_never_fails(self):
        script = self.work / "fake-shell"
        script.write_text('#!/bin/sh\necho "welcome banner"\nprintf "\\n__ACTIONS_PATH__=/opt/acme/bin:/usr/bin\\n"\n', encoding="utf-8")
        script.chmod(0o755)
        self.assertEqual(REAL_LOGIN_SHELL_PATH("linux", {"SHELL": str(script)}), ["/opt/acme/bin", "/usr/bin"])
        self.assertEqual(REAL_LOGIN_SHELL_PATH("linux", {"SHELL": str(self.work / "missing-shell")}), [])

    def test_windows_has_no_login_shell_path_to_read(self):
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
        self.addCleanup(self.stop, pid, self.work / "agents/tasks-web.log")
        self.assertEqual(result, "started")
        self.opener.assert_called_once_with(f"http://127.0.0.1:{port}/")
        self.assertTrue(launch.ready(port))
        if hasattr(os, "getsid"):
            self.assertEqual(os.getsid(pid), pid)  # its own session: closing the launcher's terminal does not stop it
        self.assertIn("stub server ready", (self.work / "agents/tasks-web.log").read_text(encoding="utf-8"))

    def stop(self, pid: int, log: Path) -> None:
        """Stop the server the test started, with its children, so that the temporary folder can be removed."""
        if os.name == "nt":
            # No process group to signal: end the whole tree (a virtual environment's python.exe runs the real one as
            # a child), then wait until the log, open in the server, can be deleted.
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            for _ in range(100):
                try:
                    log.unlink(missing_ok=True)
                    return
                except PermissionError:
                    time.sleep(0.05)
            return
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
        # The PATH lookup is this host's (on Windows, only a name with a PATHEXT extension such as uv.exe is found).
        system, exe = ("windows", "uv.exe") if os.name == "nt" else ("linux", "uv")
        running, on_path, usual = root / "running" / exe, root / "path" / exe, root / ".local/bin" / exe
        for path in (running, on_path, usual):
            path.parent.mkdir(parents=True)
            path.write_bytes(b"")
            path.chmod(0o755)
        self.assertEqual(launch.find_uv({"UV": str(running), "PATH": str(on_path.parent)}, system, root), str(running))
        # normcase: on Windows, shutil.which spells the extension as PATHEXT does (uv.EXE).
        self.assertEqual(os.path.normcase(launch.find_uv({"PATH": str(on_path.parent)}, system, root)), os.path.normcase(on_path))
        self.assertEqual(launch.find_uv({"PATH": ""}, system, root), str(usual))
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


class FakeWindow:
    """Stands for the Popen of window.py: it shows (writes the ready file) or exits after a given number of polls."""

    def __init__(self, ready: Path | None = None, shows_after: int | None = None, exits_with: int | None = None, exits_after: int = 0):
        self.ready, self.shows_after, self.exits_with, self.exits_after = ready, shows_after, exits_with, exits_after
        self.polls = 0
        self.pid = 4242

    def poll(self):
        self.polls += 1
        if self.shows_after is not None and self.polls > self.shows_after and self.ready is not None:
            self.ready.write_text("1\n", encoding="utf-8")
        if self.exits_with is not None and self.polls > self.exits_after:
            return self.exits_with
        return None


class OpenChainTest(unittest.TestCase):
    """Native window, then a Chrome app window, then the default browser: every step with injected functions."""

    URL = "http://127.0.0.1:8765/"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        shell = patch.object(launch, "login_shell_path", return_value=[])
        shell.start()
        self.addCleanup(shell.stop)

    def log(self) -> str:
        path = self.work / "agents/tasks-web.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_macos_opens_chrome_then_edge_then_chromium_or_brave_as_an_app(self):
        home = Path("/Users/jane")
        def command(*installed):
            return launch.app_mode_command(self.URL, "macos", {}, home, exists=lambda path: str(path) in installed)
        self.assertEqual(command("/Applications/Google Chrome.app", "/Applications/Microsoft Edge.app"),
                         ["open", "-na", "Google Chrome", "--args", f"--app={self.URL}"])
        self.assertEqual(command("/Users/jane/Applications/Microsoft Edge.app", "/Applications/Brave Browser.app"),
                         ["open", "-na", "Microsoft Edge", "--args", f"--app={self.URL}"])
        self.assertEqual(command("/Applications/Brave Browser.app")[3:4], ["--args"])
        self.assertEqual(command("/Applications/Brave Browser.app")[2], "Brave Browser")
        self.assertIsNone(command("/Applications/Safari.app"))

    def test_windows_looks_in_program_files_and_local_app_data(self):
        environ = {"ProgramFiles": "C:/PF", "ProgramFiles(x86)": "C:/PF86", "LOCALAPPDATA": "C:/Local"}
        def command(*installed):
            return launch.app_mode_command(self.URL, "windows", environ, Path("C:/Users/jane"), exists=lambda path: str(path) in installed)
        self.assertEqual(command("C:/PF86/Microsoft/Edge/Application/msedge.exe"),
                         ["C:/PF86/Microsoft/Edge/Application/msedge.exe", f"--app={self.URL}"])
        self.assertEqual(command("C:/Local/Google/Chrome/Application/chrome.exe", "C:/PF86/Microsoft/Edge/Application/msedge.exe")[0],
                         "C:/Local/Google/Chrome/Application/chrome.exe")  # Chrome before Edge, wherever it is
        self.assertEqual(command("C:/Local/BraveSoftware/Brave-Browser/Application/brave.exe")[0],
                         "C:/Local/BraveSoftware/Brave-Browser/Application/brave.exe")
        self.assertIsNone(command())

    def test_linux_takes_the_first_browser_on_the_path(self):
        found = {"chromium-browser": "/usr/bin/chromium-browser", "microsoft-edge": "/usr/bin/microsoft-edge"}
        which = lambda name, path=None: found.get(name)  # noqa: E731
        self.assertEqual(launch.app_mode_command(self.URL, "linux", {"PATH": "/usr/bin"}, which=which),
                         ["/usr/bin/chromium-browser", f"--app={self.URL}"])
        self.assertIsNone(launch.app_mode_command(self.URL, "linux", {}, which=lambda name, path=None: None))

    def test_the_fallback_prefers_the_app_window_then_the_browser_and_logs_its_choice(self):
        browser = Mock(return_value=True)
        starter = Mock(return_value=True)
        self.assertEqual(launch.open_fallback(self.URL, self.work, lambda url: ["/usr/bin/google-chrome", f"--app={url}"], starter, browser), "app-mode")
        starter.assert_called_once_with(["/usr/bin/google-chrome", f"--app={self.URL}"])
        browser.assert_not_called()
        self.assertIn("app window: google-chrome", self.log())
        self.assertEqual(launch.open_fallback(self.URL, self.work, lambda url: None, starter, browser), "browser")
        browser.assert_called_once_with(self.URL)
        self.assertIn("No Chrome, Edge, Chromium or Brave", self.log())
        browser.reset_mock()
        failing = Mock(return_value=False)
        self.assertEqual(launch.open_fallback(self.URL, self.work, lambda url: ["x"], failing, browser), "browser")
        self.assertIn("could not start", self.log())
        self.assertEqual(launch.open_fallback(self.URL, self.work, lambda url: None, starter, Mock(return_value=False)), "")
        self.assertIn("did not open the page", self.log())

    def test_the_window_command_runs_window_py_through_uv(self):
        self.assertEqual(launch.window_command("/opt/uv", self.work, 8765, "macos"),
                         ["/opt/uv", "run", "--quiet", "--script", str(self.work / "tools/tasks-web/window.py"), "--port", "8765", "--no-fallback"])
        uvw = self.work / "uvw.exe"
        uvw.write_bytes(b"")
        windows = launch.window_command(str(self.work / "uv.exe"), self.work, 9000, "windows", no_fallback=False)
        self.assertEqual(windows[:4], [str(uvw), "run", "--quiet", "--gui-script"])
        self.assertEqual(windows[-2:], ["--port", "9000"])
        self.assertEqual(launch.window_command(str(self.work / "uv.exe"), self.work, 9000, "linux")[3], "--script")

    def open_window(self, process: FakeWindow, **options) -> tuple[bool, Mock, Mock]:
        starter = Mock(return_value=process)
        stopper = Mock()
        result = launch.open_native_window(8765, self.work, "/opt/uv", starter=starter, delay=0.001, system="linux", stopper=stopper, **options)
        return result, starter, stopper

    def test_the_native_window_is_waited_for_until_its_ready_file(self):
        agents = self.work / "agents"
        agents.mkdir()
        (agents / launch.READY_FILE).write_text("stale\n", encoding="utf-8")  # a stale file must not count
        result, starter, stopper = self.open_window(FakeWindow(agents / launch.READY_FILE, shows_after=3), wait=5)
        self.assertTrue(result)
        command, cwd, log = starter.call_args.args
        self.assertEqual(command[:5], ["/opt/uv", "run", "--quiet", "--script", str(self.work / "tools/tasks-web/window.py")])
        self.assertIn("--no-fallback", command)  # launch.py runs the fallback itself
        self.assertEqual((cwd, log, starter.call_args.kwargs["append"]), (self.work, agents / "tasks-web.log", True))
        self.assertTrue((agents / launch.PREPARED_FILE).exists())
        stopper.assert_not_called()
        self.assertIn("native window", self.log())

    def test_a_window_that_fails_times_out_or_cannot_start_is_reported_without_stopping_the_launch(self):
        result, _, _ = self.open_window(FakeWindow(exits_with=1, exits_after=2), wait=5)
        self.assertFalse(result)
        self.assertIn("stopped with code 1", self.log())
        (self.work / "agents" / launch.PREPARED_FILE).write_text("x\n", encoding="utf-8")
        result, _, stopper = self.open_window(FakeWindow(), wait=0.05)
        self.assertFalse(result)
        stopper.assert_called_once()
        self.assertFalse((self.work / "agents" / launch.PREPARED_FILE).exists())  # the next start waits long again
        self.assertIn("did not show within", self.log())
        with patch.object(launch, "find_uv", return_value=None):
            self.assertFalse(launch.open_native_window(8765, self.work, system="linux"))
        self.assertIn("uv was not found", self.log())
        starter = Mock(side_effect=OSError(2, "No such file or directory"))
        self.assertFalse(launch.open_native_window(8765, self.work, "/opt/uv", starter=starter, system="linux"))
        self.assertIn("could not start", self.log())

    def test_a_second_start_that_raised_the_open_window_counts_as_shown(self):
        result, _, _ = self.open_window(FakeWindow(exits_with=0), wait=5)
        self.assertTrue(result)
        self.assertIn("raised", self.log())

    def test_the_first_wait_is_long_and_the_next_ones_short(self):
        with patch.object(launch, "WINDOW_FIRST_WAIT", 0.02), patch.object(launch, "WINDOW_WAIT", 0.0):
            first, _, _ = self.open_window(FakeWindow())  # never shows
            self.assertFalse(first)
            self.assertIn("within 0.02 s", self.log())
            (self.work / "agents" / launch.PREPARED_FILE).write_text("x\n", encoding="utf-8")
            second, _, _ = self.open_window(FakeWindow())
            self.assertFalse(second)
            self.assertIn("within 0 s", self.log())

    def test_macos_opens_the_installed_bundle_first_and_only_spawns_window_py_without_it(self):
        agents = self.work / "agents"
        agents.mkdir()
        ready = agents / launch.READY_FILE
        starter = Mock()
        def installed(bundle_id):
            self.assertEqual(bundle_id, "local.work.tasks-brain")
            ready.write_text(f"{os.getpid()}\n", encoding="utf-8")  # the bundle's window shows
            return True
        opener = Mock(side_effect=installed)
        self.assertTrue(launch.open_native_window(8765, self.work, "/opt/uv", starter=starter, wait=2, delay=0.001, system="macos", bundle_opener=opener))
        starter.assert_not_called()
        self.assertIn("Corvus.app", self.log())
        # Already running: `open -b` only activates it, and the ready file of a live process counts at once.
        opener = Mock(return_value=True)
        self.assertTrue(launch.open_native_window(8765, self.work, "/opt/uv", starter=starter, wait=2, delay=0.001, system="macos", bundle_opener=opener))
        opener.assert_called_once()
        starter.assert_not_called()
        # A stale ready file (dead process) does not count: the app did not show.
        ready.write_text("999999999\n", encoding="utf-8")
        self.assertFalse(launch.open_native_window(8765, self.work, "/opt/uv", starter=starter, wait=0.05, delay=0.001, system="macos", bundle_opener=Mock(return_value=True)))
        self.assertIn("did not show", self.log())
        starter.assert_not_called()
        # No app installed: window.py runs as before.
        starter = Mock(return_value=FakeWindow(ready, shows_after=1))
        ready.unlink()
        self.assertTrue(launch.open_native_window(8765, self.work, "/opt/uv", starter=starter, wait=2, delay=0.001, system="macos", bundle_opener=Mock(return_value=False)))
        starter.assert_called_once()

    def test_open_bundle_runs_open_with_the_bundle_id(self):
        with patch.object(launch.subprocess, "run", return_value=Mock(returncode=0)) as run:
            self.assertTrue(launch.open_bundle())
        self.assertEqual(run.call_args.args[0], ["open", "-b", "local.work.tasks-brain"])
        with patch.object(launch.subprocess, "run", return_value=Mock(returncode=1)):
            self.assertFalse(launch.open_bundle())
        with patch.object(launch.subprocess, "run", side_effect=OSError()):
            self.assertFalse(launch.open_bundle())

    def serve(self) -> int:
        server = ThreadingHTTPServer(("127.0.0.1", 0), StubActions)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_port

    def test_launch_tries_the_window_then_the_fallback_and_browser_mode_skips_the_window(self):
        port = self.serve()
        with patch.object(launch, "open_native_window", return_value=True) as window, patch.object(launch, "open_fallback") as fallback:
            self.assertEqual(launch.launch(port, self.work), "opened")
        window.assert_called_once_with(port, self.work)
        fallback.assert_not_called()
        with patch.object(launch, "open_native_window", return_value=False) as window, \
                patch.object(launch, "open_fallback", return_value="app-mode") as fallback:
            self.assertEqual(launch.launch(port, self.work), "opened")
        fallback.assert_called_once_with(f"http://127.0.0.1:{port}/", self.work)
        with patch.object(launch, "open_native_window") as window, patch.object(launch, "open_fallback", return_value="browser") as fallback:
            self.assertEqual(launch.launch(port, self.work, native=False), "opened")
        window.assert_not_called()
        fallback.assert_called_once()
        with patch.object(launch, "open_native_window", return_value=False), patch.object(launch, "open_fallback", return_value=""), \
                self.assertRaises(launch.LaunchError):
            launch.launch(port, self.work)

    def test_the_browser_option_skips_the_native_window(self):
        with patch.object(launch, "launch") as run:
            self.assertEqual(launch.main(["--browser", "--no-dialog"]), 0)
            self.assertEqual(run.call_args.kwargs["native"], False)
            launch.main([])
            self.assertEqual(run.call_args.kwargs["native"], True)


class PrepareWindowTest(unittest.TestCase):
    """--prepare-window prints the environment's Python on stdout and nothing else; on failure it opens the page itself."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        for target, value in (("WORK", self.work), ):
            patcher = patch.object(launch, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, kwargs in (("ensure_server", {"return_value": "running"}), ("find_uv", {"return_value": "/opt/uv"})):
            patcher = patch.object(launch, name, **kwargs)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        dialog = patch.object(launch, "show_dialog")
        self.dialog = dialog.start()
        self.addCleanup(dialog.stop)

    def run_main(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = launch.main(["--prepare-window", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_success_prints_only_the_python_path(self):
        noisy = Mock(returncode=0, stdout=f"downloading pywebview\n{sys.executable}\n", stderr="progress")
        with patch.object(launch.subprocess, "run", return_value=noisy) as run, patch.object(launch, "open_fallback") as fallback:
            code, out, err = self.run_main()
        self.assertEqual((code, out), (0, f"{sys.executable}\n"))
        fallback.assert_not_called()
        command = run.call_args.args[0]
        self.assertEqual(command, ["/opt/uv", "run", "--quiet", "--script", str(self.work / "tools/tasks-web/window.py"), "--check"])
        self.assertEqual(run.call_args.kwargs["timeout"], launch.CHECK_TIMEOUT)
        self.assertGreaterEqual(launch.CHECK_TIMEOUT, 180)
        self.assertTrue((self.work / "agents" / launch.PREPARED_FILE).exists())

    def test_a_failed_check_opens_the_fallback_and_prints_nothing(self):
        broken = Mock(returncode=1, stdout="", stderr="no matching wheel\n")
        timeout = subprocess.TimeoutExpired("uv", 180)
        for outcome in (dict(return_value=broken), dict(side_effect=timeout), dict(side_effect=OSError(2, "No such file")),
                        dict(return_value=Mock(returncode=0, stdout="/no/such/python\n", stderr=""))):
            with patch.object(launch.subprocess, "run", **outcome), patch.object(launch, "open_fallback", return_value="app-mode") as fallback:
                code, out, err = self.run_main()
            self.assertEqual((code, out), (0, ""), outcome)
            fallback.assert_called_once_with("http://127.0.0.1:8765/", self.work)
        self.assertIn("Native window unavailable", (self.work / "agents/tasks-web.log").read_text(encoding="utf-8"))

    def test_nothing_to_open_the_page_is_an_error_with_an_empty_stdout(self):
        with patch.object(launch.subprocess, "run", return_value=Mock(returncode=1, stdout="", stderr="")), \
                patch.object(launch, "open_fallback", return_value=""):
            code, out, err = self.run_main()
        self.assertEqual((code, out), (1, ""))
        self.assertIn("Could not open Corvus", err)

    def test_a_server_that_cannot_start_is_an_error_with_an_empty_stdout(self):
        self.ensure_server.side_effect = launch.LaunchError("Corvus did not start.")
        with patch.object(launch.subprocess, "run") as run:
            code, out, err = self.run_main("--no-dialog")
        self.assertEqual((code, out), (1, ""))
        run.assert_not_called()
        self.assertIn("did not start", err)
        self.dialog.assert_not_called()


class WindowHelpersTest(unittest.TestCase):
    """The parts of window.py that need no GUI: the port watcher, the lock, the raise file and the error path."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.agents = Path(self.temp.name) / "agents"

    def watch(self, sequence: list[bool], limit: int = 3) -> tuple[list[int], int, bool]:
        stop, gone, it = threading.Event(), [], iter(sequence)
        checks = []

        def check() -> bool:
            try:
                checks.append(next(it))
            except StopIteration:  # nothing left to say: the window "closed by itself"
                stop.set()
                return True
            return checks[-1]
        result = window.watch_port(lambda: gone.append(len(checks)), check, stop, 0.0, limit)
        return gone, len(checks), result

    def test_the_mac_window_asks_the_page_for_room_under_its_title_bar(self):
        self.assertEqual(window.window_url(8765, "darwin"), "http://127.0.0.1:8765/?shell=mac")
        self.assertEqual(window.window_url(8765, "win32"), "http://127.0.0.1:8765/")
        self.assertEqual(window.window_url(8770, "linux"), "http://127.0.0.1:8770/")

    def test_the_mac_title_bar_is_transparent_over_full_size_content(self):
        calls = []

        class Native:
            def styleMask(self):
                return 0b1111

            def setStyleMask_(self, mask):
                calls.append(("mask", mask))

            def setTitlebarAppearsTransparent_(self, value):
                calls.append(("transparent", value))

            def setTitleVisibility_(self, value):
                calls.append(("title", value))

            def setToolbar_(self, toolbar):
                calls.append(("toolbar", toolbar.identifier, toolbar.separator))

            def setToolbarStyle_(self, style):
                calls.append(("toolbar style", style))

            def contentView(self):
                return content

        class Toolbar:
            def __init__(self):
                self.identifier = self.separator = None

            @classmethod
            def alloc(cls):
                return cls()

            def initWithIdentifier_(self, identifier):
                self.identifier = identifier
                return self

            def setShowsBaselineSeparator_(self, value):
                self.separator = value

        class View:
            def __init__(self, name, paints=True):
                self.name, self.paints, self.subviews_ = name, paints, []

            def superview(self):
                return frame

            def subviews(self):
                return self.subviews_

            def respondsToSelector_(self, selector):
                return self.paints and selector == "setBackgroundColor:"

            def setBackgroundColor_(self, color):
                calls.append(("background", self.name, color))

        frame, content = View("frame"), View("content")
        frame.subviews_ = [content, View("titlebar"), View("other", paints=False)]
        appkit = types.SimpleNamespace(NSWindowStyleMaskFullSizeContentView=1 << 15, NSWindowTitleHidden=1, NSToolbar=Toolbar,
                                       NSWindowToolbarStyleUnified=1, NSColor=types.SimpleNamespace(clearColor=lambda: "clear"))
        with patch.dict(sys.modules, {"AppKit": appkit}):
            window.blend_title_bar(Native())
        # A 52 px title row (an empty unified toolbar, no separator); the title bar's grey (painted by pywebview) is cleared and the
        # page's own view is left alone.
        self.assertEqual(calls, [("mask", 0b1111 | 1 << 15), ("transparent", True), ("title", 1), ("toolbar", "corvus", False),
                                 ("toolbar style", 1), ("background", "titlebar", "clear")])

    def test_the_window_closes_after_three_failed_checks_in_a_row(self):
        self.assertEqual(self.watch([True, False, False, False, True]), ([4], 4, True))  # closed on the third failure, no more checks
        self.assertEqual(self.watch([False, False, False]), ([3], 3, True))

    def test_a_success_resets_the_count(self):
        gone, checks, result = self.watch([False, False, True, False, False, True, False])
        self.assertEqual((gone, result), ([], False))
        self.assertEqual(self.watch([False, False, True, False, False, False])[0], [6])

    def watch_server(self, ports: list[bool], states: list, no_pid_wait: float = 90.0, step: float = 1.0) -> tuple[list, bool]:
        """A fake clock advances `step` per check; `states` gives process() per call (the last one repeats)."""
        stop, gone, now, it, calls = threading.Event(), [], [0.0], iter(ports), []

        def check() -> bool:
            try:
                value = next(it)
            except StopIteration:
                stop.set()
                return True
            now[0] += step
            return value

        def process():
            calls.append(1)
            return states[min(len(calls), len(states)) - 1]
        result = window.watch_port(lambda: gone.append(now[0]), check, stop, 0.0, 3, process, no_pid_wait, lambda: now[0])
        return gone, result

    def test_a_restart_keeps_the_window_while_the_server_process_lives(self):
        # An in-page Update: the port is closed for a long time, the process (same PID after the exec) is alive.
        gone, result = self.watch_server([False] * 200 + [True], [True])
        self.assertEqual((gone, result), ([], False))

    def test_a_quit_closes_the_window_once_the_process_is_gone(self):
        gone, result = self.watch_server([False] * 10, [False])
        self.assertEqual(gone, [3.0])  # the third failed check, process dead
        gone, result = self.watch_server([False] * 10, [True, True, False])  # alive for two looks, then gone
        self.assertEqual((len(gone), result), (1, True))
        self.assertGreater(gone[0], 3.0)

    def test_without_a_pid_the_port_must_stay_closed_for_the_long_delay(self):
        gone, _ = self.watch_server([False] * 200, [None], no_pid_wait=90.0)
        self.assertEqual(gone, [91.0])  # closed since t=1 s, 90 s later
        gone, _ = self.watch_server([False] * 50 + [True] + [False] * 50, [None], no_pid_wait=90.0)
        self.assertEqual(gone, [])  # the page came back: the count starts over, never reaching 90 s

    def test_the_pid_file_says_alive_dead_or_unknown(self):
        pid_file = self.agents / "tasks-web.pid"
        self.assertIsNone(window.server_alive(pid_file))
        pid_file.parent.mkdir(parents=True)
        for text in ("", "abc\n", "0\n", "-5\n"):
            pid_file.write_text(text, encoding="utf-8")
            self.assertIsNone(window.server_alive(pid_file), text)
        pid_file.write_text("4242\n", encoding="utf-8")
        self.assertTrue(window.server_alive(pid_file, lambda pid: pid == 4242))
        self.assertFalse(window.server_alive(pid_file, lambda pid: False))
        self.assertTrue(window.pid_alive(os.getpid()))
        self.assertFalse(window.pid_alive(2 ** 22 + 12345 if os.name != "nt" else 0xFFFFFFF0))

    def test_the_watcher_stops_when_the_window_closed_first(self):
        stop = threading.Event()
        stop.set()
        called = Mock()
        self.assertFalse(window.watch_port(called, lambda: False, stop, 0.0))
        called.assert_not_called()

    def test_port_open_tells_a_listening_port_from_a_closed_one(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            self.assertTrue(window.port_open(server.getsockname()[1]))
        self.assertFalse(window.port_open(free_port()))

    def test_one_instance_holds_the_lock_until_it_lets_go(self):
        first, second = window.InstanceLock(self.agents / "w.lock"), window.InstanceLock(self.agents / "w.lock")
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        self.assertTrue(second.acquire())
        second.release()
        second.release()  # twice is harmless

    def test_a_raise_request_is_consumed_once_and_wakes_the_watcher(self):
        path = self.agents / "w.raise"
        self.assertFalse(window.take_raise_request(path))
        window.request_raise(path)
        self.assertTrue(path.exists())
        self.assertTrue(window.take_raise_request(path))
        self.assertFalse(window.take_raise_request(path))
        stop, woke = threading.Event(), threading.Event()
        thread = threading.Thread(target=window.watch_raise, args=(path, woke.set, stop, 0.01), daemon=True)
        thread.start()
        self.assertFalse(woke.wait(0.05))
        window.request_raise(path)
        self.assertTrue(woke.wait(2))
        stop.set()
        thread.join(2)
        self.assertFalse(path.exists())

    def test_a_second_start_raises_the_first_window_and_exits_cleanly(self):
        holder = window.InstanceLock(self.agents / window.LOCK_FILE)
        self.assertTrue(holder.acquire())
        self.addCleanup(holder.release)
        with patch.object(window, "AGENTS", self.agents), patch.object(window.sys, "platform", "linux"), \
                patch.object(window, "run_window") as run:
            self.assertEqual(window.main(["--port", "9"]), 0)
        run.assert_not_called()
        self.assertTrue((self.agents / window.RAISE_FILE).exists())

    def test_a_window_that_fails_logs_the_error_and_opens_the_fallback_unless_told_not_to(self):
        with patch.object(window, "AGENTS", self.agents), patch.object(window.sys, "platform", "linux"), \
                patch.object(window, "run_window", side_effect=RuntimeError("no GTK")), patch.object(window, "fall_back") as fall_back:
            self.assertEqual(window.main(["--port", "9"]), 1)
            fall_back.assert_called_once_with(9)
            self.assertEqual(window.main(["--port", "9", "--no-fallback"]), 1)
            fall_back.assert_called_once()
        self.assertIn("RuntimeError: no GTK", (self.agents / "tasks-web.log").read_text(encoding="utf-8"))
        self.assertTrue(window.InstanceLock(self.agents / window.LOCK_FILE).acquire())  # the lock was released

    def test_check_prints_the_interpreter_and_needs_only_the_import(self):
        out = io.StringIO()
        with patch.dict(sys.modules, {"webview": Mock()}), redirect_stdout(out):
            self.assertEqual(window.main(["--check"]), 0)
        self.assertEqual(out.getvalue(), f"{sys.executable}\n")

    def test_the_window_settings_are_corvuss(self):
        self.assertEqual((window.TITLE, window.SIZE, window.MIN_SIZE, window.APP_ID), ("Corvus", (1280, 840), (720, 480), install.BUNDLE_ID))
        self.assertTrue(window.ICON.is_file())
        self.assertEqual(window.page_url(8765), "http://127.0.0.1:8765/")


if __name__ == "__main__":
    unittest.main()
