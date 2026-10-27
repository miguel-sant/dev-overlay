"""Config, estado persistente e peças de UI compartilhadas entre o hub e os cards."""
import json
import re
import sys
import time
import zlib
from pathlib import Path

from gi.repository import Gdk, GLib, Gtk

from .theme import FAMILY_COLORS

try:
    import gi

    gi.require_version("GdkX11", "3.0")
    from gi.repository import GdkX11
except (ValueError, ImportError):
    GdkX11 = None

APP_ID = "dev.miguel.OverlayDev"
CONFIG_DIR = Path(GLib.get_user_config_dir()) / "overlay-dev"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_FILE = CONFIG_DIR / "state.json"
DEFAULT_CONFIG = {
    "roots": [str(Path.home() / "Documentos" / "Projetos SEMGE")],
    "editor": ["code"],
    # Faz `git fetch` sozinho no projeto ativo quando o último fetch for mais antigo que isso.
    # 0 = desligado: o overlay só fala com o servidor quando você clica em fetch/pull/push.
    "auto_fetch_minutes": 0,
}
SHADOW_MARGIN = 10


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save_json(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except OSError as err:
        print(f"overlay-dev: não foi possível salvar {path}: {err}", file=sys.stderr)


def load_config():
    saved = load_json(CONFIG_FILE, {})
    config = {**DEFAULT_CONFIG, **saved}
    if config != saved:
        save_json(CONFIG_FILE, config)
    if isinstance(config["editor"], str):
        config["editor"] = [config["editor"]]
    return config


class Store:
    """Estado persistente (posições, recentes, base de cada projeto…) salvo com debounce."""

    def __init__(self):
        self.data = load_json(STATE_FILE, {})
        self._source = 0

    def section(self, key):
        return self.data.setdefault(key, {})

    def save_soon(self):
        if self._source:
            GLib.source_remove(self._source)
        self._source = GLib.timeout_add(400, self._save)

    def _save(self):
        self._source = 0
        save_json(STATE_FILE, self.data)
        return False


# ---- helpers de UI ----------------------------------------------------


def add_classes(widget, *classes):
    ctx = widget.get_style_context()
    for cls in classes:
        if cls:
            ctx.add_class(cls)
    return widget


def label(text="", *classes, markup=None, xalign=0, ellipsize=None, max_chars=None):
    widget = add_classes(Gtk.Label(xalign=xalign), *classes)
    if markup is not None:
        widget.set_markup(markup)
    else:
        widget.set_text(text)
    if ellipsize is not None:
        widget.set_ellipsize(ellipsize)
    if max_chars:
        widget.set_max_width_chars(max_chars)
    return widget


def clear(container):
    for child in container.get_children():
        container.remove(child)


def initials(name):
    parts = [p for p in re.split(r"[-_ .]+", name) if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def family_color(name):
    # Projetos da mesma família (sismed-*, siad-*, sigav2…) ficam com a mesma cor.
    family = re.sub(r"v\d+$", "", re.split(r"[-_]", name)[0].lower())
    return zlib.crc32(family.encode()) % len(FAMILY_COLORS)


def branch_kind(branch):
    b = branch.lower()
    if b in ("develop", "dev", "development"):
        return "dev"
    if b in ("main", "master", "producao", "production", "prod"):
        return "prod"
    if b.startswith(("homolog", "staging", "release", "pre_homolog")):
        return "hml"
    if "/" in b or "task" in b or "tarefa" in b:
        return "feat"
    return "other"


def time_ago(timestamp, prefix=""):
    seconds = time.time() - timestamp
    if seconds < 60:
        return "agora"
    if seconds < 3600:
        return f"{prefix}{int(seconds // 60)} min"
    if seconds < 86400:
        return f"{prefix}{int(seconds // 3600)} h"
    return f"{prefix}{int(seconds // 86400)} d"


def plural(n, singular, plural_form=None):
    return f"{n} {singular if n == 1 else plural_form or singular + 's'}"


class ActionButton(Gtk.Button):
    """Botão de ação. Com `confirm`, o primeiro clique só arma ("Confirmar?") e o segundo executa."""

    def __init__(self, text, callback, confirm=False, primary=False, tooltip=None, sensitive=True):
        super().__init__(label=text)
        add_classes(self, "act", "primary" if primary else None)
        self.text = text
        self.callback = callback
        self.confirm = confirm
        self._armed_source = 0
        self.set_can_focus(False)
        self.set_valign(Gtk.Align.CENTER)
        self.set_sensitive(sensitive)
        if tooltip:
            self.set_tooltip_text(tooltip)
        self.connect("clicked", self.on_clicked)

    def on_clicked(self, *_):
        if self.confirm and not self._armed_source:
            self.set_label("Confirmar?")
            self.get_style_context().add_class("armed")
            self._armed_source = GLib.timeout_add(3000, self.disarm)
            return
        self.disarm()
        self.callback()

    def disarm(self):
        if self._armed_source:
            GLib.source_remove(self._armed_source)
            self._armed_source = 0
        self.set_label(self.text)
        self.get_style_context().remove_class("armed")
        return False


class FloatingWindow(Gtk.Window):
    """Janela sem borda, sempre por cima, que se arrasta pela alça e lembra a posição."""

    def __init__(self, app, key):
        super().__init__(title=f"Overlay Dev · {key}")
        self.app = app
        self.key = key
        self.geo = app.store.section("windows").setdefault(key, {})
        self._press = None

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_keep_above(True)
        Gtk.Widget.set_opacity(self, app.opacity)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)

        self.connect("configure-event", self.on_configure)
        self.connect("delete-event", lambda *_: self.hide() or True)
        app.add_window(self)

    def frame(self, child, *classes):
        """Envolve o conteúdo com a margem da sombra e as classes do container."""
        add_classes(child, *classes)
        for side in ("top", "bottom", "start", "end"):
            getattr(child, f"set_margin_{side}")(SHADOW_MARGIN)
        self.add(child)
        return child

    def make_draggable(self, eventbox):
        eventbox.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK
        )
        eventbox.connect("button-press-event", self._on_press)
        eventbox.connect("motion-notify-event", self._on_motion)
        eventbox.connect("button-release-event", lambda *_: setattr(self, "_press", None))

    def _on_press(self, _widget, event):
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            self._press = (event.x_root, event.y_root)
        return False

    def _on_motion(self, _widget, event):
        # Só começa a arrastar depois de mover alguns pixels, para cliques normais continuarem funcionando.
        if self._press and event.state & Gdk.ModifierType.BUTTON1_MASK:
            dx, dy = event.x_root - self._press[0], event.y_root - self._press[1]
            if dx * dx + dy * dy > 16:
                self._press = None
                self.begin_move_drag(1, int(event.x_root), int(event.y_root), event.time)
        return False

    def on_configure(self, *_):
        if self.get_visible():
            x, y = self.get_position()
            if (self.geo.get("x"), self.geo.get("y")) != (x, y):
                self.geo.update(x=x, y=y)
                self.app.store.save_soon()
        return False

    def place(self, default_x, default_y):
        """Volta para a posição salva, se ela ainda estiver em algum monitor; senão usa a padrão."""
        display = Gdk.Display.get_default()
        x, y = self.geo.get("x"), self.geo.get("y")
        if x is not None and y is not None:
            for i in range(display.get_n_monitors()):
                area = display.get_monitor(i).get_geometry()
                if area.x <= x + 60 < area.x + area.width and area.y <= y + 20 < area.y + area.height:
                    self.move(x, y)
                    return
        self.move(default_x, default_y)

    def reset_position(self):
        self.geo.pop("x", None)
        self.geo.pop("y", None)

    def present_focused(self, retry=False):
        self.realize()
        timestamp = 0
        gdk_window = self.get_window()
        if GdkX11 and isinstance(gdk_window, GdkX11.X11Window):
            # Evita que o "focus stealing prevention" deixe a janela sem foco.
            timestamp = GdkX11.x11_get_server_time(gdk_window)
        self.present_with_time(timestamp or Gtk.get_current_event_time())
        if not retry:
            # Na primeira vez que a janela é mapeada o GNOME às vezes ignora o pedido; insiste uma vez.
            GLib.timeout_add(120, self._retry_focus)

    def _retry_focus(self):
        if self.get_visible() and not self.is_active():
            self.present_focused(retry=True)
        return False


def pointer_workarea():
    display = Gdk.Display.get_default()
    _, px, py = display.get_default_seat().get_pointer().get_position()
    monitor = display.get_monitor_at_point(px, py) or display.get_primary_monitor()
    return monitor.get_workarea()
