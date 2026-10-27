"""Base dos cards: cabeçalho arrastável com ícone, título, extras e botão de fechar."""
from gi.repository import Gtk, Pango

from .common import FloatingWindow, add_classes, label


class Card(FloatingWindow):
    WIDTH = 380

    def __init__(self, app, key, icon, title):
        super().__init__(app, key)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_size_request(self.WIDTH, -1)
        self.frame(root, "card")

        handle = Gtk.EventBox()
        self.make_draggable(handle)
        header = Gtk.Box(spacing=8)
        header.pack_start(label(icon, "card-icon"), False, False, 0)
        self.title = label(title, "card-title", ellipsize=Pango.EllipsizeMode.END)
        header.pack_start(self.title, True, True, 0)

        close = add_classes(Gtk.Button(label="✕"), "xbtn")
        close.set_can_focus(False)
        close.set_valign(Gtk.Align.CENTER)
        close.set_tooltip_text("Ocultar este card (reative passando o mouse na barra)")
        close.connect("clicked", lambda *_: app.set_card_visible(key, False))
        header.pack_end(close, False, False, 0)
        self.header_extra = Gtk.Box(spacing=6)
        header.pack_end(self.header_extra, False, False, 0)
        handle.add(header)
        root.pack_start(handle, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.pack_start(self.body, True, True, 0)
        root.show_all()

    def on_shown(self):
        """Chamado quando o card aparece (para atualizar dados)."""
