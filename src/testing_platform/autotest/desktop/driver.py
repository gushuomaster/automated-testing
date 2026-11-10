"""Windows desktop driver: UIA element list + screenshot observation, guarded input actions.

Runs inside the service subprocess (see service.py). Every input action first makes a
target-process window foreground and verifies the click point / keyboard focus belongs
to the target process; otherwise it raises Refused and sends nothing.
"""

from __future__ import annotations

import ctypes
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=SyntaxWarning)

from PIL import Image, ImageDraw, ImageFont, ImageGrab  # noqa: E402
from pywinauto import keyboard, mouse  # noqa: E402
from pywinauto.controls.uiawrapper import UIAWrapper  # noqa: E402
from pywinauto.uia_element_info import UIAElementInfo  # noqa: E402
import win32gui  # noqa: E402
import win32process  # noqa: E402

from .observation import (  # noqa: E402
    Element,
    Frame,
    clear_allowed,
    escape_text,
    inside,
    keep_element,
    scale_for,
)

VALUE_TYPES = {"Edit", "ComboBox", "Document", "Spinner", "Slider", "DataItem", "ListItem", "TreeItem"}
TOGGLE_TYPES = {"CheckBox", "Button", "MenuItem"}
SELECT_TYPES = {"ListItem", "TreeItem", "TabItem", "RadioButton", "DataItem"}
EXPAND_TYPES = {"TreeItem", "ComboBox", "MenuItem", "SplitButton"}
COLORS = [(230, 25, 75), (0, 130, 200), (60, 180, 75), (245, 130, 48), (145, 30, 180), (0, 128, 128)]


class Refused(Exception):
    """Input was not sent because it could land outside the target process."""


def owner_pid(hwnd: int) -> int:
    return win32process.GetWindowThreadProcessId(hwnd)[1] if hwnd else 0


def target_windows(pids: set[int]) -> list[int]:
    """Visible, non-empty top-level windows of the target processes in z-order (top first)."""
    handles: list[int] = []

    def collect(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or owner_pid(hwnd) not in pids:
            return
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if right - left > 4 and bottom - top > 4:
            handles.append(hwnd)

    win32gui.EnumWindows(collect, None)
    return handles


def _try(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


class Driver:
    def __init__(self, out_dir: str | Path, max_nodes: int = 400, max_depth: int = 30, settle: float = 0.6):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.settle = settle
        self.pids: set[int] = set()
        self.elements: dict[str, tuple[Element, UIAWrapper]] = {}
        self.frame = Frame(0, 0, 1.0)
        self.shot_seq = 0
        try:
            self.font = ImageFont.load_default(size=13)
        except TypeError:
            self.font = ImageFont.load_default()

    # ---- target -------------------------------------------------------------------------
    def set_target(self, pids: list[int]) -> dict:
        self.pids = {int(p) for p in pids}
        self.elements.clear()
        return {"pids": sorted(self.pids), "windows": len(target_windows(self.pids))}

    def _windows(self) -> list[int]:
        if not self.pids:
            raise Refused("no target process set")
        handles = target_windows(self.pids)
        if not handles:
            raise Refused(f"target processes {sorted(self.pids)} have no visible window")
        return handles

    def _foreground_ok(self) -> bool:
        return owner_pid(win32gui.GetForegroundWindow()) in self.pids

    def focus(self) -> dict:
        """Bring the top-most enabled target window (a modal dialog if any) to the foreground."""
        handles = self._windows()
        if self._foreground_ok():
            return {"foreground": win32gui.GetWindowText(win32gui.GetForegroundWindow())}
        enabled = [h for h in handles if win32gui.IsWindowEnabled(h)] or handles
        hwnd = enabled[0]
        user32 = ctypes.windll.user32
        for _ in range(3):
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
            fg = win32gui.GetForegroundWindow()
            cur = ctypes.windll.kernel32.GetCurrentThreadId()
            fg_thread = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
            attached = bool(fg_thread) and user32.AttachThreadInput(cur, fg_thread, True)
            try:
                win32gui.ShowWindow(hwnd, 5)  # SW_SHOW
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            finally:
                if attached:
                    user32.AttachThreadInput(cur, fg_thread, False)
            time.sleep(0.3)
            if self._foreground_ok():
                return {"foreground": win32gui.GetWindowText(win32gui.GetForegroundWindow())}
        raise Refused(f"cannot bring target to foreground; foreground pid is "
                      f"{owner_pid(win32gui.GetForegroundWindow())}")

    def _guard_point(self, x: int, y: int) -> None:
        hit = win32gui.WindowFromPoint((x, y))
        root = win32gui.GetAncestor(hit, 3) if hit else 0  # GA_ROOTOWNER
        if owner_pid(hit) not in self.pids and owner_pid(root) not in self.pids:
            raise Refused(f"point ({x},{y}) belongs to pid {owner_pid(hit)}, not the target")

    def _guard_keys(self) -> None:
        if not self._foreground_ok():
            raise Refused(f"foreground changed to pid {owner_pid(win32gui.GetForegroundWindow())}")

    # ---- observation --------------------------------------------------------------------
    def _describe(self, wrapper: UIAWrapper, hwnd: int, path: list[int]) -> Element | None:
        info = wrapper.element_info
        ctype = _try(lambda: info.control_type, "") or ""
        rect_obj = _try(lambda: info.rectangle)
        if rect_obj is None:
            return None
        rect = [rect_obj.left, rect_obj.top, rect_obj.right, rect_obj.bottom]
        name = _try(lambda: info.name, "") or ""
        raw = info.element
        value = None
        if ctype in VALUE_TYPES:
            value = _try(lambda: wrapper.iface_value.CurrentValue)
        if not keep_element(ctype, name, value, rect):
            return None
        el = Element(
            id="", hwnd=hwnd, path=path, control_type=ctype, name=name,
            auto_id=_try(lambda: info.automation_id, "") or "", value=value, rect=rect,
            enabled=bool(_try(lambda: info.enabled, True)),
            focused=bool(_try(lambda: raw.CurrentHasKeyboardFocus, False)),
            is_password=bool(_try(lambda: raw.CurrentIsPassword, False)),
        )
        if ctype in TOGGLE_TYPES:
            el.toggle = _try(lambda: wrapper.iface_toggle.CurrentToggleState)
        if ctype in SELECT_TYPES:
            el.selected = _try(lambda: bool(wrapper.iface_selection_item.CurrentIsSelected))
        if ctype in EXPAND_TYPES:
            el.expand = _try(lambda: wrapper.iface_expand_collapse.CurrentExpandCollapseState)
        if el.is_password:
            el.value = None
        return el

    def _walk(self, wrapper: UIAWrapper, hwnd: int, path: list[int], bounds: list[int],
              out: list[tuple[Element, UIAWrapper]], state: dict) -> None:
        if len(out) >= self.max_nodes:
            state["truncated"] = True
            return
        if len(path) > self.max_depth:
            return
        offscreen = bool(_try(lambda: wrapper.element_info.element.CurrentIsOffscreen, False))
        if offscreen and path:
            return
        el = self._describe(wrapper, hwnd, path) if path else None
        if el is not None and inside(el.rect, bounds):
            out.append((el, wrapper))
        kids = _try(wrapper.children, []) or []
        for i, kid in enumerate(kids):
            self._walk(kid, hwnd, path + [i], bounds, out, state)

    def observe(self, annotate: bool = True, focus: bool = True) -> dict:
        if focus:
            _try(self.focus)
        handles = self._windows()
        fg = win32gui.GetForegroundWindow()
        windows, collected, state = [], [], {"truncated": False}
        for hwnd in handles:
            rect = list(win32gui.GetWindowRect(hwnd))
            windows.append({
                "hwnd": hwnd, "title": win32gui.GetWindowText(hwnd), "rect": rect,
                "enabled": bool(win32gui.IsWindowEnabled(hwnd)), "foreground": hwnd == fg,
            })
            root = _try(lambda: UIAWrapper(UIAElementInfo(hwnd)))
            if root is not None:
                self._walk(root, hwnd, [], rect, collected, state)

        self.elements.clear()
        for i, (el, wrapper) in enumerate(collected, start=1):
            el.id = f"e{i}"
            self.elements[el.id] = (el, wrapper)

        left = min(w["rect"][0] for w in windows)
        top = min(w["rect"][1] for w in windows)
        right = max(w["rect"][2] for w in windows)
        bottom = max(w["rect"][3] for w in windows)
        img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).convert("RGB")
        scale = scale_for(img.width, img.height)
        if scale < 1.0:
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                             Image.LANCZOS)
        self.frame = Frame(left, top, scale)

        self.shot_seq += 1
        stamp = f"{self.shot_seq:04d}-{datetime.now().strftime('%H%M%S')}"
        raw_path = self.out_dir / f"obs-{stamp}.png"
        img.save(raw_path)
        annotated_path = raw_path
        if annotate:
            annotated_path = self.out_dir / f"obs-{stamp}-marked.png"
            self._annotate(img.copy(), [e for e, _ in collected]).save(annotated_path)
        return {
            "windows": windows,
            "elements": [e.to_dict() for e, _ in collected],
            "truncated": state["truncated"],
            "frame": {"left": left, "top": top, "scale": scale},
            "image_size": [img.width, img.height],
            "screenshot": str(raw_path),
            "annotated": str(annotated_path),
        }

    def _annotate(self, img: Image.Image, elements: list[Element]) -> Image.Image:
        draw = ImageDraw.Draw(img)
        for n, el in enumerate(e for e in elements if e.interactive):
            color = COLORS[n % len(COLORS)]
            x0, y0 = self.frame.to_image(el.rect[0], el.rect[1])
            x1, y1 = self.frame.to_image(el.rect[2], el.rect[3])
            draw.rectangle([x0, y0, x1, y1], outline=color, width=1)
            label = el.id[1:]
            tw = draw.textlength(label, font=self.font)
            draw.rectangle([x0, y0, x0 + tw + 3, y0 + 14], fill=color)
            draw.text((x0 + 2, y0), label, fill=(255, 255, 255), font=self.font)
        return img

    # ---- actions ------------------------------------------------------------------------
    def _element(self, element_id: str) -> tuple[Element, UIAWrapper]:
        if element_id not in self.elements:
            raise KeyError(f"unknown element id {element_id!r}; observe again and use a current id")
        return self.elements[element_id]

    def _center(self, element_id: str) -> tuple[int, int]:
        el, wrapper = self._element(element_id)
        r = _try(lambda: wrapper.element_info.rectangle)
        rect = [r.left, r.top, r.right, r.bottom] if r is not None and r.right > r.left else el.rect
        return (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2

    def _click_screen(self, x: int, y: int, button: str, double: bool) -> dict:
        if button not in ("left", "right"):
            raise ValueError("button must be left or right")
        self.focus()
        self._guard_point(x, y)
        if double:
            mouse.double_click(button=button, coords=(x, y))
        else:
            mouse.click(button=button, coords=(x, y))
        time.sleep(self.settle)
        return {"screen_xy": [x, y], "button": button, "double": double}

    def click_element(self, element_id: str, button: str = "left", double: bool = False) -> dict:
        x, y = self._center(element_id)
        return self._click_screen(x, y, button, double)

    def click_point(self, x: float, y: float, button: str = "left", double: bool = False) -> dict:
        sx, sy = self.frame.to_screen(x, y)
        return self._click_screen(sx, sy, button, double)

    def _focused(self) -> tuple[str, bool | None, int]:
        """(control type, read-only or None, pid) of the element with keyboard focus."""
        from pywinauto.uia_defines import IUIA

        raw = IUIA().iuia.GetFocusedElement()
        info = UIAElementInfo(raw)
        read_only = None
        try:
            from pywinauto.uia_defines import get_elem_interface

            read_only = bool(get_elem_interface(raw, "Value").CurrentIsReadOnly)
        except Exception:
            pass
        return info.control_type or "", read_only, int(_try(lambda: raw.CurrentProcessId, 0) or 0)

    def type_text(self, text: str, element_id: str | None = None, clear_first: bool = False) -> dict:
        if element_id:
            self.click_element(element_id)
        self.focus()
        self._guard_keys()
        if clear_first:
            # Ctrl+A, Delete on a list/tree would delete items, so only clear a real input box.
            ctype, read_only, pid = self._focused()
            if pid not in self.pids or not clear_allowed(ctype, read_only):
                raise Refused(f"焦点在 {ctype or '未知控件'}{'（只读）' if read_only else ''} 上，不是可编辑输入框；"
                              f"未执行清空和输入。请先让真正的输入框获得焦点（例如打开该对象的编辑界面）")
            keyboard.send_keys("^a{DELETE}", pause=0.03)
        self._guard_keys()
        keyboard.send_keys(escape_text(text), with_spaces=True, with_tabs=True, with_newlines=True,
                           pause=0.02, vk_packet=True)
        time.sleep(self.settle)
        return {"chars": len(text)}

    def press_keys(self, keys: str) -> dict:
        self.focus()
        self._guard_keys()
        keyboard.send_keys(keys, pause=0.05)
        time.sleep(self.settle)
        return {"keys": keys}

    def _point(self, element_id: str | None, x: float | None, y: float | None) -> tuple[int, int]:
        if element_id:
            return self._center(element_id)
        return self.frame.to_screen(x, y)

    def drag(self, from_element_id: str | None = None, from_x: float | None = None, from_y: float | None = None,
             to_element_id: str | None = None, to_x: float | None = None, to_y: float | None = None) -> dict:
        start = self._point(from_element_id, from_x, from_y)
        end = self._point(to_element_id, to_x, to_y)
        self.focus()
        self._guard_point(*start)
        self._guard_point(*end)
        mouse.press(button="left", coords=start)
        time.sleep(0.2)
        steps = 12  # move gradually so toolkits pass their drag threshold and track the hover target
        for i in range(1, steps + 1):
            mouse.move(coords=(round(start[0] + (end[0] - start[0]) * i / steps),
                               round(start[1] + (end[1] - start[1]) * i / steps)))
            time.sleep(0.04)
        time.sleep(0.3)
        mouse.release(button="left", coords=end)
        time.sleep(self.settle)
        return {"from": list(start), "to": list(end)}

    def scroll(self, x: float, y: float, amount: int) -> dict:
        sx, sy = self.frame.to_screen(x, y)
        self.focus()
        self._guard_point(sx, sy)
        mouse.scroll(coords=(sx, sy), wheel_dist=int(amount))
        time.sleep(self.settle)
        return {"screen_xy": [sx, sy], "amount": amount}

    def set_value(self, element_id: str, value: str) -> dict:
        _, wrapper = self._element(element_id)
        wrapper.iface_value.SetValue(value)
        time.sleep(self.settle)
        return {"ok": True}

    def invoke(self, element_id: str) -> dict:
        _, wrapper = self._element(element_id)
        errors = []
        for pattern in ("invoke", "select", "toggle", "expand"):
            try:
                getattr(wrapper, pattern)()
                time.sleep(self.settle)
                return {"pattern": pattern}
            except Exception as exc:  # noqa: PERF203
                errors.append(f"{pattern}: {type(exc).__name__}")
        raise RuntimeError("element supports none of invoke/select/toggle/expand (" + "; ".join(errors) + ")")

    def wait(self, seconds: float) -> dict:
        seconds = max(0.0, min(float(seconds), 10.0))
        time.sleep(seconds)
        return {"waited": seconds}
