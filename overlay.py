#!/usr/bin/env python3
"""Overlay Dev — overlay de projetos e git no estilo do Shugo.GG.

Uso:
    overlay.py            mostra/foca/esconde o overlay (inicia o app se preciso)
    overlay.py --hidden   inicia em segundo plano, sem mostrar nada
"""
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from overlaydev.common import APP_ID, SHADOW_MARGIN, Store, load_config, pointer_workarea  # noqa: E402
from overlaydev.git_card import GitCard  # noqa: E402
from overlaydev.hub import HUB_WIDTH, Hub  # noqa: E402
from overlaydev.projects_card import ProjectsCard, load_statuses, scan_projects  # noqa: E402
from overlaydev.theme import CSS  # noqa: E402
from overlaydev.vscode_watch import VSCodeWatcher  # noqa: E402

CARDS = [("projects", "▤  Projetos", ProjectsCard), ("git", "⎇  Git", GitCard)]
GAP = 16


class OverlayApp(Gtk.Application):
    def __init__(self, start_hidden):
        super().__init__(application_id=APP_ID)
        self.start_hidden = start_hidden
        self.config = load_config()
        self.store = Store()
        self.prefs = self.store.section("prefs")
        self.opacity = self.prefs.get("opacity", 1.0)
        self.projects = []
        self.statuses = {}
        self.active_path = None
        self.hub = None
        self.cards = {}
        self.shown = False
        self.lost_focus_at = 0.0

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self):
        if self.hub is None:
            self.build()
            if self.start_hidden:
                return
        self.toggle()

    def build(self):
        self.projects = scan_projects(self.config["roots"])
        self.hub = Hub(self, [(key, text) for key, text, _cls in CARDS])
        self.cards = {key: cls(self) for key, _text, cls in CARDS}
        for window in (self.hub, *self.cards.values()):
            window.connect("focus-out-event", self._on_focus_out)
        for key in self.cards:
            self.hub.sync_chip(key, self.card_enabled(key))
        self.watcher = VSCodeWatcher(self.set_active_project, lambda: self.projects)

        recent = self.store.section("recent")
        active = self.prefs.get("active") or max(recent, key=recent.get, default=None)
        if active and any(p.path == active for p in self.projects):
            self.set_active_project(active)
        else:
            self.hub.update(None, None)
        self.cards["projects"].refresh()
        self.refresh_statuses()
        GLib.timeout_add_seconds(60, self._periodic)

    # ---- projeto ativo e status ---------------------------------------

    def set_active_project(self, path):
        if path == self.active_path:
            return
        self.active_path = path
        self.prefs["active"] = path
        self.store.save_soon()
        self.cards["git"].set_project(path)
        self.hub.update(path, self.statuses.get(path))

    def refresh_statuses(self, paths=None):
        load_statuses(paths or [p.path for p in self.projects], self._on_statuses)

    def _on_statuses(self, results):
        self.statuses.update(results)
        self.cards["projects"].refresh()
        self.hub.update(self.active_path, self.statuses.get(self.active_path))

    def rescan(self):
        projects = scan_projects(self.config["roots"])
        if projects != self.projects:
            self.projects = projects
            self.cards["projects"].refresh()

    def _periodic(self):
        if self.shown:
            self.rescan()
            self.refresh_statuses()
        return True

    # ---- visibilidade -------------------------------------------------

    def card_enabled(self, key):
        return self.store.section("cards").get(key, True)

    def set_card_visible(self, key, visible):
        self.store.section("cards")[key] = visible
        self.store.save_soon()
        self.hub.sync_chip(key, visible)
        card = self.cards[key]
        if visible and self.shown:
            self._place_card(key)
            card.show()
            card.on_shown()
        else:
            card.hide()

    def _place_card(self, key):
        area = pointer_workarea()
        right = area.x + area.width - GAP
        projects_w = ProjectsCard.WIDTH + 2 * SHADOW_MARGIN
        top = area.y + GAP + 62
        if key == "projects":
            self.cards[key].place(right - projects_w, top)
        else:
            self.cards[key].place(right - projects_w - GitCard.WIDTH - 2 * SHADOW_MARGIN - 4, top)

    def show_all(self):
        self.shown = True
        self.rescan()
        self.refresh_statuses()
        area = pointer_workarea()
        self.hub.place(area.x + area.width - GAP - HUB_WIDTH - 2 * SHADOW_MARGIN, area.y + GAP)
        self.hub.show()
        for key, card in self.cards.items():
            if self.card_enabled(key):
                self._place_card(key)
                card.show()
                card.on_shown()
        self.focus()

    def hide_all(self):
        self.shown = False
        self.hub.hide()
        for card in self.cards.values():
            card.hide()

    def focus(self):
        projects = self.cards["projects"]
        if projects.get_visible():
            projects.focus_search()
        else:
            self.hub.present_focused()

    def toggle(self):
        if not self.shown:
            self.show_all()
            return
        windows = (self.hub, *self.cards.values())
        # O próprio atalho pode tirar o foco por um instante; nesse caso conta como "estava focado".
        if any(w.is_active() for w in windows) or time.monotonic() - self.lost_focus_at < 0.3:
            self.hide_all()
        else:
            self.focus()

    def _on_focus_out(self, *_):
        self.lost_focus_at = time.monotonic()
        return False

    def set_opacity(self, value):
        self.opacity = value
        self.prefs["opacity"] = value
        self.store.save_soon()
        for window in (self.hub, *self.cards.values()):
            Gtk.Widget.set_opacity(window, value)


def main():
    start_hidden = "--hidden" in sys.argv
    argv = [a for a in sys.argv if a != "--hidden"]
    return OverlayApp(start_hidden).run(argv)


if __name__ == "__main__":
    sys.exit(main())
