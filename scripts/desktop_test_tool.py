"""Minimal Windows desktop test tool for AI-driven GUI testing experiments.

Each invocation is one short-lived process so a hung UIA/COM call can be
bounded by an outer timeout. Every command appends one JSON line to the
session log. Element paths are dot-separated child indexes under a top-level
window of the target process (e.g. "0.3.1"; window index first).

Commands:
  launch EXE [ARGS...]        start a program, wait for its first window
  windows --pid P             list top-level windows of the process
  tree --pid P [--depth N]    dump UIA tree (type, name, auto_id, rect, value, state)
  shot --pid P [--grid]       capture the foreground window of the process
  click --pid P (--path X | --xy X,Y) [--double|--right]
  type --pid P --text T       type text into the focused control
  keys --pid P --keys K       send key sequence (pywinauto syntax, e.g. "^a{DEL}")
  set --pid P --path X --value V   ValuePattern.SetValue
  invoke --pid P --path X     InvokePattern / select / toggle
  read --pid P --path X       read one element's properties
  kill --pid P                terminate the process
"""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ctypes.windll.shcore.SetProcessDpiAwareness(2)

import warnings

warnings.filterwarnings("ignore", category=SyntaxWarning)

from PIL import ImageDraw  # noqa: E402
from pywinauto import keyboard, mouse  # noqa: E402
from pywinauto.controls.uiawrapper import UIAWrapper  # noqa: E402
from pywinauto.uia_element_info import UIAElementInfo  # noqa: E402
import win32gui  # noqa: E402
import win32process  # noqa: E402

DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

LOG_DIR = Path(os.environ.get("DTT_LOG_DIR", "dtt-logs"))


def now():
    return datetime.now(timezone.utc).isoformat()


def log(record):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"ts": now(), **record}
    with (LOG_DIR / "actions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=1))


def window_handles(pid):
    """Visible top-level HWNDs of a process, without walking the whole UIA desktop
    (one unresponsive foreign window can hang a desktop-wide UIA enumeration)."""
    handles = []

    def collect(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1] == pid:
            if win32gui.GetWindowText(hwnd) or win32gui.GetWindow(hwnd, 4) == 0:  # GW_OWNER
                handles.append(hwnd)

    win32gui.EnumWindows(collect, None)
    fg = win32gui.GetForegroundWindow()
    handles.sort(key=lambda h: h != fg)
    return handles


def top_windows(pid):
    return [UIAWrapper(UIAElementInfo(h)) for h in window_handles(pid)]


def resolve(pid, path):
    parts = [int(p) for p in path.split(".")]
    node = top_windows(pid)[parts[0]]
    for idx in parts[1:]:
        node = node.children()[idx]
    return node


def rect_of(el):
    r = el.rectangle()
    return [r.left, r.top, r.right, r.bottom]


def describe(el):
    info = el.element_info
    d = {
        "type": info.control_type,
        "name": info.name,
        "auto_id": info.automation_id,
        "class": info.class_name,
        "rect": rect_of(el),
        "enabled": info.enabled,
    }
    try:
        d["value"] = el.iface_value.CurrentValue
    except Exception:
        pass
    for attr, key in (("get_toggle_state", "toggle"), ("is_selected", "selected"),
                      ("get_expand_state", "expand")):
        try:
            d[key] = getattr(el, attr)()
        except Exception:
            pass
    try:
        d["focused"] = el.has_keyboard_focus()
    except Exception:
        pass
    return d


def walk(el, path, depth, max_depth, out, limit):
    if len(out) >= limit:
        return
    d = describe(el)
    d["path"] = path
    d["depth"] = depth
    out.append(d)
    if depth >= max_depth:
        return
    try:
        kids = el.children()
    except Exception as exc:
        d["children_error"] = str(exc)
        return
    for i, kid in enumerate(kids):
        walk(kid, f"{path}.{i}", depth + 1, max_depth, out, limit)


class Refused(Exception):
    """Input was not sent because it could land outside the target process."""


def owner_pid(hwnd):
    return win32process.GetWindowThreadProcessId(hwnd)[1] if hwnd else 0


def foreground_is(pid):
    return owner_pid(win32gui.GetForegroundWindow()) == pid


def focus_window(pid):
    """Bring the target to the foreground or refuse; never act on another window."""
    hwnd = window_handles(pid)[0]
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
    for _ in range(3):
        if foreground_is(pid):
            break
        fg = win32gui.GetForegroundWindow()
        user32 = ctypes.windll.user32
        cur = ctypes.windll.kernel32.GetCurrentThreadId()
        fg_thread = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
        attached = fg_thread and user32.AttachThreadInput(cur, fg_thread, True)
        try:
            win32gui.ShowWindow(hwnd, 5)  # SW_SHOW
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        finally:
            if attached:
                user32.AttachThreadInput(cur, fg_thread, False)
        time.sleep(0.4)
    if not foreground_is(pid):
        raise Refused(f"target pid {pid} is not foreground; foreground pid is "
                      f"{owner_pid(win32gui.GetForegroundWindow())}")
    return UIAWrapper(UIAElementInfo(hwnd))


def guard_point(pid, x, y):
    hit = win32gui.WindowFromPoint((x, y))
    root = win32gui.GetAncestor(hit, 3) if hit else 0  # GA_ROOTOWNER
    if owner_pid(hit) != pid and owner_pid(root) != pid:
        raise Refused(f"point {x},{y} belongs to pid {owner_pid(hit)}, not target {pid}")


def guard_keys(pid):
    if not foreground_is(pid):
        raise Refused(f"foreground changed to pid {owner_pid(win32gui.GetForegroundWindow())}")


def cmd_launch(args):
    proc = subprocess.Popen([args.exe, *args.args], cwd=args.cwd or None, creationflags=DETACHED)
    deadline = time.time() + args.wait
    pid, title = proc.pid, None
    exe_name = Path(args.exe).name.lower()
    while time.time() < deadline:
        handles = window_handles(proc.pid)
        if not handles:
            # Launchers may hand the UI to another process of the same image.
            handles = [h for h in all_window_handles()
                       if process_name(win32process.GetWindowThreadProcessId(h)[1]) == exe_name]
        if handles:
            pid = win32process.GetWindowThreadProcessId(handles[0])[1]
            title = win32gui.GetWindowText(handles[0])
            break
        time.sleep(0.5)
    emit(log({"cmd": "launch", "exe": args.exe, "args": args.args, "pid": pid,
              "launcher_pid": proc.pid, "title": title}))


def all_window_handles():
    handles = []
    win32gui.EnumWindows(lambda h, _: handles.append(h) if win32gui.IsWindowVisible(h) else None, None)
    return handles


def process_name(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, errors="replace").stdout
    return out.split(",")[0].strip('"').lower() if out.startswith('"') else ""


def cmd_windows(args):
    wins = [{"index": i, "title": w.window_text(), "rect": rect_of(w)}
            for i, w in enumerate(top_windows(args.pid))]
    emit(log({"cmd": "windows", "pid": args.pid, "windows": wins}))


def cmd_tree(args):
    out = []
    roots = top_windows(args.pid)
    for i, win in enumerate(roots):
        if args.window is not None and i != args.window:
            continue
        root = win if not args.root else resolve(args.pid, args.root)
        walk(root, args.root or str(i), 0, args.depth, out, args.limit)
        if args.root:
            break
    log({"cmd": "tree", "pid": args.pid, "root": args.root, "count": len(out)})
    for d in out:
        indent = "  " * d.pop("depth")
        extras = {k: v for k, v in d.items() if k not in ("path", "type", "name", "auto_id", "class")}
        print(f"{indent}[{d['path']}] {d['type']} name={d['name']!r} id={d['auto_id']!r} "
              f"cls={d['class']!r} {json.dumps(extras, ensure_ascii=False)}")


def capture_window(hwnd):
    """Render the window itself (PrintWindow), so an occluding window is never captured."""
    import win32ui
    from PIL import Image

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    src = win32gui.GetWindowDC(hwnd)
    dc = win32ui.CreateDCFromHandle(src)
    mem = dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(dc, w, h)
    mem.SelectObject(bmp)
    ok = ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2)  # PW_RENDERFULLCONTENT
    info = bmp.GetInfo()
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]),
                           bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    win32gui.DeleteObject(bmp.GetHandle())
    mem.DeleteDC()
    dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, src)
    if not ok:
        raise RuntimeError("PrintWindow failed")
    return img, [left, top, right, bottom]


def cmd_shot(args):
    hwnd = window_handles(args.pid)[0]
    img, (left, top, right, bottom) = capture_window(hwnd)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H%M%S%f")
    raw = LOG_DIR / f"shot-{stamp}.png"
    img.save(raw)
    out = raw
    if args.grid:
        g = img.convert("RGB")
        draw = ImageDraw.Draw(g)
        step = args.grid
        for x in range(0, g.width, step):
            draw.line([(x, 0), (x, g.height)], fill=(255, 0, 0), width=1)
            draw.text((x + 2, 2), str(x), fill=(255, 0, 0))
        for y in range(0, g.height, step):
            draw.line([(0, y), (g.width, y)], fill=(255, 0, 0), width=1)
            draw.text((2, y + 2), str(y), fill=(255, 0, 0))
        out = LOG_DIR / f"shot-{stamp}-grid.png"
        g.save(out)
    emit(log({"cmd": "shot", "pid": args.pid, "window_rect": [left, top, right, bottom],
              "file": str(out.resolve()), "raw": str(raw.resolve()),
              "note": "xy for click --xy are relative to window_rect top-left"}))


def cmd_click(args):
    win = focus_window(args.pid)
    if args.path:
        el = resolve(args.pid, args.path)
        l, t, r, b = rect_of(el)
        x, y = (l + r) // 2, (t + b) // 2
        target = describe(el)
    else:
        wl, wt, _, _ = rect_of(win)
        rx, ry = (int(v) for v in args.xy.split(","))
        x, y = wl + rx, wt + ry
        target = {"window_relative": [rx, ry]}
    button = "right" if args.right else "left"
    guard_point(args.pid, x, y)
    if args.double:
        mouse.double_click(button=button, coords=(x, y))
    else:
        mouse.click(button=button, coords=(x, y))
    time.sleep(args.settle)
    emit(log({"cmd": "click", "pid": args.pid, "path": args.path, "screen_xy": [x, y],
              "button": button, "double": args.double, "target": target}))


def cmd_type(args):
    focus_window(args.pid)
    guard_keys(args.pid)
    keyboard.send_keys(args.text, with_spaces=True, pause=0.02, vk_packet=True)
    time.sleep(args.settle)
    emit(log({"cmd": "type", "pid": args.pid, "text": args.text}))


def cmd_keys(args):
    focus_window(args.pid)
    guard_keys(args.pid)
    keyboard.send_keys(args.keys, pause=0.05)
    time.sleep(args.settle)
    emit(log({"cmd": "keys", "pid": args.pid, "keys": args.keys}))


def cmd_set(args):
    el = resolve(args.pid, args.path)
    el.iface_value.SetValue(args.value)
    time.sleep(args.settle)
    emit(log({"cmd": "set", "pid": args.pid, "path": args.path, "value": args.value,
              "after": describe(el)}))


def cmd_invoke(args):
    el = resolve(args.pid, args.path)
    used = None
    for name in ("invoke", "select", "toggle", "expand"):
        try:
            getattr(el, name)()
            used = name
            break
        except Exception:
            continue
    time.sleep(args.settle)
    emit(log({"cmd": "invoke", "pid": args.pid, "path": args.path, "pattern": used,
              "target": describe(el)}))


def cmd_focus(args):
    focus_window(args.pid)
    el = resolve(args.pid, args.path)
    el.set_focus()
    time.sleep(args.settle)
    emit(log({"cmd": "focus", "pid": args.pid, "path": args.path, "after": describe(el)}))


def cmd_read(args):
    el = resolve(args.pid, args.path)
    d = describe(el)
    try:
        d["texts"] = el.texts()[:20]
    except Exception:
        pass
    emit(log({"cmd": "read", "pid": args.pid, "path": args.path, "element": d}))


def cmd_kill(args):
    subprocess.run(["taskkill", "/PID", str(args.pid), "/T", "/F"], capture_output=True)
    emit(log({"cmd": "kill", "pid": args.pid}))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("launch"); s.add_argument("exe"); s.add_argument("args", nargs="*")
    s.add_argument("--cwd"); s.add_argument("--wait", type=float, default=20); s.set_defaults(fn=cmd_launch)
    s = sub.add_parser("windows"); s.add_argument("--pid", type=int, required=True); s.set_defaults(fn=cmd_windows)
    s = sub.add_parser("tree"); s.add_argument("--pid", type=int, required=True)
    s.add_argument("--depth", type=int, default=6); s.add_argument("--limit", type=int, default=400)
    s.add_argument("--window", type=int); s.add_argument("--root"); s.set_defaults(fn=cmd_tree)
    s = sub.add_parser("shot"); s.add_argument("--pid", type=int, required=True)
    s.add_argument("--grid", type=int, nargs="?", const=50); s.set_defaults(fn=cmd_shot)
    s = sub.add_parser("click"); s.add_argument("--pid", type=int, required=True)
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--path"); g.add_argument("--xy")
    s.add_argument("--double", action="store_true"); s.add_argument("--right", action="store_true")
    s.set_defaults(fn=cmd_click)
    s = sub.add_parser("type"); s.add_argument("--pid", type=int, required=True)
    s.add_argument("--text", required=True); s.set_defaults(fn=cmd_type)
    s = sub.add_parser("keys"); s.add_argument("--pid", type=int, required=True)
    s.add_argument("--keys", required=True); s.set_defaults(fn=cmd_keys)
    s = sub.add_parser("set"); s.add_argument("--pid", type=int, required=True)
    s.add_argument("--path", required=True); s.add_argument("--value", required=True); s.set_defaults(fn=cmd_set)
    s = sub.add_parser("invoke"); s.add_argument("--pid", type=int, required=True)
    s.add_argument("--path", required=True); s.set_defaults(fn=cmd_invoke)
    s = sub.add_parser("focus"); s.add_argument("--pid", type=int, required=True)
    s.add_argument("--path", required=True); s.set_defaults(fn=cmd_focus)
    s = sub.add_parser("read"); s.add_argument("--pid", type=int, required=True)
    s.add_argument("--path", required=True); s.set_defaults(fn=cmd_read)
    s = sub.add_parser("kill"); s.add_argument("--pid", type=int, required=True); s.set_defaults(fn=cmd_kill)
    for sp in sub.choices.values():
        sp.add_argument("--settle", type=float, default=0.4)

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except Exception as exc:
        emit(log({"cmd": args.cmd, "error": f"{type(exc).__name__}: {exc}"}))
        sys.exit(2)


if __name__ == "__main__":
    main()
