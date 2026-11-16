"""Generate benchmarks/keepassxc-m1/seed.kdbx reproducibly: KeePass XML -> `keepassxc-cli import`.

keepassxc-cli 2.7.6 `add` has no TOTP option, so the TOTP entry is written as the `otp` string field
(an otpauth:// URI, the format KeePassXC's own TOTP setup dialog uses) and imported from XML.
After import the script verifies the result with `show --totp` and `export` + `parse_export`.

Usage: .venv\\Scripts\\python.exe benchmarks/keepassxc-m1/make_seed.py [--app-dir DIR] [--out PATH]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_APP = ROOT / "artifacts/feasibility-01/downloads/kpxc-2.7.6/app/KeePassXC-2.7.6-Win64"
PASSWORD = "Test@2026"
STAMP = "2026-11-13T00:00:00Z"
TOTP_URI = ("otpauth://totp/GitHub:dev%40example.com?secret=JBSWY3DPEHPK3PXP"
            "&period=30&digits=6&issuer=GitHub")

# group path -> entries (title, username, password, url, notes, extra string fields)
LAYOUT = {
    "": [
        ("路由器管理", "admin", "R0uter!2026", "http://192.168.1.1", "家里的路由器", {}),
        ("Wi-Fi 家庭网络", "", "HomeNet#8821", "", "", {}),
    ],
    "网银": [
        ("招商银行", "zhang.san", "Cmb@2026pass", "https://www.cmbchina.com", "", {}),
        ("工商银行", "zhangsan01", "Icbc$7731", "https://www.icbc.com.cn", "", {}),
    ],
    "邮箱": [
        ("QQ 邮箱", "12345678@qq.com", "QqMail#5521", "https://mail.qq.com", "", {}),
        ("Gmail", "zhang.san@gmail.com", "Gm@il2026!", "https://mail.google.com", "", {}),
        ("公司邮箱", "zhangsan@example.com", "Corp#Mail88", "https://mail.example.com", "", {}),
    ],
    "工作": [
        ("GitHub", "dev@example.com", "Gh#Dev2026", "https://github.com", "开启了两步验证", {"otp": TOTP_URI}),
        ("GitLab", "zhangsan", "Gl@b2026", "https://gitlab.example.com", "", {}),
        ("VPN", "zhangsan", "Vpn!4410", "https://vpn.example.com", "", {}),
    ],
}


def uuid_for(key: str) -> str:
    return base64.b64encode(hashlib.md5(key.encode("utf-8")).digest()).decode("ascii")


def times(parent: ET.Element) -> None:
    t = ET.SubElement(parent, "Times")
    for tag in ("LastModificationTime", "CreationTime", "LastAccessTime", "ExpiryTime", "LocationChanged"):
        ET.SubElement(t, tag).text = STAMP
    ET.SubElement(t, "Expires").text = "False"
    ET.SubElement(t, "UsageCount").text = "0"


def group(parent: ET.Element, name: str, key: str) -> ET.Element:
    g = ET.SubElement(parent, "Group")
    ET.SubElement(g, "UUID").text = uuid_for("group:" + key)
    ET.SubElement(g, "Name").text = name
    ET.SubElement(g, "IconID").text = "48"
    times(g)
    ET.SubElement(g, "IsExpanded").text = "True"
    return g


def entry(parent: ET.Element, path: str, fields: dict) -> None:
    e = ET.SubElement(parent, "Entry")
    ET.SubElement(e, "UUID").text = uuid_for("entry:" + path)
    ET.SubElement(e, "IconID").text = "0"
    times(e)
    for key, value in fields.items():
        s = ET.SubElement(e, "String")
        ET.SubElement(s, "Key").text = key
        v = ET.SubElement(s, "Value")
        v.text = value
        if key == "Password":
            v.set("ProtectInMemory", "True")


def build_xml() -> bytes:
    doc = ET.Element("KeePassFile")
    meta = ET.SubElement(doc, "Meta")
    ET.SubElement(meta, "Generator").text = "KeePassXC"
    ET.SubElement(meta, "DatabaseName").text = "测试密码库"
    ET.SubElement(meta, "RecycleBinEnabled").text = "True"
    top = group(ET.SubElement(doc, "Root"), "密码", "")
    for path, items in LAYOUT.items():
        parent = top if not path else group(top, path, path)
        for title, user, pw, url, notes, extra in items:
            entry(parent, f"{path}/{title}", {"Title": title, "UserName": user, "Password": pw,
                                             "URL": url, "Notes": notes, **extra})
    ET.indent(doc, "\t")
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(doc, encoding="utf-8")


def cli(app_dir: Path, *args: str, stdin: str) -> str:
    res = subprocess.run([str(app_dir / "keepassxc-cli.exe"), *args], input=stdin, capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=120)
    if res.returncode != 0:
        raise SystemExit(f"keepassxc-cli {args[0]} failed ({res.returncode}): {res.stderr.strip()}")
    return res.stdout


def verify(app_dir: Path, db: Path) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from testing_platform.autotest.apps.keepassxc import parse_export

    snap = parse_export(cli(app_dir, "export", "-q", "-f", "xml", str(db), stdin=PASSWORD + "\n"))
    expected = {f"{p}/{t[0]}" if p else t[0] for p, items in LAYOUT.items() for t in items}
    if set(snap.entries) != expected:
        raise SystemExit(f"entry mismatch: {sorted(set(snap.entries) ^ expected)}")
    if snap.groups != {p for p in LAYOUT if p}:
        raise SystemExit(f"group mismatch: {sorted(snap.groups)}")
    if snap.entries["工作/GitHub"].get("otp") != TOTP_URI:
        raise SystemExit("otp field missing after import")
    code = cli(app_dir, "show", "-q", "--totp", str(db), "工作/GitHub", stdin=PASSWORD + "\n").strip()
    if not (code.isdigit() and len(code) == 6):
        raise SystemExit(f"show --totp did not return a 6-digit code: {code!r}")
    print(f"verified: {len(snap.entries)} entries, groups {sorted(snap.groups)}, totp ok")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app-dir", type=Path, default=DEFAULT_APP)
    ap.add_argument("--out", type=Path, default=HERE / "seed.kdbx")
    args = ap.parse_args()
    if args.out.exists():
        args.out.unlink()
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "seed.xml"
        xml_path.write_bytes(build_xml())
        cli(args.app_dir, "import", "-q", "-p", str(xml_path), str(args.out), stdin=f"{PASSWORD}\n{PASSWORD}\n")
    verify(args.app_dir, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
