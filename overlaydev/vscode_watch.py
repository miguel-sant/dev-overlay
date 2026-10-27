"""Descobre qual projeto está aberto na janela do VS Code em foco, pelo título da janela.

O título padrão do VS Code é "arquivo - pasta - Visual Studio Code"; basta achar a pasta nele.
Só funciona no X11 (usa libwnck); no Wayland simplesmente não faz nada.
"""
try:
    import gi

    gi.require_version("Wnck", "3.0")
    from gi.repository import Wnck
except (ValueError, ImportError):
    Wnck = None


class VSCodeWatcher:
    def __init__(self, on_project, projects_fn):
        """`on_project(path)` é chamado quando o foco vai para um VS Code com um projeto conhecido."""
        self.on_project = on_project
        self.projects_fn = projects_fn
        self._window = None
        self._name_handler = 0
        if Wnck is None:
            return
        self.screen = Wnck.Screen.get_default()
        if self.screen is None:
            return
        self.screen.connect("active-window-changed", self._on_active_changed)

    def _on_active_changed(self, screen, _previous):
        if self._window is not None and self._name_handler:
            self._window.disconnect(self._name_handler)
        self._window = screen.get_active_window()
        self._name_handler = 0
        if self._window is not None and self._is_vscode(self._window):
            # O título muda quando se troca de pasta na mesma janela.
            self._name_handler = self._window.connect("name-changed", self._check)
            self._check(self._window)

    @staticmethod
    def _is_vscode(window):
        group = window.get_class_group_name() or ""
        return group.lower() in ("code", "code - oss", "vscodium", "code-insiders")

    def _check(self, window):
        title = f" - {window.get_name()} - "
        matches = [p for p in self.projects_fn() if f" - {p.name} - " in title or f" - {p.name} [" in title]
        if matches:
            # O nome mais longo vence (sismed-adm em vez de sismed).
            self.on_project(max(matches, key=lambda p: len(p.name)).path)
