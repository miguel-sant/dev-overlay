"""Card de projetos: busca, recentes e status git de cada pasta."""
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import gitops
from .card import Card
from .common import add_classes, branch_kind, clear, family_color, initials, label, time_ago
from .theme import ACCENT

RECENT_LIMIT = 5
VISIBLE_ROWS = 9
ROW_HEIGHT = 36


@dataclass
class Project:
    name: str
    path: str


def scan_projects(roots):
    projects = []
    for root in roots:
        try:
            entries = sorted(Path(root).expanduser().iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        projects += [Project(e.name, str(e)) for e in entries if e.is_dir() and not e.name.startswith(".")]
    return projects


def fuzzy_match(query, text, subsequence=True):
    """Pontua `text` contra `query`. Retorna (score, índices casados) ou None."""
    if not text:
        return None
    t = text.lower()
    for q in {query, query.replace(" ", "-")}:
        i = t.find(q)
        if i >= 0:
            score = 1000 - i * 10 - (len(t) - len(q))
            if i == 0:
                score += 500
            elif t[i - 1] in "-_./ ":
                score += 250
            return score, list(range(i, i + len(q)))
    if not subsequence:
        return None

    # Subsequência: "sadm" casa com "sismed-adm".
    indices, pos, prev, score = [], 0, -2, 0
    for ch in query.replace(" ", ""):
        pos = t.find(ch, pos)
        if pos < 0:
            return None
        if pos == prev + 1:
            score += 15
        if pos == 0 or t[pos - 1] in "-_./ ":
            score += 10
        indices.append(pos)
        prev, pos = pos, pos + 1
    return score - len(t), indices


def highlight(text, indices):
    marked = set(indices)
    out = []
    for i, ch in enumerate(text):
        esc = GLib.markup_escape_text(ch)
        out.append(f'<span foreground="{ACCENT}">{esc}</span>' if i in marked else esc)
    return "".join(out)


def status_labels(st):
    """Indicadores compactos (alterações, ↑ ↓) para uma linha de projeto ou para o hub."""
    if st is None:
        return []
    out = []
    if st.changes:
        out.append(label(f"●{st.changes}", "st-dirty"))
    if st.ahead:
        out.append(label(f"↑{st.ahead}", "st-ahead"))
    if st.behind:
        out.append(label(f"↓{st.behind}", "st-behind"))
    for widget, tip in zip(out, ("alterações não commitadas", "commits para enviar", "commits para baixar")):
        widget.set_tooltip_text(tip)
    return out


class ProjectRow(Gtk.ListBoxRow):
    def __init__(self, project, markup, section, status, when=None):
        super().__init__()
        self.project = project
        self.section = section
        color = family_color(project.name)
        add_classes(self, "proj", f"stripe-{color}")

        box = Gtk.Box(spacing=8)
        badge = label(initials(project.name), "badge", f"fam-{color}", xalign=0.5)
        badge.set_valign(Gtk.Align.CENTER)
        box.pack_start(badge, False, False, 0)
        name = label("", "name", markup=markup, ellipsize=Pango.EllipsizeMode.END)
        box.pack_start(name, True, True, 0)

        if when:
            box.pack_end(label(when, "dim"), False, False, 0)
        if status and status.branch:
            tag = label(status.branch, "tag", f"br-{branch_kind(status.branch)}", ellipsize=Pango.EllipsizeMode.MIDDLE, max_chars=18)
            tag.set_valign(Gtk.Align.CENTER)
            box.pack_end(tag, False, False, 0)
        for widget in reversed(status_labels(status)):
            box.pack_end(widget, False, False, 0)

        self.add(box)
        self.show_all()


class ProjectsCard(Card):
    WIDTH = 400

    def __init__(self, app):
        super().__init__(app, "projects", "▤", "Projetos")
        self.section_notes = {}
        self._select_source = 0

        self.count = label("", "pill")
        self.count.set_valign(Gtk.Align.CENTER)
        self.header_extra.pack_start(self.count, False, False, 0)

        self.entry = add_classes(Gtk.Entry(placeholder_text="Buscar projeto ou branch…"), "query")
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "system-search-symbolic")
        self.entry.connect("changed", lambda *_: self.refresh())
        self.body.pack_start(self.entry, False, False, 0)

        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroller.set_min_content_height(VISIBLE_ROWS * ROW_HEIGHT)
        self.scroller.set_max_content_height(VISIBLE_ROWS * ROW_HEIGHT)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.set_header_func(self.on_list_header)
        self.listbox.connect("row-activated", lambda _lb, row: self.launch(row.project, "editor"))
        self.listbox.connect("row-selected", self.on_row_selected)
        self.scroller.add(self.listbox)
        self.body.pack_start(self.scroller, True, True, 0)

        self.empty = label("Nenhum projeto encontrado", "empty", xalign=0.5)
        self.empty.set_no_show_all(True)
        self.body.pack_start(self.empty, False, False, 0)

        self.hint = label("", "dim", ellipsize=Pango.EllipsizeMode.END)
        self.body.pack_start(self.hint, False, False, 0)
        self._toast_source = 0
        self._clear_toast()

        self.connect("key-press-event", self.on_key)
        self.body.show_all()

    # ---- dados --------------------------------------------------------

    def refresh(self, keep_path=None):
        if keep_path is None:
            selected = self.listbox.get_selected_row()
            keep_path = selected.project.path if selected else None
        query = self.entry.get_text().strip().lower()
        recent = self.app.store.section("recent")
        statuses = self.app.statuses

        if query:
            matches = []
            for project in self.app.projects:
                st = statuses.get(project.path)
                by_name = fuzzy_match(query, project.name)
                by_branch = fuzzy_match(query, st.branch if st else None, subsequence=False)
                if by_name and (not by_branch or by_name[0] >= by_branch[0] - 300):
                    matches.append((by_name[0], project, by_name[1]))
                elif by_branch:
                    matches.append((by_branch[0] - 300, project, []))
            matches.sort(key=lambda m: (-m[0], -recent.get(m[1].path, 0), m[1].name.lower()))
            items = [(p, idx, "results") for _s, p, idx in matches]
            self.section_notes = {"results": f"{len(items)} encontrado{'s' if len(items) != 1 else ''}"}
            keep_path = None  # numa busca, o melhor resultado fica selecionado
        else:
            recents = sorted((p for p in self.app.projects if p.path in recent), key=lambda p: -recent[p.path])
            recents = recents[:RECENT_LIMIT]
            others = [p for p in self.app.projects if p not in recents]
            items = [(p, [], "recent") for p in recents] + [(p, [], "all") for p in others]
            self.section_notes = {"recent": "abertos por último", "all": f"{len(others)} pastas"}

        clear(self.listbox)
        keep_row = None
        for project, indices, section in items:
            when = time_ago(recent[project.path]) if section == "recent" else None
            row = ProjectRow(project, highlight(project.name, indices), section, statuses.get(project.path), when)
            self.listbox.add(row)
            if project.path == keep_path:
                keep_row = row

        self.count.set_text(str(len(self.app.projects)))
        self.scroller.set_visible(bool(items))
        self.empty.set_visible(not items)
        self._selecting_programmatically = True
        self.select(keep_row or self.listbox.get_row_at_index(0))
        self._selecting_programmatically = False

    def on_list_header(self, row, before):
        if before is not None and before.section == row.section:
            row.set_header(None)
            return
        title = {"recent": "RECENTES", "all": "PROJETOS", "results": "RESULTADOS"}[row.section]
        box = add_classes(Gtk.Box(spacing=8), "section")
        box.pack_start(label(title, "section-title"), False, False, 0)
        box.pack_start(label(self.section_notes.get(row.section, ""), "section-note"), False, False, 0)
        box.show_all()
        row.set_header(box)

    # ---- seleção e teclado ---------------------------------------------

    def select(self, row):
        if row is None:
            return
        self.listbox.select_row(row)
        GLib.idle_add(self.scroll_to, row)

    def scroll_to(self, row):
        alloc = row.get_allocation()
        header = row.get_header()
        top = alloc.y - (header.get_allocated_height() if header else 0)
        self.scroller.get_vadjustment().clamp_page(top, alloc.y + alloc.height + 8)
        return False

    def on_row_selected(self, _listbox, row):
        # O card de git acompanha a seleção quando você navega pela lista (não quando ela é reconstruída).
        if row is None or getattr(self, "_selecting_programmatically", False):
            return
        if self._select_source:
            GLib.source_remove(self._select_source)
        self._select_source = GLib.timeout_add(250, self._emit_selection, row.project.path)

    def _emit_selection(self, path):
        self._select_source = 0
        self.app.set_active_project(path)
        return False

    def move_selection(self, delta):
        rows = self.listbox.get_children()
        if rows:
            current = self.listbox.get_selected_row()
            index = current.get_index() if current else -1
            self.select(rows[(index + delta) % len(rows)])

    def on_key(self, _widget, event):
        key = event.keyval
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        alt = event.state & Gdk.ModifierType.MOD1_MASK
        if key == Gdk.KEY_Escape:
            if self.entry.get_text():
                self.entry.set_text("")
            else:
                self.app.hide_all()
        elif key in (Gdk.KEY_Down, Gdk.KEY_Tab) or (ctrl and key in (Gdk.KEY_n, Gdk.KEY_j)):
            self.move_selection(1)
        elif key in (Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab) or (ctrl and key in (Gdk.KEY_p, Gdk.KEY_k)):
            self.move_selection(-1)
        elif key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            row = self.listbox.get_selected_row()
            if row:
                self.launch(row.project, "terminal" if ctrl else "files" if alt else "editor")
        else:
            return False
        return True

    def focus_search(self):
        self.present_focused()
        self.entry.grab_focus()

    # ---- abrir --------------------------------------------------------

    def launch(self, project, mode):
        if mode == "terminal":
            if shutil.which("gnome-terminal"):
                argv = ["gnome-terminal", f"--working-directory={project.path}"]
            elif shutil.which("ptyxis"):
                argv = ["ptyxis", "--new-window", "--working-directory", project.path]
            else:
                argv = ["x-terminal-emulator"]
            where = "no terminal"
        elif mode == "files":
            argv, where = ["xdg-open", project.path], "na pasta"
        else:
            argv, where = [*self.app.config["editor"], project.path], "no VS Code"

        if not spawn(argv, project.path):
            self.toast(f"Falha ao executar {argv[0]}", ok=False)
            return
        self.app.store.section("recent")[project.path] = time.time()
        self.app.store.save_soon()
        self.app.set_active_project(project.path)
        self.toast(f"Abrindo {project.name} {where}")
        if not self.entry.get_text():
            self.refresh(keep_path=project.path)

    def toast(self, message, ok=True):
        icon = '<span foreground="#5fd068">✓</span>' if ok else '<span foreground="#ff6b6b">✕</span>'
        self.hint.set_markup(f"{icon}  {GLib.markup_escape_text(message)}")
        if self._toast_source:
            GLib.source_remove(self._toast_source)
        self._toast_source = GLib.timeout_add(2500, self._clear_toast)

    def _clear_toast(self):
        self._toast_source = 0
        self.hint.set_markup("<b>↵</b> VS Code    <b>Ctrl+↵</b> terminal    <b>Alt+↵</b> pasta    <b>Esc</b> ocultar")
        return False


def spawn(argv, cwd):
    launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
    launcher.set_cwd(cwd)
    # Se o overlay foi iniciado de dentro de um terminal do VS Code, não herda o vínculo dele.
    for var in ("VSCODE_IPC_HOOK_CLI", "VSCODE_GIT_IPC_HANDLE", "ELECTRON_RUN_AS_NODE"):
        launcher.unsetenv(var)
    try:
        launcher.spawnv(argv)
        return True
    except GLib.Error:
        return False


def load_statuses(paths, callback):
    """Lê o status git de várias pastas em paralelo e chama `callback(dict)` uma vez no fim."""
    results, pending = {}, len(paths)
    if not pending:
        callback(results)
        return

    def done(path, st):
        nonlocal pending
        results[path] = None if isinstance(st, Exception) else st
        pending -= 1
        if pending == 0:
            callback(results)

    for path in paths:
        gitops.submit(lambda st, p=path: done(p, st), gitops.read_status, path)
