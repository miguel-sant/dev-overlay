"""Leitura do estado dos repositórios e ações git.

Tudo roda em threads (o git pode demorar) e o resultado volta para a thread da UI via GLib.idle_add.
Só `fetch`, `pull` e `push` falam com o servidor — e só quando o usuário pede.
Nenhum commit é criado aqui além do commit de merge que o próprio `git merge` faz, com a identidade
configurada no git do usuário.
"""
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from gi.repository import GLib

BASE_CANDIDATES = ("develop", "homologa", "main", "master", "producao", "production")

_POOL = ThreadPoolExecutor(max_workers=4)


def submit(callback, fn, *args):
    """Roda `fn(*args)` numa thread e entrega o resultado para `callback` na thread da UI."""

    def deliver(future):
        try:
            result = future.result()
        except Exception as err:  # noqa: BLE001 — erro inesperado vira mensagem na UI
            result = err
        GLib.idle_add(lambda: callback(result) and False)

    _POOL.submit(fn, *args).add_done_callback(deliver)


def _env():
    # Não herda o askpass/IPC do VS Code (se o overlay foi aberto por um terminal dele) e nunca
    # fica esperando senha: sem credencial salva, o comando falha na hora.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VSCODE_", "GIT_ASKPASS", "ELECTRON_"))}
    env.update(
        LC_ALL="C",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
        GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10",
    )
    return env


def git(path, *args, timeout=15):
    try:
        return subprocess.run(
            ["git", *args], cwd=path, env=_env(), capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "tempo esgotado")
    except OSError as err:
        return subprocess.CompletedProcess(args, 127, "", str(err))


@dataclass
class RepoStatus:
    branch: str | None = None   # None = HEAD destacado
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    conflicts: int = 0

    @property
    def changes(self):
        return self.staged + self.unstaged + self.untracked + self.conflicts


def read_status(path):
    """Estado rápido do working tree. None se a pasta não for um repositório git."""
    if not (Path(path) / ".git").exists():
        return None
    r = git(path, "status", "--porcelain=v2", "--branch")
    if r.returncode != 0:
        return None
    st = RepoStatus()
    for line in r.stdout.splitlines():
        if line.startswith("# branch.head "):
            head = line[14:]
            st.branch = None if head == "(detached)" else head
        elif line.startswith("# branch.upstream "):
            st.upstream = line[18:]
        elif line.startswith("# branch.ab "):
            a, b = line[12:].split()
            st.ahead, st.behind = int(a), -int(b)
        elif line.startswith(("1 ", "2 ")):
            xy = line[2:4]
            st.staged += xy[0] != "."
            st.unstaged += xy[1] != "."
        elif line.startswith("u "):
            st.conflicts += 1
        elif line.startswith("? "):
            st.untracked += 1
    return st


@dataclass
class BranchInfo:
    name: str
    date: int
    ahead: int | None   # commits que a branch tem e a base não
    behind: int | None  # commits que a base tem e a branch não
    track: str


@dataclass
class Snapshot:
    path: str
    status: RepoStatus
    merging: bool = False
    bases: list = field(default_factory=list)
    base: str | None = None
    base_ahead: int = 0
    base_behind: int = 0
    base_conflicts: list | None = None   # None = não calculado
    remote_branch: str | None = None     # upstream ou origin/<branch>, se existir
    remote_ahead: int = 0
    remote_behind: int = 0
    remote_conflicts: list | None = None
    has_upstream: bool = False
    branches: list = field(default_factory=list)
    web_url: str | None = None
    last_fetch: float | None = None


def _count(path, left, right):
    r = git(path, "rev-list", "--left-right", "--count", f"{left}...{right}")
    if r.returncode != 0:
        return 0, 0
    a, b = r.stdout.split()
    return int(a), int(b)


def predict_conflicts(path, ours, theirs):
    """Simula o merge sem tocar no working tree. [] = sem conflito; lista de arquivos; None = não deu."""
    r = git(path, "merge-tree", "--write-tree", "--name-only", "--no-messages", ours, theirs)
    if r.returncode == 0:
        return []
    if r.returncode == 1:
        return [line for line in r.stdout.splitlines()[1:] if line.strip()]
    return None


def web_url(remote):
    remote = remote.strip()
    if remote.startswith("git@"):
        host, _, repo = remote[4:].partition(":")
        remote = f"https://{host}/{repo}"
    remote = remote.removesuffix(".git")
    if "@" in remote.split("//", 1)[-1].split("/", 1)[0]:
        # Tira usuário/senha embutidos na URL.
        scheme, rest = remote.split("//", 1)
        remote = f"{scheme}//{rest.split('@', 1)[1]}"
    return remote if remote.startswith("http") else None


def merge_request_url(web, source, target):
    return (
        f"{web}/-/merge_requests/new?merge_request%5Bsource_branch%5D={quote(source, safe='')}"
        f"&merge_request%5Btarget_branch%5D={quote(target, safe='')}"
    )


def snapshot(path, base_pref=None):
    """Tudo que o card de git mostra. Só leitura e só local (não fala com o servidor)."""
    st = read_status(path)
    if st is None:
        return None
    git_dir = Path(path) / ".git"
    snap = Snapshot(path=path, status=st, merging=(git_dir / "MERGE_HEAD").exists())
    try:
        snap.last_fetch = (git_dir / "FETCH_HEAD").stat().st_mtime
    except OSError:
        pass

    remotes = set(git(path, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin").stdout.split())
    snap.bases = [b for b in BASE_CANDIDATES if f"origin/{b}" in remotes]
    snap.base = base_pref if base_pref in snap.bases else (snap.bases[0] if snap.bases else None)
    base_ref = f"origin/{snap.base}" if snap.base else None

    if st.upstream:
        snap.remote_branch, snap.has_upstream = st.upstream, True
        snap.remote_ahead, snap.remote_behind = st.ahead, st.behind
    elif st.branch and f"origin/{st.branch}" in remotes:
        snap.remote_branch = f"origin/{st.branch}"
        snap.remote_ahead, snap.remote_behind = _count(path, "HEAD", snap.remote_branch)
    if snap.remote_ahead and snap.remote_behind:
        snap.remote_conflicts = predict_conflicts(path, "HEAD", snap.remote_branch)

    if base_ref and st.branch != snap.base:
        snap.base_ahead, snap.base_behind = _count(path, "HEAD", base_ref)
        if snap.base_ahead and snap.base_behind:
            snap.base_conflicts = predict_conflicts(path, "HEAD", base_ref)
        elif snap.base_behind:
            snap.base_conflicts = []  # fast-forward: nunca dá conflito

    fmt = "%(refname:short)%09%(committerdate:unix)%09%(upstream:track)"
    if base_ref:
        fmt += f"%09%(ahead-behind:{base_ref})"
    r = git(path, "for-each-ref", "--sort=-committerdate", f"--format={fmt}", "refs/heads")
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if parts[0] == st.branch:
            continue
        ahead = behind = None
        if len(parts) > 3 and parts[3]:
            ahead, behind = (int(n) for n in parts[3].split())
        snap.branches.append(BranchInfo(parts[0], int(parts[1] or 0), ahead, behind, parts[2]))

    remote = git(path, "remote", "get-url", "origin")
    if remote.returncode == 0:
        snap.web_url = web_url(remote.stdout)
    return snap


# ---- ações -------------------------------------------------------------


def _result(r, ok_message):
    if r.returncode == 0:
        return True, ok_message
    lines = [line.strip() for line in (r.stderr or r.stdout).splitlines() if line.strip()]
    hint = next((line for line in lines if line.startswith(("fatal:", "error:", "CONFLICT"))), lines[-1] if lines else "")
    if "could not read Username" in hint or "Authentication failed" in hint:
        hint = "sem credencial salva para o GitLab — faça um fetch pelo terminal uma vez"
    return False, hint.removeprefix("fatal: ").removeprefix("error: ")


def fetch(path):
    return _result(git(path, "fetch", "--prune", "--quiet", "origin", timeout=90), "Fetch concluído")


def pull(path, merge=False):
    args = ["pull", "--no-rebase", "--no-edit"] if merge else ["pull", "--ff-only"]
    return _result(git(path, *args, timeout=120), "Pull concluído")


def push(path, branch, publish=False):
    args = ["push", "-u", "origin", branch] if publish else ["push"]
    return _result(git(path, *args, timeout=120), "Branch publicada" if publish else "Push concluído")


def merge(path, ref):
    r = git(path, "merge", "--no-edit", ref, timeout=60)
    if r.returncode != 0 and (Path(path) / ".git" / "MERGE_HEAD").exists():
        return False, "Merge com conflitos — resolva no VS Code"
    return _result(r, f"{ref} mesclado")


def abort_merge(path):
    return _result(git(path, "merge", "--abort"), "Merge abortado")


def switch(path, branch):
    return _result(git(path, "switch", branch), f"Agora em {branch}")


def delete_branch(path, branch):
    # -d (e não -D): o git recusa se a branch não estiver mesclada.
    return _result(git(path, "branch", "-d", branch), f"{branch} excluída")
