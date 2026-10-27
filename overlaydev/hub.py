"""Barra principal (a "linha" do Shugo): projeto ativo + status; ao passar o mouse, liga/desliga os cards."""
from pathlib import Path

from gi.repository import Gdk, GLib, Gtk, Pango

from .common import FloatingWindow, add_classes, branch_kind, clear, label
from .projects_card import status_labels

HUB_WIDTH = 280
OPACITY_STEPS = (1.0, 0.88, 0.75)


class Hub(FloatingWindow):
    def __init__(self, app, cards):
        super().__init__(app, "hub")
        self._hide_source = 0
        self._syncing = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.set_size_request(HUB_WIDTH, -1)
        self.frame(root, "hub")

        handle = Gtk.EventBox()
        self.make_draggable(handle)
        handle.set_tooltip_text("Arraste para mover · passe o mouse para ver os cards")
        line = Gtk.Box(spacing=8)
        logo = label("</>", "logo", xalign=0.5)
        logo.set_valign(Gtk.Align.CENTER)
        line.pack_start(logo, False, False, 0)
        self.name = label("", "hub-name", ellipsize=Pango.EllipsizeMode.END)
        line.pack_start(self.name, False, True, 0)
        self.status_box = Gtk.Box(spacing=6)
        line.pack_start(self.status_box, False, False, 0)
        self.branch_box = Gtk.Box()
        line.pack_end(self.branch_box, False, False, 0)
        handle.add(line)
        root.pack_start(handle, False, False, 0)

        # Opções que aparecem ao passar o mouse.
        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.revealer.set_transition_duration(120)
        chips = add_classes(Gtk.Box(spacing=6), "chips")
        self.chips = {}
        for key, text in cards:
            chip = add_classes(Gtk.ToggleButton(label=text), "chip")
            chip.set_can_focus(False)
            chip.connect("toggled", self._on_chip, key)
            chips.pack_start(chip, False, False, 0)
            self.chips[key] = chip

        hide = add_classes(Gtk.Button(label="✕"), "xbtn")
        hide.set_tooltip_text("Ocultar tudo (o atalho traz de volta)")
        hide.connect("clicked", lambda *_: app.hide_all())
        self.opacity_btn = add_classes(Gtk.Button(label="◐"), "xbtn")
        self.opacity_btn.connect("clicked", self._cycle_opacity)
        self._update_opacity_tooltip()
        for btn in (hide, self.opacity_btn):
            btn.set_can_focus(False)
            chips.pack_end(btn, False, False, 0)
        self.revealer.add(chips)
        root.pack_start(self.revealer, False, False, 0)

        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("enter-notify-event", self._on_enter)
        self.connect("leave-notify-event", self._on_leave)
        root.show_all()

    # ---- hover --------------------------------------------------------

    def _on_enter(self, *_):
        if self._hide_source:
            GLib.source_remove(self._hide_source)
            self._hide_source = 0
        self.revealer.set_reveal_child(True)
        return False

    def _on_leave(self, _widget, event):
        if event.detail != Gdk.NotifyType.INFERIOR and not self._hide_source:
            self._hide_source = GLib.timeout_add(700, self._collapse)
        return False

    def _collapse(self):
        self._hide_source = 0
        self.revealer.set_reveal_child(False)
        GLib.timeout_add(150, self._shrink)
        return False

    def _shrink(self):
        self.resize(1, 1)
        return False

    # ---- cards e opacidade ---------------------------------------------

    def _on_chip(self, chip, key):
        if not self._syncing:
            self.app.set_card_visible(key, chip.get_active())

    def sync_chip(self, key, active):
        self._syncing = True
        self.chips[key].set_active(active)
        self._syncing = False

    def _cycle_opacity(self, *_):
        current = self.app.opacity
        steps = list(OPACITY_STEPS)
        nxt = steps[(steps.index(current) + 1) % len(steps)] if current in steps else steps[0]
        self.app.set_opacity(nxt)
        self._update_opacity_tooltip()

    def _update_opacity_tooltip(self):
        self.opacity_btn.set_tooltip_text(f"Opacidade: {round(self.app.opacity * 100)}% (clique para alternar)")

    # ---- conteúdo -----------------------------------------------------

    def update(self, path, status):
        clear(self.status_box)
        clear(self.branch_box)
        if not path:
            self.name.set_text("Overlay Dev")
            return
        self.name.set_text(Path(path).name)
        for widget in status_labels(status):
            self.status_box.pack_start(widget, False, False, 0)
        if status and status.branch:
            tag = label(status.branch, "tag", f"br-{branch_kind(status.branch)}",
                        ellipsize=Pango.EllipsizeMode.MIDDLE, max_chars=16)
            tag.set_valign(Gtk.Align.CENTER)
            self.branch_box.pack_start(tag, False, False, 0)
        self.status_box.show_all()
        self.branch_box.show_all()
