"""Card de git: estado da branch atual, comparação com o remoto e com a base, e o que fazer a seguir."""
import math
import time
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import gitops
from .card import Card
from .common import ActionButton, add_classes, branch_kind, clear, label, plural, time_ago
from .projects_card import spawn
from .theme import AMBER, BAR, BLUE, DIM, GREEN, RED

BRANCHES_COLLAPSED = 5
STALE_FETCH = 30 * 60  # depois disso, avisa que o fetch está velho antes de mesclar


class SplitBar(Gtk.DrawingArea):
    """Barra estilo Shugo: ↑ (commits seus) em laranja da esquerda, ↓ (commits deles) em azul da direita."""

    def __init__(self, ahead, behind, unknown=False):
        super().__init__()
        self.ahead, self.behind, self.unknown = ahead, behind, unknown
        self.set_size_request(-1, 6)
        self.connect("draw", self.on_draw)

    @staticmethod
    def _rounded(cr, x, y, w, h):
        r = min(h / 2, w / 2)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, math.pi / 2)
        cr.arc(x + r, y + r, r, math.pi / 2, 3 * math.pi / 2)
        cr.close_path()

    @staticmethod
    def _rgb(hex_color):
        return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def on_draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        cr.set_source_rgba(1, 1, 1, 0.08)
        self._rounded(cr, 0, 0, w, h)
        cr.fill()
        if self.unknown:
            return False
        total = self.ahead + self.behind
        if total == 0:
            cr.set_source_rgba(*self._rgb(GREEN), 0.6)
            self._rounded(cr, 0, 0, w, h)
            cr.fill()
            return False
        scale = max(total, 20)
        if self.ahead:
            cr.set_source_rgb(*self._rgb(BAR))
            self._rounded(cr, 0, 0, max(h, w * self.ahead / scale), h)
            cr.fill()
        if self.behind:
            bw = max(h, w * self.behind / scale)
            cr.set_source_rgb(*self._rgb(BLUE))
            self._rounded(cr, w - bw, 0, bw, h)
            cr.fill()
        return False


def counts_markup(ahead, behind):
    if not ahead and not behind:
        return f'<span foreground="{GREEN}"><b>em dia ✓</b></span>'
    parts = []
    if ahead:
        parts.append(f'<span foreground="{BAR}">↑<b>{ahead}</b></span>')
    if behind:
        parts.append(f'<span foreground="{BLUE}">↓<b>{behind}</b></span>')
    return "  ".join(parts)


class GitCard(Card):
    WIDTH = 410

    def __init__(self, app):
        super().__init__(app, "git", "⎇", "Git")
        self.path = None
        self.snap = None
        self.busy = False
        self.show_all_branches = False
        self._token = 0
        self._toast_source = 0

        self.spinner = Gtk.Spinner()
        self.spinner.set_no_show_all(True)
        self.header_extra.pack_start(self.spinner, False, False, 0)
        self.base_pill = self._pill_button("Trocar a branch base usada na comparação", self.cycle_base)
        self.fetch_pill = self._pill_button("", lambda *_: self.fetch())
        for pill in (self.base_pill, self.fetch_pill):
            pill.set_no_show_all(True)
            self.header_extra.pack_start(pill, False, False, 0)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.body.pack_start(self.content, False, False, 0)
        self.toast_label = label("", "toast", ellipsize=Pango.EllipsizeMode.END)
        self.toast_label.set_no_show_all(True)
        self.body.pack_start(self.toast_label, False, False, 0)
        self.body.show_all()

        GLib.timeout_add_seconds(20, self._tick)
        self.render()

    def _pill_button(self, tooltip, callback):
        btn = add_classes(Gtk.Button(), "pill")
        btn.add(Gtk.Label())
        btn.get_child().show()  # o botão usa no_show_all, então o filho precisa ser mostrado à mão
        btn.set_can_focus(False)
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_tooltip_text(tooltip)
        btn.connect("clicked", callback)
        return btn

    # ---- dados --------------------------------------------------------

    def set_project(self, path):
        if path == self.path:
            return
        self.path = path
        self.snap = None
        self.show_all_branches = False
        self.reload()

    def reload(self):
        if not self.path:
            self.render()
            return
        self._token += 1
        token, path = self._token, self.path
        base_pref = self.app.store.section("bases").get(path)
        gitops.submit(lambda snap: self._on_snapshot(token, snap), gitops.snapshot, path, base_pref)

    def _on_snapshot(self, token, snap):
        if token != self._token:
            return  # chegou atrasado: o projeto ativo já mudou
        self.snap = None if isinstance(snap, Exception) else snap
        self.render()
        minutes = self.app.config.get("auto_fetch_minutes", 0)
        if snap and minutes and not self.busy and time.time() - (snap.last_fetch or 0) > minutes * 60:
            self.fetch(quiet=True)

    def on_shown(self):
        self.reload()

    def _tick(self):
        if self.get_visible() and not self.busy and self.path:
            self.reload()
        return True

    # ---- render -------------------------------------------------------

    def render(self):
        clear(self.content)
        if not self.path:
            self.title.set_text("Git")
            self.base_pill.hide()
            self.fetch_pill.hide()
            self.content.pack_start(
                label("Foque uma janela do VS Code ou selecione um projeto", "empty", xalign=0.5), False, False, 0
            )
            self.content.show_all()
            return

        self.title.set_text(Path(self.path).name)
        snap = self.snap
        if snap is None:
            self.base_pill.hide()
            self.fetch_pill.hide()
            self.content.pack_start(label("Lendo repositório…", "empty", xalign=0.5), False, False, 0)
            self.content.show_all()
            return

        self._update_pills(snap)
        self.content.pack_start(self._hero(snap), False, False, 0)
        self.content.pack_start(self._stat_pills(snap.status), False, False, 0)
        self.content.pack_start(self._compare_panel(snap), False, False, 0)
        for alert in self._alerts(snap):
            self.content.pack_start(alert, False, False, 0)
        if snap.branches:
            self.content.pack_start(self._branches(snap), False, False, 0)
        self.content.show_all()
        self.content.set_sensitive(not self.busy)

    def _update_pills(self, snap):
        if snap.base:
            self.base_pill.get_child().set_markup(f'<span foreground="{DIM}">base</span>  <b>{snap.base}</b>')
            self.base_pill.set_sensitive(len(snap.bases) > 1)
            self.base_pill.show()
        else:
            self.base_pill.hide()
        when = time_ago(snap.last_fetch, "há ") if snap.last_fetch else "nunca"
        self.fetch_pill.get_child().set_markup(f"⟳  <b>{when}</b>")
        self.fetch_pill.set_tooltip_text(
            f"Último fetch: {when}. Clique para buscar novidades do GitLab (só leitura, nada é enviado)."
        )
        self.fetch_pill.show()

    def _hero(self, snap):
        st = snap.status
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        top = Gtk.Box(spacing=8)
        name = st.branch or "HEAD destacado"
        top.pack_start(label(name, "big", ellipsize=Pango.EllipsizeMode.MIDDLE), False, True, 0)
        if st.branch:
            kind = branch_kind(st.branch)
            tag = label({"dev": "desenvolvimento", "prod": "produção", "hml": "homologação", "feat": "task"}.get(kind, "branch"),
                        "tag", f"br-{kind}")
            tag.set_valign(Gtk.Align.CENTER)
            top.pack_start(tag, False, False, 0)
        box.pack_start(top, False, False, 0)

        if snap.merging:
            sub = f'<span foreground="{RED}">merge em andamento</span>'
        elif snap.remote_branch:
            sub = GLib.markup_escape_text(snap.remote_branch) + ("" if snap.has_upstream else "  · sem upstream configurado")
        else:
            sub = "ainda não publicada no remoto"
        box.pack_start(label("", "sub", markup=sub), False, False, 0)
        return box

    def _stat_pills(self, st):
        box = Gtk.Box(spacing=6)
        pills = []
        if st.conflicts:
            pills.append(f'<span foreground="{RED}"><b>{st.conflicts}</b></span> em conflito')
        if st.unstaged:
            pills.append(f'<span foreground="{AMBER}"><b>{st.unstaged}</b></span> modificados')
        if st.staged:
            pills.append(f'<span foreground="{GREEN}"><b>{st.staged}</b></span> no stage')
        if st.untracked:
            pills.append(f'<b>{st.untracked}</b> novos')
        if not pills:
            pills.append(f'<span foreground="{GREEN}">✓</span> nada pendente')
        for markup in pills:
            box.pack_start(label("", "pill", markup=markup), False, False, 0)
        return box

    def _compare_row(self, title, subtitle, ahead, behind, tooltip, missing=None):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        top = Gtk.Box(spacing=8)
        top.pack_start(label(title, "panel-label"), False, False, 0)
        top.pack_start(label(subtitle, "dim", ellipsize=Pango.EllipsizeMode.MIDDLE), True, True, 0)
        if missing:
            top.pack_end(label(missing, "dim"), False, False, 0)
        else:
            top.pack_end(label("", markup=counts_markup(ahead, behind)), False, False, 0)
        row.pack_start(top, False, False, 0)
        row.pack_start(SplitBar(ahead, behind, unknown=bool(missing)), False, False, 0)
        row.set_tooltip_text(tooltip)
        return row

    def _compare_panel(self, snap):
        panel = add_classes(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "panel")
        panel.pack_start(
            self._compare_row(
                "Remoto", snap.remote_branch or "", snap.remote_ahead, snap.remote_behind,
                "↑ commits seus que ainda não foram enviados · ↓ commits no GitLab que você ainda não baixou",
                missing=None if snap.remote_branch else "não publicada",
            ),
            False, False, 0,
        )
        if snap.base and snap.status.branch != snap.base:
            panel.pack_start(
                self._compare_row(
                    snap.base.capitalize(), f"origin/{snap.base}", snap.base_ahead, snap.base_behind,
                    f"↑ commits seus que a {snap.base} não tem · ↓ commits da {snap.base} que sua branch não tem",
                ),
                False, False, 0,
            )
        return panel

    def _alert(self, kind, markup, *actions):
        box = add_classes(Gtk.Box(spacing=8), "alert", kind)
        text = label("", markup=markup)
        text.set_line_wrap(True)
        text.set_max_width_chars(34)
        box.pack_start(text, True, True, 0)
        for action in reversed(actions):
            box.pack_end(action, False, False, 0)
        return box

    def _alerts(self, snap):
        """O "e agora?": recomendações em ordem de prioridade, cada uma com a ação certa."""
        st, alerts = snap.status, []
        clean = st.changes == 0
        need_clean = "Faça commit ou stash das suas alterações antes"
        open_code = ActionButton("VS Code", self.open_editor)

        if snap.merging:
            alerts.append(self._alert(
                "danger", f"<b>Merge em andamento</b> · {plural(st.conflicts, 'arquivo')} em conflito",
                ActionButton("VS Code", self.open_editor, primary=True),
                ActionButton("Abortar", lambda: self.run(gitops.abort_merge, self.path), confirm=True),
            ))
        elif st.changes:
            alerts.append(self._alert(
                "info", f"<b>{plural(st.changes, 'alteração', 'alterações')}</b> não commitada{'s' if st.changes > 1 else ''}",
                open_code,
            ))

        stale = ""
        if not snap.last_fetch or time.time() - snap.last_fetch > STALE_FETCH:
            stale = f'\n<span foreground="{DIM}">Último fetch {time_ago(snap.last_fetch, "há ") if snap.last_fetch else "nunca feito"} — faça fetch para ver o estado real.</span>'

        # Remoto: puxar antes de empurrar.
        if st.branch and not snap.merging:
            if not snap.remote_branch:
                if st.branch != snap.base:
                    alerts.append(self._alert(
                        "warn", "Branch <b>ainda não publicada</b> no GitLab",
                        ActionButton("Publicar", lambda: self.run(gitops.push, self.path, st.branch, True), confirm=True,
                                     tooltip=f"git push -u origin {st.branch}"),
                    ))
            elif snap.remote_ahead and snap.remote_behind:
                alerts.append(self._alert(
                    "danger",
                    f"<b>Divergiu do remoto</b>: {snap.remote_ahead} seus × {snap.remote_behind} de lá"
                    f"{self._conflict_text(snap.remote_conflicts)}. Faça pull antes do push.",
                    ActionButton("Pull", lambda: self.run(gitops.pull, self.path, True, after=self._after_merge),
                                 confirm=True, sensitive=clean, tooltip="git pull --no-rebase" if clean else need_clean),
                ))
            elif snap.remote_behind:
                alerts.append(self._alert(
                    "warn", f"O remoto tem <b>{plural(snap.remote_behind, 'commit novo', 'commits novos')}</b> — faça pull antes do push",
                    ActionButton("Pull", lambda: self.run(gitops.pull, self.path), primary=True, tooltip="git pull --ff-only"),
                ))
            elif snap.remote_ahead:
                alerts.append(self._alert(
                    "warn", f"<b>{plural(snap.remote_ahead, 'commit', 'commits')}</b> para enviar",
                    ActionButton("Push", lambda: self.run(gitops.push, self.path, st.branch, not snap.has_upstream),
                                 confirm=True, primary=True, tooltip="git push"),
                ))

        # Base: a develop andou? Sua branch está pronta para entrar nela?
        if snap.base and st.branch and st.branch != snap.base and not snap.merging:
            base_ref = f"origin/{snap.base}"
            if snap.base_behind:
                kind = "danger" if snap.base_conflicts else "warn"
                alerts.append(self._alert(
                    kind,
                    f"A <b>{snap.base}</b> tem {plural(snap.base_behind, 'commit', 'commits')} que sua branch não tem"
                    f"{self._conflict_text(snap.base_conflicts)}. Atualize antes de abrir o MR.{stale}",
                    ActionButton("Atualizar", lambda: self.run(gitops.merge, self.path, base_ref, after=self._after_merge),
                                 confirm=True, sensitive=clean,
                                 tooltip=f"git merge {base_ref}" if clean else need_clean),
                ))
            elif snap.base_ahead and snap.remote_branch and not snap.remote_ahead and not snap.remote_behind and snap.web_url:
                alerts.append(self._alert(
                    "ok", f"{plural(snap.base_ahead, 'commit pronto', 'commits prontos')} para entrar na <b>{snap.base}</b>",
                    ActionButton("Abrir MR", lambda: self.open_url(
                        gitops.merge_request_url(snap.web_url, st.branch, snap.base)), primary=True,
                        tooltip="Abre a página de novo Merge Request no GitLab (no navegador)"),
                ))
            elif not snap.base_ahead and not snap.base_behind:
                alerts.append(self._alert("ok", f"Igual à <b>{snap.base}</b> — nada para mesclar"))

        if not alerts:
            alerts.append(self._alert("ok", "<b>Tudo em dia</b> ✓"))
        return alerts

    @staticmethod
    def _conflict_text(conflicts):
        if conflicts is None:
            return ""
        if not conflicts:
            return f' · <span foreground="{GREEN}">sem conflitos ✓</span>'
        files = ", ".join(GLib.markup_escape_text(Path(f).name) for f in conflicts[:3])
        more = f" +{len(conflicts) - 3}" if len(conflicts) > 3 else ""
        return f' · <span foreground="{RED}"><b>{plural(len(conflicts), "conflito")}</b></span> ({files}{more})'

    def _branches(self, snap):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        head = Gtk.Box(spacing=8)
        head.pack_start(label("BRANCHES", "section-title"), False, False, 0)
        note = f"vs {snap.base} · mais recentes primeiro" if snap.base else "mais recentes primeiro"
        head.pack_start(label(note, "section-note"), False, False, 0)
        box.pack_start(head, False, False, 2)

        clean = snap.status.changes == 0 and not snap.merging
        shown = snap.branches if self.show_all_branches else snap.branches[:BRANCHES_COLLAPSED]
        for branch in shown:
            box.pack_start(self._branch_row(branch, clean), False, False, 0)

        hidden = len(snap.branches) - BRANCHES_COLLAPSED
        if hidden > 0:
            more = add_classes(Gtk.Button(label="mostrar menos" if self.show_all_branches else f"ver todas (+{hidden})"), "pill")
            more.set_can_focus(False)
            more.set_halign(Gtk.Align.START)
            more.connect("clicked", self._toggle_branches)
            box.pack_start(more, False, False, 2)
        return box

    def _toggle_branches(self, *_):
        self.show_all_branches = not self.show_all_branches
        self.render()

    def _branch_row(self, branch, clean):
        events = Gtk.EventBox()
        row = add_classes(Gtk.Box(spacing=8), "brow")
        row.pack_start(label(branch.name, "bname", ellipsize=Pango.EllipsizeMode.MIDDLE), True, True, 0)

        # Branches base (develop, homologa, main…) nunca contam como "mesclada" nem podem ser excluídas daqui.
        protected = branch.name in gitops.BASE_CANDIDATES
        merged = branch.ahead == 0 and not protected
        if branch.ahead is not None:
            if merged:
                info = label("mesclada ✓", "st-ok")
                info.set_tooltip_text("Tudo dessa branch já está na base — pode ser excluída")
            else:
                info = label("", "counts", markup=counts_markup(branch.ahead, branch.behind))
                info.set_tooltip_text("↑ commits que ainda não estão na base · ↓ commits da base que faltam nela")
            row.pack_start(info, False, False, 0)
        if "gone" in branch.track:
            row.pack_start(label("remota apagada", "dim"), False, False, 0)

        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_transition_duration(100)
        stack.add_named(label(time_ago(branch.date) if branch.date else "", "dim", xalign=1), "age")
        actions = Gtk.Box(spacing=4)
        actions.pack_start(ActionButton(
            "Usar", lambda: self.run(gitops.switch, self.path, branch.name), sensitive=clean,
            tooltip=f"git switch {branch.name}" if clean else "Faça commit ou stash das suas alterações antes",
        ), False, False, 0)
        if merged:
            actions.pack_start(ActionButton(
                "Excluir", lambda: self.run(gitops.delete_branch, self.path, branch.name), confirm=True,
                tooltip=f"git branch -d {branch.name} (só apaga se já estiver mesclada)",
            ), False, False, 0)
        stack.add_named(actions, "actions")
        row.pack_end(stack, False, False, 0)

        events.add(row)
        events.connect("enter-notify-event", lambda *_: stack.set_visible_child_name("actions"))
        events.connect("leave-notify-event", lambda _w, e: e.detail == Gdk.NotifyType.INFERIOR or stack.set_visible_child_name("age"))
        return events

    # ---- ações --------------------------------------------------------

    def run(self, fn, *args, after=None, quiet=False):
        if self.busy:
            return
        path = self.path
        self.set_busy(True)

        def done(result):
            self.set_busy(False)
            ok, message = (False, str(result)) if isinstance(result, Exception) else result
            if not (quiet and ok):
                self.toast(message, ok)
            if after:
                after(ok)
            if path == self.path:
                self.reload()
            self.app.refresh_statuses([path])

        gitops.submit(done, fn, *args)

    def fetch(self, quiet=False):
        if self.path:
            self.run(gitops.fetch, self.path, quiet=quiet)

    def _after_merge(self, ok):
        if not ok and self.path and (Path(self.path) / ".git" / "MERGE_HEAD").exists():
            self.open_editor()

    def cycle_base(self, *_):
        if not self.snap or len(self.snap.bases) < 2:
            return
        bases = self.snap.bases
        nxt = bases[(bases.index(self.snap.base) + 1) % len(bases)]
        self.app.store.section("bases")[self.path] = nxt
        self.app.store.save_soon()
        self.reload()

    def set_busy(self, busy):
        self.busy = busy
        self.spinner.set_visible(busy)
        (self.spinner.start if busy else self.spinner.stop)()
        self.content.set_sensitive(not busy)
        self.fetch_pill.set_sensitive(not busy)

    def open_editor(self):
        spawn([*self.app.config["editor"], self.path], self.path)

    def open_url(self, url):
        try:
            Gio.AppInfo.launch_default_for_uri(url, None)
        except GLib.Error as err:
            self.toast(f"Não foi possível abrir o navegador: {err.message}", ok=False)

    def toast(self, message, ok=True):
        icon = f'<span foreground="{GREEN}">✓</span>' if ok else f'<span foreground="{RED}">✕</span>'
        self.toast_label.set_markup(f"{icon}  {GLib.markup_escape_text(message)}")
        self.toast_label.show()
        if self._toast_source:
            GLib.source_remove(self._toast_source)
        self._toast_source = GLib.timeout_add(6000 if not ok else 3500, self._clear_toast)

    def _clear_toast(self):
        self._toast_source = 0
        self.toast_label.hide()
        return False
