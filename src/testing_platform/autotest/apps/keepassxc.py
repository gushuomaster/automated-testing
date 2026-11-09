"""KeePassXC environment control and ground-truth readers for benchmark verification.

The agent never sees anything from this module except the launched application.
KeePassXC denies PROCESS_TERMINATE to same-user callers, so stop() closes windows and
answers the save prompt with "discard" (unsaved changes therefore never reach disk).
"""

from __future__ import annotations

import configparser
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

CONFIG = """[General]
ConfigVersion=2
UpdateCheckMessageShown=true
SingleInstance=true
RememberLastDatabases=false
OpenPreviousDatabasesOnStartup=false
AutoSaveAfterEveryChange=false
AutoSaveOnExit=false
AutoSaveNonDataChanges=false
BackupBeforeSave=false

[GUI]
CheckForUpdates=false
ShowTrayIcon=false
MinimizeOnClose=false
MinimizeOnStartup=false
"""
LOCAL_CONFIG = """[Security]
QuickUnlock=false
"""
DISCARD_WORDS = ("放弃", "不保存", "Discard", "关闭但不保存", "否", "No")
DETACHED = 0x00000008 | 0x00000200


def kpxc_pids() -> list[int]:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq KeePassXC.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, errors="replace").stdout
    return [int(line.split(",")[1].strip('"')) for line in out.splitlines() if line.startswith('"')]


def _windows_of(pid: int) -> list[int]:
    import win32gui
    import win32process

    hs: list[int] = []
    win32gui.EnumWindows(lambda h, _: hs.append(h) if win32gui.IsWindowVisible(h)
                         and win32process.GetWindowThreadProcessId(h)[1] == pid else None, None)
    return hs


def _answer_discard(pid: int) -> str | None:
    from pywinauto.controls.uiawrapper import UIAWrapper
    from pywinauto.uia_element_info import UIAElementInfo

    for h in _windows_of(pid):
        try:
            for el in UIAWrapper(UIAElementInfo(h)).descendants(control_type="Button"):
                name = el.element_info.name or ""
                if any(name.startswith(word) for word in DISCARD_WORDS):
                    el.invoke()
                    return name
        except Exception:
            pass
    return None


def stop(timeout: float = 20) -> list[dict]:
    import win32con
    import win32gui

    log = []
    for pid in kpxc_pids():
        for h in _windows_of(pid):
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        deadline = time.time() + timeout
        while time.time() < deadline and pid in kpxc_pids():
            time.sleep(0.7)
            answered = _answer_discard(pid)
            if answered:
                log.append({"pid": pid, "answered": answered})
            for h in _windows_of(pid):
                win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        log.append({"pid": pid, "exited": pid not in kpxc_pids()})
    return log


@dataclass
class KeePassXCEnv:
    app_dir: Path
    seed_db: Path
    password: str
    run_dir: Path
    pid: int | None = None
    db: Path = field(init=False)

    def __post_init__(self) -> None:
        self.app_dir = Path(self.app_dir)
        self.seed_db = Path(self.seed_db)
        self.run_dir = Path(self.run_dir)
        self.db = self.run_dir / "passwords.kdbx"

    @property
    def config_file(self) -> Path:
        return self.app_dir / "config" / "keepassxc.ini"

    @property
    def cli(self) -> Path:
        return self.app_dir / "keepassxc-cli.exe"

    def reset(self) -> dict:
        stopped = stop()
        if kpxc_pids():
            raise RuntimeError(f"KeePassXC still running after stop: {kpxc_pids()}")
        config = self.app_dir / "config"
        shutil.rmtree(config, ignore_errors=True)
        config.mkdir(parents=True)
        (config / "keepassxc.ini").write_text(CONFIG, encoding="utf-8")
        (config / "keepassxc_local.ini").write_text(LOCAL_CONFIG, encoding="utf-8")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.seed_db, self.db)
        return {"stopped": stopped}

    def launch(self, wait: float = 20) -> int:
        proc = subprocess.Popen([str(self.app_dir / "KeePassXC.exe"), "--allow-screencapture", str(self.db)],
                                creationflags=DETACHED)
        self.pid = proc.pid
        deadline = time.time() + wait
        while time.time() < deadline and not _windows_of(self.pid):
            time.sleep(0.5)
        if not _windows_of(self.pid):
            raise RuntimeError("KeePassXC window did not appear")
        time.sleep(1.0)
        return self.pid

    def stop(self) -> list[dict]:
        return stop()

    # ---- ground truth ------------------------------------------------------------------
    def export_xml(self) -> str:
        res = subprocess.run([str(self.cli), "export", "-q", "-f", "xml", str(self.db)],
                             input=self.password + "\n", capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        if res.returncode != 0:
            raise RuntimeError(f"keepassxc-cli export failed: {res.stderr.strip()}")
        return res.stdout

    def snapshot(self) -> "DbSnapshot":
        return parse_export(self.export_xml())

    def read_config(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        if self.config_file.exists():
            parser.read(self.config_file, encoding="utf-8")
        return parser


@dataclass
class DbSnapshot:
    groups: set[str]
    entries: dict[str, dict[str, str]]  # "群组/标题" -> fields (Title, UserName, Password, URL, Notes)

    def entries_in(self, group: str) -> list[str]:
        prefix = group + "/"
        return [p for p in self.entries if p.startswith(prefix) and "/" not in p[len(prefix):]]

    def find_title(self, title: str) -> list[str]:
        return [p for p, f in self.entries.items() if f.get("Title") == title]


def parse_export(xml_text: str) -> DbSnapshot:
    """Parse `keepassxc-cli export -f xml` output, excluding the recycle bin and entry history."""
    start = xml_text.find("<?xml")
    root = ET.fromstring(xml_text[start:] if start >= 0 else xml_text)
    recycle = root.findtext("Meta/RecycleBinUUID") or ""
    top = root.find("Root/Group")
    groups: set[str] = set()
    entries: dict[str, dict[str, str]] = {}

    def visit(group: ET.Element, prefix: str) -> None:
        for entry in group.findall("Entry"):
            fields = {}
            for s in entry.findall("String"):
                fields[s.findtext("Key") or ""] = s.findtext("Value") or ""
            path = f"{prefix}{fields.get('Title', '')}"
            entries[path] = fields
        for child in group.findall("Group"):
            if recycle and recycle != "AAAAAAAAAAAAAAAAAAAAAA==" and child.findtext("UUID") == recycle:
                continue
            name = child.findtext("Name") or ""
            path = f"{prefix}{name}"
            groups.add(path)
            visit(child, path + "/")

    if top is not None:
        visit(top, "")
    return DbSnapshot(groups=groups, entries=entries)
