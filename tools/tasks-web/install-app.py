#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Install the Actions Brain launcher: a macOS app, a Windows Start Menu shortcut or a Linux menu entry.

Run from Work with: uv run tools/tasks-web/install-app.py [--dry-run] [--uninstall]
Each entry runs `<uv> run ... tools/tasks-web/launch.py`, which starts the local server when needed and opens the page.
The absolute path of uv is written into the entry, because desktop launchers get a minimal PATH: run the
installer again after moving Work or uv. Standard library only.

- macOS: "Actions Brain.app" (an AppleScript app, bundle id local.work.tasks-brain, the icon of static/icon.icns)
  in <artifacts>/internal/setup/tasks-dock-app/, with its launch.applescript and a README.md. Nothing in the
  artifacts folder is ever overwritten or deleted: when the app is already there the installer refuses, and
  --replace first moves the existing files into <artifacts>/archive/tasks-dock-app-<date>/; --uninstall moves the
  app it made there too.
- Windows: "Actions Brain.lnk" in the Start Menu (%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs), and on the
  Desktop with --desktop, made by PowerShell (WScript.Shell). Its target is the windowless uvw.exe next to uv.exe
  when there is one (else uv.exe, in a minimized window) with `run --gui-script <launch.py>`.
- Linux: actions-brain.desktop in $XDG_DATA_HOME/applications (default ~/.local/share), the icon in
  $XDG_DATA_HOME/icons/hicolor/256x256/apps, then update-desktop-database when it is installed.

Every file the installer writes carries MARKER (or ICON_MARKER for an icon); --uninstall touches only those, and an
existing file without it is never replaced. --dry-run prints what would be done and changes nothing. --platform
chooses the system (tests and dry runs); a real install builds the macOS app only on macOS and the Windows shortcut
only on Windows. --artifacts-dir replaces the artifacts folder of the configuration (see tools/machine/work_config.py).
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1]
LAUNCH = HERE / "launch.py"
STATIC = HERE / "static"
APP_NAME = "Actions Brain"
BUNDLE_ID = "local.work.tasks-brain"
MARKER = "installed by tools/tasks-web/install-app.py"
ICON_MARKER = b"actions-brain-icon"  # written into every icon by make-icon.py
PLIST_MARKER_KEY = "LocalWorkInstaller"
MAC_FOLDER = Path("internal/setup/tasks-dock-app")
MAC_FILES = (f"{APP_NAME}.app", "launch.applescript", "README.md")
LINK_NAME = f"{APP_NAME}.lnk"
DESKTOP_ID = "actions-brain"
DESCRIPTION = f"Open the local actions page ({MARKER})"
OSACOMPILE = Path("/usr/bin/osacompile")
PLACEHOLDER_UV = {"macos": "<uv>", "linux": "<uv>", "windows": "<uv.exe>"}  # shown by a dry run for another system
STAGING_ROOT = WORK / "agents"  # where the macOS app is compiled and finished before it moves into the artifacts folder


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launch_tool = _load("tasks_launch", LAUNCH)
work_config = _load("work_config", WORK / "tools/machine/work_config.py")


class InstallError(Exception):
    """A reason the installer stops, said to the user; nothing after it is done."""


@dataclass
class Plan:
    """What an install or an uninstall does: steps (verb, path, action) run in order, and text to show."""

    title: str
    steps: list[tuple[str, str, Callable[[], None]]] = field(default_factory=list)
    texts: list[tuple[str, str]] = field(default_factory=list)  # (label, generated text) shown by --dry-run
    notes: list[str] = field(default_factory=list)

    def add(self, verb: str, path: Path | str, action: Callable[[], None]) -> None:
        self.steps.append((verb, str(path), action))


def run_command(argv: list[str]) -> str:
    """Run a command; InstallError with its output when it fails."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                stdin=subprocess.DEVNULL, check=False)
    except OSError as error:
        raise InstallError(f"{argv[0]} could not run: {error.strerror or error}") from None
    if result.returncode:
        raise InstallError(f"{Path(argv[0]).name} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def no_line_breaks(*values: str) -> None:
    for value in values:
        if any(char in value for char in "\r\n\0"):
            raise InstallError(f"A path contains a line break, which a launcher cannot hold: {value!r}")


def write_bytes(path: Path, data: bytes) -> Callable[[], None]:
    return lambda: path.write_bytes(data)


def make_folder(path: Path) -> Callable[[], None]:
    return lambda: path.mkdir(parents=True, exist_ok=True)


def moved_to(target: Path, source: Path) -> Callable[[], None]:
    def move() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise InstallError(f"{target} already exists: nothing was moved.")
        shutil.move(str(source), str(target))
    return move


def removed(path: Path) -> Callable[[], None]:
    return lambda: path.unlink(missing_ok=True)


def resolve_uv(given: str | None, system: str, dry_run: bool) -> str:
    """The absolute uv to write into the entry: --uv, else the uv running this script, else PATH, else the usual places."""
    if given:
        path = Path(given).expanduser()
        if not dry_run and not path.is_file():
            raise InstallError(f"--uv {given}: no such file.")
        return str(path if path.is_absolute() else path.absolute())
    found = launch_tool.find_uv(system=system) if system == launch_tool.system_name() else None  # this computer's uv only
    if found:
        return found
    if dry_run:
        return PLACEHOLDER_UV[system]
    raise InstallError("uv was not found: install it, or give its path with --uv.")


def archive_folder(artifacts: Path) -> Path:
    """A new folder under <artifacts>/archive/ for the files set aside (the only move the workspace allows there)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = artifacts / "archive" / f"tasks-dock-app-{stamp}"
    number = 2
    while folder.exists():
        folder = artifacts / "archive" / f"tasks-dock-app-{stamp}-{number}"
        number += 1
    return folder


# --- macOS


def applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def applescript_source(uv: str, launch: Path) -> str:
    no_line_breaks(uv, str(launch))
    command = (f"(quoted form of {applescript_string(uv)}) & \" run --quiet --script \" & "
               f"(quoted form of {applescript_string(str(launch))}) & \" --no-dialog\"")
    return (f"-- {APP_NAME}: {MARKER}.\n"
            "-- Opens the local actions page, starting its server first when needed (tools/tasks-web/launch.py).\n"
            "on run\n"
            "    try\n"
            f"        do shell script ({command})\n"
            "    on error errorMessage\n"
            f'        display dialog ("Could not open Actions. " & errorMessage) with title "{APP_NAME}" '
            'buttons {"OK"} default button "OK" with icon stop\n'
            "    end try\n"
            "end run\n")


def mac_readme() -> str:
    return (f"# {APP_NAME} app\n\n"
            f"Local app {MARKER} (`uv run tools/tasks-web/install-app.py` from the Work repository). It runs "
            "`tools/tasks-web/launch.py` with the uv found when it was built: the script starts the tasks server if needed "
            "and opens the local page in the default browser. The code and the data stay in Work; this app is a local "
            "deliverable that is not versioned. `launch.applescript` is its source.\n\n"
            "To rebuild it (after moving Work or uv), run `uv run tools/tasks-web/install-app.py --replace`: the existing "
            "app, its source and this README move to `archive/` in the artifacts folder first, nothing is deleted. The "
            "**Quit** item in the page stops the local server. Restarting the Mac stops it too.\n")


def mark_app(app: Path) -> None:
    """Bundle id, marker and icon of a freshly compiled app (still in the staging folder), then an ad-hoc signature."""
    info = app / "Contents/Info.plist"
    with open(info, "rb") as handle:
        plist = plistlib.load(handle)
    plist["CFBundleIdentifier"] = BUNDLE_ID
    plist[PLIST_MARKER_KEY] = MARKER
    plist.pop("CFBundleIconName", None)  # the icon of Assets.car would win over CFBundleIconFile
    plist["CFBundleIconFile"] = "applet"
    with open(info, "wb") as handle:
        plistlib.dump(plist, handle)
    resources = app / "Contents/Resources"
    (resources / "Assets.car").unlink(missing_ok=True)
    (resources / "applet.icns").write_bytes((STATIC / "icon.icns").read_bytes())
    if shutil.which("codesign") or Path("/usr/bin/codesign").is_file():
        run_command([shutil.which("codesign") or "/usr/bin/codesign", "--force", "--sign", "-", str(app)])


def build_app(source_text: str, app: Path) -> Callable[[], None]:
    def build() -> None:
        STAGING_ROOT.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="actions-brain-app-", dir=STAGING_ROOT))
        try:
            source = staging / "launch.applescript"
            source.write_text(source_text, encoding="utf-8")
            built = staging / app.name
            run_command([str(OSACOMPILE), "-o", str(built), str(source)])
            mark_app(built)
            if app.exists() or app.is_symlink():
                raise InstallError(f"{app} appeared meanwhile: it was left as it is.")
            shutil.move(str(built), str(app))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return build


def app_is_ours(app: Path) -> bool:
    try:
        with open(app / "Contents/Info.plist", "rb") as handle:
            return plistlib.load(handle).get(PLIST_MARKER_KEY) == MARKER
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


def text_is_ours(path: Path) -> bool:
    try:
        return MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def macos_plan(args: argparse.Namespace) -> Plan:
    artifacts = Path(args.artifacts_dir).expanduser().absolute() if args.artifacts_dir else work_config.artifacts_dir(WORK)
    folder = artifacts / MAC_FOLDER
    app = folder / MAC_FILES[0]
    present = [folder / name for name in MAC_FILES if (folder / name).exists() or (folder / name).is_symlink()]
    if args.uninstall:
        plan = Plan(f"{APP_NAME} for macOS: uninstall")
        if not app.exists():
            plan.notes.append(f"No app at {app}: nothing to do.")
            return plan
        if not app_is_ours(app):
            plan.notes.append(f"{app} was not made by install-app.py: it was left as it is.")
            return plan
        archive = archive_folder(artifacts)
        for path in present:
            if path == app or text_is_ours(path):
                plan.add("move", f"{path} -> {archive / path.name}", moved_to(archive / path.name, path))
        plan.notes.append(f"Nothing is deleted in the artifacts folder: the app moves to {archive}. Delete that folder "
                          "yourself when you no longer need it, and take the app out of the Dock.")
        return plan
    if not args.dry_run and not OSACOMPILE.is_file():
        raise InstallError("osacompile was not found: the macOS app can only be built on macOS (use --dry-run to see it).")
    uv = resolve_uv(args.uv, "macos", args.dry_run)
    source = applescript_source(uv, LAUNCH)
    plan = Plan(f"{APP_NAME} for macOS")
    if present:
        if not args.replace:
            raise InstallError(f"{app if app in present else present[0]} already exists. Nothing in the artifacts folder is "
                               "overwritten or deleted: run again with --replace to move the existing app, its source and "
                               f"its README into {artifacts / 'archive'} first.")
        archive = archive_folder(artifacts)
        for path in present:
            plan.add("move", f"{path} -> {archive / path.name}", moved_to(archive / path.name, path))
        plan.notes.append(f"The previous files moved to {archive} (nothing deleted). If the old app is in the Dock, "
                          "remove it and drag the new one there.")
    plan.add("folder", folder, make_folder(folder))
    plan.add("write", folder / "launch.applescript", write_bytes(folder / "launch.applescript", source.encode("utf-8")))
    plan.add("build", f"{app} (osacompile, bundle id {BUNDLE_ID}, icon static/icon.icns, ad-hoc signature)", build_app(source, app))
    plan.add("write", folder / "README.md", write_bytes(folder / "README.md", mac_readme().encode("utf-8")))
    plan.texts.append(("launch.applescript", source))
    plan.notes += [f"uv: {uv}", f"App: {app} (add it to the Dock by dragging it there)."]
    return plan


# --- Windows


def powershell_string(value: str) -> str:
    """A single-quoted PowerShell string: quotes doubled, including the typographic ones PowerShell also reads as quotes."""
    return "'" + re.sub("['‘’‚‛]", lambda found: found.group(0) * 2, value) + "'"


def powershell_script(shortcut: Path, target: str, arguments: str, work: Path, icon: Path, window_style: int) -> str:
    """The PowerShell lines that create (or update) one shortcut through the WScript.Shell COM object."""
    no_line_breaks(str(shortcut), target, arguments, str(work), str(icon))
    return "\n".join(["$ErrorActionPreference = 'Stop'",
                      "$shell = New-Object -ComObject WScript.Shell",
                      f"$link = $shell.CreateShortcut({powershell_string(str(shortcut))})",
                      f"$link.TargetPath = {powershell_string(target)}",
                      f"$link.Arguments = {powershell_string(arguments)}",
                      f"$link.WorkingDirectory = {powershell_string(str(work))}",
                      f"$link.IconLocation = {powershell_string(f'{icon},0')}",
                      f"$link.Description = {powershell_string(DESCRIPTION)}",
                      f"$link.WindowStyle = {window_style}",
                      "$link.Save()"]) + "\n"


def powershell_command(script: str) -> list[str]:
    """powershell.exe with the script as -EncodedCommand (UTF-16LE, base64): no quoting of the command line at all."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]


def windows_desktop() -> Path:
    """The Desktop folder (OneDrive-redirected included) on Windows, else %USERPROFILE%\\Desktop."""
    if sys.platform == "win32":
        import ctypes

        buffer = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0:  # type: ignore[attr-defined]  # CSIDL_DESKTOPDIRECTORY
            return Path(buffer.value)
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop"


def link_is_ours(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return MARKER.encode("utf-16-le") in data or MARKER.encode("utf-8") in data


def windows_links(desktop: bool) -> list[Path]:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise InstallError("APPDATA is not set: the Start Menu folder cannot be found.")
    links = [Path(appdata) / "Microsoft/Windows/Start Menu/Programs" / LINK_NAME]
    return links + [windows_desktop() / LINK_NAME] if desktop else links


def create_link(script: str, link: Path) -> Callable[[], None]:
    def create() -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        run_command(powershell_command(script))
    return create


def windows_plan(args: argparse.Namespace) -> Plan:
    if args.uninstall:
        plan = Plan(f"{APP_NAME} for Windows: uninstall")
        for link in windows_links(True):
            if link_is_ours(link):
                plan.add("remove", link, removed(link))
            elif link.exists():
                plan.notes.append(f"{link} was not made by install-app.py: it was left as it is.")
        if not plan.steps:
            plan.notes.append("No shortcut made by install-app.py was found.")
        return plan
    links = windows_links(args.desktop)
    for link in links:
        if link.exists() and not link_is_ours(link):
            raise InstallError(f"{link} exists and was not made by install-app.py: it was left as it is. Move it away, "
                               "then run the installer again.")
    if not args.dry_run and launch_tool.system_name() != "windows":
        raise InstallError("The Windows shortcut can only be created on Windows (use --dry-run to see it).")
    uv = resolve_uv(args.uv, "windows", args.dry_run)
    windowless = Path(uv).with_name("uvw.exe")
    if uv == PLACEHOLDER_UV["windows"]:
        target, style = "<uvw.exe next to uv.exe>", 1
    else:
        target, style = (str(windowless), 1) if windowless.is_file() else (uv, 7)  # 7: minimized, when only uv.exe exists
    arguments = f'run --gui-script "{LAUNCH}"'
    plan = Plan(f"{APP_NAME} for Windows")
    for link in links:
        script = powershell_script(link, target, arguments, WORK, STATIC / "icon.ico", style)
        plan.add("shortcut", link, create_link(script, link))
        plan.texts.append((f"PowerShell script for {link} (powershell.exe -NoProfile -NonInteractive -EncodedCommand)", script))
    plan.notes.append(f"Target: {target} {arguments}")
    if style == 7:
        plan.notes.append("uvw.exe was not found next to uv.exe: the shortcut runs uv.exe in a minimized window. "
                          "Update uv (uv self update) and run the installer again for no window at all.")
    return plan


# --- Linux


def desktop_value(value: str) -> str:
    """A string value of a Desktop Entry key: backslash escaped (spec, "Possible value types")."""
    no_line_breaks(value)
    return value.replace("\\", "\\\\").replace("\t", "\\t")


def desktop_exec_argument(value: str) -> str:
    """One Exec argument: double-quoted with `"`, backquote, `$` and `\\` escaped, `%` doubled, then escaped as a string."""
    no_line_breaks(value)
    quoted = '"' + re.sub(r'(["`$\\])', r"\\\1", value) + '"'
    return desktop_value(quoted.replace("%", "%%"))


def xdg_data_home() -> Path:
    value = os.environ.get("XDG_DATA_HOME", "")
    return Path(value) if value and Path(value).is_absolute() else Path(os.environ.get("HOME") or Path.home()) / ".local/share"


def desktop_entry(uv: str, launch: Path, work: Path, icon: Path) -> str:
    command = " ".join(desktop_exec_argument(part) for part in (uv, "run", "--quiet", "--script", str(launch)))
    return ("[Desktop Entry]\n"
            "Type=Application\n"
            "Version=1.5\n"
            f"Name={APP_NAME}\n"
            "Comment=Open the local actions page of the Work brains\n"
            f"Exec={command}\n"
            f"Path={desktop_value(str(work))}\n"
            f"Icon={desktop_value(str(icon))}\n"
            "Terminal=false\n"
            "Categories=Office;\n"
            "StartupNotify=false\n"
            f"X-Actions-Brain={MARKER}\n")


def icon_is_ours(path: Path) -> bool:
    try:
        return ICON_MARKER in path.read_bytes()
    except OSError:
        return False


def refresh_menu(applications: Path) -> Callable[[], None]:
    def refresh() -> None:
        program = shutil.which("update-desktop-database")
        if program:
            try:
                run_command([program, str(applications)])
            except InstallError as error:
                print(f"warning: {error}", file=sys.stderr)
    return refresh


def linux_plan(args: argparse.Namespace) -> Plan:
    data = xdg_data_home()
    applications = data / "applications"
    entry = applications / f"{DESKTOP_ID}.desktop"
    icon = data / "icons/hicolor/256x256/apps" / f"{DESKTOP_ID}.png"
    if args.uninstall:
        plan = Plan(f"{APP_NAME} for Linux: uninstall")
        for path, ours in ((entry, text_is_ours(entry)), (icon, icon_is_ours(icon))):
            if ours:
                plan.add("remove", path, removed(path))
            elif path.exists():
                plan.notes.append(f"{path} was not made by install-app.py: it was left as it is.")
        if plan.steps:
            plan.add("refresh", "update-desktop-database (when installed)", refresh_menu(applications))
        else:
            plan.notes.append("No menu entry made by install-app.py was found.")
        return plan
    for path, ours in ((entry, text_is_ours(entry)), (icon, icon_is_ours(icon))):
        if path.exists() and not ours:
            raise InstallError(f"{path} exists and was not made by install-app.py: it was left as it is. Move it away, "
                               "then run the installer again.")
    uv = resolve_uv(args.uv, "linux", args.dry_run)
    text = desktop_entry(uv, LAUNCH, WORK, icon)
    plan = Plan(f"{APP_NAME} for Linux")
    plan.add("folder", applications, make_folder(applications))
    plan.add("write", entry, write_bytes(entry, text.encode("utf-8")))
    plan.add("folder", icon.parent, make_folder(icon.parent))
    plan.add("write", icon, write_bytes(icon, (STATIC / "icon.png").read_bytes()))
    plan.add("refresh", "update-desktop-database (when installed)", refresh_menu(applications))
    plan.texts.append((entry.name, text))
    plan.notes.append(f"uv: {uv}")
    return plan


# --- command line


PLANS = {"macos": macos_plan, "windows": windows_plan, "linux": linux_plan}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--platform", choices=sorted(PLANS), help="the system to install for (default: this one)")
    parser.add_argument("--dry-run", action="store_true", help="print what would be done, change nothing")
    parser.add_argument("--uninstall", action="store_true", help="remove what this installer made (macOS: move the app to archive/)")
    parser.add_argument("--desktop", action="store_true", help="Windows: also put the shortcut on the Desktop")
    parser.add_argument("--replace", action="store_true", help="macOS: move an existing app into <artifacts>/archive/ first")
    parser.add_argument("--artifacts-dir", metavar="DIR", help="macOS: this folder instead of the configured artifacts folder")
    parser.add_argument("--uv", metavar="PATH", help="this uv instead of the one found")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    system = args.platform or launch_tool.system_name()
    try:
        if args.desktop and system != "windows":
            raise InstallError("--desktop is for the Windows shortcut only.")
        if (args.replace or args.artifacts_dir) and system != "macos":
            raise InstallError("--replace and --artifacts-dir are for the macOS app only.")
        plan = PLANS[system](args)
        print(plan.title + (" (dry run: nothing is changed)" if args.dry_run else ""))
        for verb, path, action in plan.steps:
            print(f"  {verb:<8} {path}")
            if not args.dry_run:
                action()
        if args.dry_run:
            for label, text in plan.texts:
                print(f"\n{label}:\n" + "".join(f"    {line}\n" for line in text.splitlines()))
        for note in plan.notes:
            print(note)
    except InstallError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 even through a pipe on Windows, where the default is the ANSI code page
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors=_stream.errors)
    raise SystemExit(main())
