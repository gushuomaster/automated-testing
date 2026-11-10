"""Pure helpers shared by the desktop driver and the agent (no Windows imports)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Control types the agent can usually act on; these get a box + id label on the screenshot.
INTERACTIVE_TYPES = frozenset({
    "Button", "SplitButton", "Edit", "ComboBox", "CheckBox", "RadioButton", "MenuItem",
    "ListItem", "TreeItem", "TabItem", "Hyperlink", "Slider", "Spinner", "DataItem",
    "HeaderItem", "Document",
})
# Non-interactive types kept only when they carry a name or value (labels, titles, status).
TEXT_TYPES = frozenset({
    "Text", "Header", "StatusBar", "Group", "Window", "Pane", "Table", "List", "Tree",
    "Menu", "MenuBar", "ToolBar", "Tab", "TitleBar", "Image", "ProgressBar", "Custom",
})

MAX_IMAGE_EDGE = 1568
PYWINAUTO_SPECIAL = "+^%~(){}[]"


@dataclass
class Element:
    id: str
    hwnd: int
    path: list[int]
    control_type: str
    name: str = ""
    auto_id: str = ""
    value: str | None = None
    rect: list[int] = field(default_factory=lambda: [0, 0, 0, 0])  # screen coords l,t,r,b
    enabled: bool = True
    focused: bool = False
    toggle: int | None = None
    selected: bool | None = None
    expand: int | None = None
    is_password: bool = False

    @property
    def interactive(self) -> bool:
        return self.control_type in INTERACTIVE_TYPES

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Element":
        return cls(**data)


@dataclass
class Frame:
    """Mapping between screen coordinates and the (possibly downscaled) image sent to the model."""

    left: int
    top: int
    scale: float  # image_px = (screen_px - origin) * scale

    def to_image(self, x: int, y: int) -> tuple[int, int]:
        return round((x - self.left) * self.scale), round((y - self.top) * self.scale)

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        return round(self.left + x / self.scale), round(self.top + y / self.scale)


MAX_IMAGE_PIXELS = 1_150_000


def scale_for(width: int, height: int, max_edge: int = MAX_IMAGE_EDGE,
              max_pixels: int = MAX_IMAGE_PIXELS) -> float:
    """Downscale factor so the image fits the model's preferred size (never upscales)."""
    if width <= 0 or height <= 0:
        return 1.0
    scale = min(1.0, max_edge / max(width, height), (max_pixels / (width * height)) ** 0.5)
    return scale


def keep_element(control_type: str, name: str, value: str | None, rect: list[int]) -> bool:
    left, top, right, bottom = rect
    if right - left <= 1 or bottom - top <= 1:
        return False
    if control_type in INTERACTIVE_TYPES:
        return True
    return control_type in TEXT_TYPES and bool((name or "").strip() or (value or "").strip())


def inside(rect: list[int], bounds: list[int]) -> bool:
    """True when the element's center lies within bounds (filters off-screen/scrolled-out nodes)."""
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    return bounds[0] <= cx <= bounds[2] and bounds[1] <= cy <= bounds[3]


def _clip(text: str | None, limit: int = 80) -> str:
    text = (text or "").replace("\r", " ").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_element(el: Element, frame: Frame) -> str:
    cx, cy = frame.to_image((el.rect[0] + el.rect[2]) // 2, (el.rect[1] + el.rect[3]) // 2)
    parts = [f"[{el.id}] {el.control_type}"]
    if el.name:
        parts.append(f'"{_clip(el.name)}"')
    if el.value not in (None, "") and not el.is_password:
        parts.append(f"value={_clip(el.value)!r}")
    if el.is_password:
        parts.append("(password field)")
    flags = []
    if not el.enabled:
        flags.append("disabled")
    if el.focused:
        flags.append("focused")
    if el.toggle is not None:
        flags.append({0: "unchecked", 1: "checked", 2: "indeterminate"}.get(el.toggle, f"toggle={el.toggle}"))
    if el.selected:
        flags.append("selected")
    if el.expand is not None:
        flags.append({0: "collapsed", 1: "expanded", 2: "partially-expanded", 3: "leaf"}.get(el.expand, ""))
    flags = [f for f in flags if f]
    if flags:
        parts.append("(" + ", ".join(flags) + ")")
    parts.append(f"@({cx},{cy})")
    return " ".join(parts)


def format_observation(obs: dict) -> str:
    """Render an observation dict (as returned by the service) into compact text for the model."""
    frame = Frame(**obs["frame"])
    lines = ["窗口:"]
    for win in obs["windows"]:
        mark = " [前台]" if win.get("foreground") else ""
        modal = " [不可用/被模态框阻挡]" if not win.get("enabled", True) else ""
        lines.append(f'- "{_clip(win["title"])}"{mark}{modal}')
    lines.append(f"控件（共 {len(obs['elements'])} 个，坐标为截图像素）:")
    lines.extend(format_element(Element.from_dict(e), frame) for e in obs["elements"])
    if obs.get("truncated"):
        lines.append("（控件过多，列表已截断；可用截图坐标操作未列出的部分）")
    return "\n".join(lines)


# Focus targets where Ctrl+A, Delete selects and deletes items instead of text.
NON_TEXT_FOCUS = frozenset({
    "List", "ListItem", "Tree", "TreeItem", "Table", "DataGrid", "DataItem", "Header", "HeaderItem",
    "Button", "SplitButton", "CheckBox", "RadioButton", "MenuItem", "Menu", "MenuBar", "Tab", "TabItem",
    "ToolBar", "Hyperlink", "Image", "Text", "Window", "TitleBar", "ScrollBar", "Slider", "StatusBar",
})


def clear_allowed(control_type: str, read_only: bool | None) -> bool:
    """Whether clearing the focused control with Ctrl+A, Delete is safe.

    Unknown or generic types (Pane, Custom) are allowed so apps with incomplete UIA still work.
    """
    if read_only:
        return False
    return control_type not in NON_TEXT_FOCUS


def escape_text(text: str) -> str:
    """Escape literal text for pywinauto.keyboard.send_keys."""
    out = []
    for ch in text:
        if ch in PYWINAUTO_SPECIAL:
            out.append("{" + ch + "}")
        elif ch == "\n":
            out.append("{ENTER}")
        elif ch == "\t":
            out.append("{TAB}")
        else:
            out.append(ch)
    return "".join(out)
