"""Paleta e CSS, inspirados no app e nos overlays do Shugo.GG."""

ACCENT = "#ff8e05"   # laranja dos títulos e seleção
BAR = "#ffa53a"      # laranja das barras
BLUE = "#5aa2ff"
GREEN = "#5fd068"
RED = "#ff6b6b"
AMBER = "#f2b84b"
TEXT = "#f1f2f4"
MUTED = "#9298a2"
DIM = "#646b75"

FAMILY_COLORS = ["#7c8cf8", "#4fa7a0", "#f27178", "#b07cf0", "#e8b04a", "#4fa3e0", "#7fbf5a", "#e077a9"]
BRANCH_COLORS = {"dev": "#4fc1b6", "prod": "#f27178", "hml": "#e8b04a", "feat": "#b394f5", "other": "#8b949e"}
ALERT_COLORS = {"danger": RED, "warn": ACCENT, "info": BLUE, "ok": GREEN}


def rgba(hex_color, alpha):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _each(template, items):
    return "\n".join(template.format(k=k, c=c, soft=rgba(c, 0.13), mid=rgba(c, 0.16)) for k, c in items)


CSS = f"""
* {{ font-family: "Noto Sans", sans-serif; }}
window {{ background: transparent; }}
label {{ color: {TEXT}; }}

/* ---- barra principal (hub) ---- */
.hub {{
    background: rgba(24, 28, 35, 0.97);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.5);
    padding: 6px 8px;
}}
.logo {{
    background: {ACCENT};
    color: #0b0e14;
    border-radius: 6px;
    font-size: 9px;
    font-weight: 900;
    min-width: 24px;
    min-height: 24px;
}}
.hub-name {{ font-size: 13px; font-weight: 800; }}
.hub-idle {{ color: {DIM}; font-size: 12px; }}
.chips {{ padding-top: 7px; }}
.chip {{
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid transparent;
    border-radius: 999px;
    box-shadow: none;
    color: {MUTED};
    font-size: 11.5px;
    font-weight: 700;
    min-height: 0;
    padding: 2px 10px;
}}
.chip:hover {{ background: rgba(255, 255, 255, 0.1); color: {TEXT}; }}
.chip:checked {{ background: {rgba(ACCENT, 0.15)}; border-color: {rgba(ACCENT, 0.5)}; color: {ACCENT}; }}
.chip label {{ color: inherit; }}

/* ---- cards ---- */
.card {{
    background: rgba(36, 40, 47, 0.97);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.5);
    padding: 10px 12px 12px;
}}
.card-icon {{ color: {ACCENT}; font-size: 16px; font-weight: 900; }}
.card-title {{ font-size: 14.5px; font-weight: 800; }}
.xbtn {{
    background: transparent;
    border: none;
    box-shadow: none;
    color: {DIM};
    min-width: 22px;
    min-height: 22px;
    padding: 0;
    border-radius: 6px;
}}
.xbtn:hover {{ background: rgba(255, 255, 255, 0.08); color: {TEXT}; }}
.xbtn label {{ color: inherit; }}

.pill {{
    background: rgba(255, 255, 255, 0.07);
    border-radius: 999px;
    color: {MUTED};
    font-size: 11.5px;
    padding: 2px 9px;
}}
button.pill {{ border: none; box-shadow: none; min-height: 0; }}
button.pill:hover {{ background: rgba(255, 255, 255, 0.12); }}
button.pill label {{ color: {MUTED}; }}

.panel {{
    background: #12151a;
    border-radius: 10px;
    padding: 9px 12px 11px;
}}
.panel-label {{ font-size: 12.5px; font-weight: 800; }}
.big {{ font-size: 16px; font-weight: 800; }}
.sub {{ color: {MUTED}; font-size: 11.5px; }}
.dim {{ color: {DIM}; font-size: 11px; }}
.section-title {{ color: {ACCENT}; font-size: 10px; font-weight: 800; letter-spacing: 1px; }}
.section-note {{ color: {DIM}; font-size: 10.5px; }}

.alert {{
    border-radius: 8px;
    border-left: 3px solid transparent;
    padding: 5px 8px 5px 10px;
    min-height: 26px;
}}
.alert label {{ font-size: 12px; }}
{_each(".alert.{k} {{ background: {soft}; border-left-color: {c}; }}", ALERT_COLORS.items())}

button.act {{
    background: rgba(255, 255, 255, 0.09);
    border: none;
    border-radius: 6px;
    box-shadow: none;
    min-height: 0;
    padding: 2px 9px;
}}
button.act label {{ color: {TEXT}; font-size: 11.5px; font-weight: 700; }}
button.act:hover {{ background: rgba(255, 255, 255, 0.16); }}
button.act.primary {{ background: {ACCENT}; }}
button.act.primary label {{ color: #1a1206; }}
button.act.primary:hover {{ background: #ffa22e; }}
button.act.armed {{ background: {RED}; }}
button.act.armed label {{ color: #1a0606; }}
button.act:disabled {{ opacity: 0.4; }}

.toast {{ font-size: 11.5px; padding: 2px 2px 0; }}

/* ---- linhas de projeto ---- */
entry.query {{
    background: #12151a;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    box-shadow: none;
    color: {TEXT};
    caret-color: {ACCENT};
    font-size: 12.5px;
    min-height: 30px;
    padding: 0 8px;
}}
entry.query:focus {{ border-color: {rgba(ACCENT, 0.6)}; }}
entry.query image {{ color: {DIM}; }}
entry.query selection {{ background: {rgba(ACCENT, 0.35)}; }}

list {{ background: transparent; }}
.section {{ padding: 9px 2px 5px; }}
row.proj {{
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid transparent;
    border-left-width: 3px;
    border-radius: 7px;
    margin-bottom: 4px;
    padding: 0 8px 0 7px;
    min-height: 32px;
    outline: none;
}}
row.proj:hover {{ background: rgba(255, 255, 255, 0.07); }}
{_each("row.proj.stripe-{k} {{ border-left-color: {c}; }}", enumerate(FAMILY_COLORS))}
row.proj:selected {{ background: {rgba(ACCENT, 0.13)}; border-color: {ACCENT}; }}

.badge {{ min-width: 22px; min-height: 22px; border-radius: 6px; font-size: 9.5px; font-weight: 800; }}
{_each(".badge.fam-{k} {{ color: {c}; background: {mid}; }}", enumerate(FAMILY_COLORS))}
.name {{ font-size: 12.5px; font-weight: 700; }}
.tag {{ font-size: 10px; font-weight: 700; border-radius: 4px; padding: 1px 6px; }}
{_each(".tag.br-{k} {{ color: {c}; background: {soft}; }}", BRANCH_COLORS.items())}
.st-dirty {{ color: {AMBER}; font-size: 11px; font-weight: 700; }}
.st-ahead {{ color: {BAR}; font-size: 11px; font-weight: 700; }}
.st-behind {{ color: {BLUE}; font-size: 11px; font-weight: 700; }}
.st-ok {{ color: {GREEN}; font-size: 11px; font-weight: 700; }}

.empty {{ color: {DIM}; font-size: 12px; padding: 18px; }}

/* ---- linhas de branch ---- */
.brow {{ border-radius: 7px; padding: 3px 6px; min-height: 26px; }}
.brow:hover {{ background: rgba(255, 255, 255, 0.05); }}
.bname {{ font-size: 12px; font-weight: 600; }}
.counts {{ font-size: 11.5px; }}
"""
