"""
🚀 PilotPro — Gestion de projet « Notion × MS Project » (Streamlit)

6 vues : Projets · Tâches · Planning · Chemin critique · Ressources · COPIL (EVM)
- Tout est modifiable, aucune donnée pré-remplie.
- Dépendances entre tâches (fin → début) et calcul du chemin critique (CPM) :
  dates au plus tôt / au plus tard, marges, chaîne critique, verdict d'échéance.
- Gantt style MS Project : barres par projet, avancement intégré,
  tâches critiques en rouge, connecteurs de dépendances, week-ends grisés,
  ligne « aujourd'hui », zoom (rangeslider).
- Base de tâches façon Notion : édition en ligne (ajout, modification, suppression),
  avec coût prévu (€) et coût réel (€) par tâche pour piloter le budget.
- COPIL / EVM : PV · EV · AC, SV · CV, SPI · CPI, EAC · VAC · TCPI,
  verdict délai + budget, et courbe en S (planifié / valorisé / dépensé).
- Ressources : capacité par personne (140 h/mois par défaut) et taux de charge.
- Design « MS Project pro » : bleu #2563EB, grille fine, titres de section en
  capitales, navigation par onglets en haut de page + liens rapides entre les vues.

Installation :
    pip install streamlit pandas plotly
    streamlit run pilotpro.py
(Plotly est optionnel : un repli Altair est utilisé s'il est absent.)
"""

from __future__ import annotations

import html as _html
from collections import deque
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
    PLOTLY = True
except Exception:
    PLOTLY = False

try:
    import altair as alt
    ALTAIR = True
except Exception:
    ALTAIR = False

# ------------------------------------------------------------------ constantes

TODAY = date.today()
MONTHLY_MAX_H = 140
ACCENT = "#2563EB"

STATUSES = ["Backlog", "À faire", "En cours", "En revue", "Terminé"]
PRIORITIES = ["Critique", "Haute", "Moyenne", "Basse"]

STATUS_STYLES = {
    "Backlog": ("#E5E7EB", "#4B5563"),
    "À faire": ("#DBEAFE", "#1D4ED8"),
    "En cours": ("#FEF3C7", "#B45309"),
    "En revue": ("#EDE9FE", "#6D28D9"),
    "Terminé": ("#D1FAE5", "#047857"),
}
PRIORITY_STYLES = {
    "Critique": ("#FEE2E2", "#B91C1C"),
    "Haute": ("#FFEDD5", "#C2410C"),
    "Moyenne": ("#FEF9C3", "#A16207"),
    "Basse": ("#F1F5F9", "#475569"),
}
DEFAULT_COLORS = ["#4F46E5", "#0EA5E9", "#10B981", "#F59E0B",
                 "#EF4444", "#8B5CF6", "#EC4899", "#14B8A6"]

VIEWS = ["📁 Projets", "🗒️ Tâches", "📅 Planning",
         "🔗 Chemin critique", "👥 Ressources", "📊 COPIL (EVM)"]

# ------------------------------------------------------------------ petits outils


def d(days: int) -> date:
    """Date relative à aujourd'hui (d(-3) = il y a 3 jours)."""
    return TODAY + timedelta(days=days)


def esc(s) -> str:
    return _html.escape(str(s))


def fmt_date(x: date | None) -> str:
    return x.strftime("%d/%m/%Y") if x else "—"


def fmt_money(v) -> str:
    try:
        return f"{int(round(float(v))):,}".replace(",", " ") + " €"
    except Exception:
        return "—"


def parse_date(v, fallback=None):
    """Accepte date, datetime, 'YYYY-MM-DD', 'JJ/MM/AAAA'."""
    if isinstance(v, date):
        return v
    if isinstance(v, str) and v.strip():
        s = v.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except Exception:
                pass
    return fallback


def ts_ms(x: date) -> float:
    return (x - date(1970, 1, 1)).total_seconds() * 1000.0


def duration_days(t: dict) -> int:
    return max(1, (t["due"] - t["start"]).days + 1)


# ------------------------------------------------------------------ état global


def init_state():
    SS = st.session_state
    SS.setdefault("projects", [])
    SS.setdefault("tasks", [])
    SS.setdefault("members", [])
    SS.setdefault("view", VIEWS[0])


def next_id(prefix: str, items: list[dict]) -> str:
    used = set()
    for x in items:
        try:
            if str(x.get("id", "")).startswith(prefix):
                used.add(int(x["id"][len(prefix):]))
        except Exception:
            pass
    n = 1
    while n in used:
        n += 1
    return f"{prefix}{n}"


def get_project(pid: str):
    return next((p for p in st.session_state.projects if p["id"] == pid), None)


def get_task(tid: str):
    return next((t for t in st.session_state.tasks if t["id"] == tid), None)


def get_member(mid: str):
    return next((m for m in st.session_state.members if m["id"] == mid), None)


def project_tasks(pid: str) -> list[dict]:
    return [t for t in st.session_state.tasks if t["projectId"] == pid]


def task_by_id() -> dict:
    return {t["id"]: t for t in st.session_state.tasks}


def sanitize_deps():
    """Purge les dépendances orphelines, auto-référencées ou inter-projets."""
    by_id = task_by_id()
    for t in st.session_state.tasks:
        seen, keep = set(), []
        for dep in t.get("deps", []):
            if dep == t["id"] or dep not in by_id or dep in seen:
                continue
            if by_id[dep]["projectId"] != t["projectId"]:
                continue
            keep.append(dep)
            seen.add(dep)
        t["deps"] = keep


# ------------------------------------------------------------------ CPM (chemin critique)


def topo_order(tasks: list[dict]):
    """Tri topologique (Kahn). Retourne (ordre, cycle_booléen)."""
    ids = [t["id"] for t in tasks]
    id_set = set(ids)
    preds = {t["id"]: [p for p in t.get("deps", []) if p in id_set] for t in tasks}
    succs = {i: [] for i in ids}
    indeg = {}
    for i in ids:
        indeg[i] = len(preds[i])
        for p in preds[i]:
            succs[p].append(i)
    q = deque(sorted(i for i in ids if indeg[i] == 0))
    order = []
    while q:
        i = q.popleft()
        order.append(i)
        for s in succs[i]:
            indeg[s] -= 1
            if indeg[s] == 0:
                q.append(s)
    return order, len(order) != len(ids)


def cpm_analyze(tasks: list[dict]):
    """
    Analyse CPM d'un lot de tâches (même projet, dépendances fin → début).
    Retourne None si cycle, sinon un dict :
      es/ef/ls/lf/slack/critical par id + order + project_end.
    """
    if not tasks:
        return None
    order, cycle = topo_order(tasks)
    if cycle:
        return None
    by_id = {t["id"]: t for t in tasks}
    dur = {i: duration_days(by_id[i]) for i in order}

    es, ef = {}, {}
    for i in order:
        preds = by_id[i].get("deps", [])
        base = max((ef[p] for p in preds), default=None)
        start = by_id[i]["start"]
        es[i] = base + timedelta(days=1) if base is not None else start
        ef[i] = es[i] + timedelta(days=dur[i] - 1)

    project_end = max(ef.values())
    ls, lf = {}, {}
    succs = {i: [] for i in order}
    for i in order:
        for p in by_id[i].get("deps", []):
            succs[p].append(i)
    for i in reversed(order):
        if succs[i]:
            lf[i] = min(ls[s] for s in succs[i]) - timedelta(days=1)
        else:
            lf[i] = project_end
        ls[i] = lf[i] - timedelta(days=dur[i] - 1)

    slack = {i: (ls[i] - es[i]).days for i in order}
    critical = {i: (slack[i] <= 0) for i in order}
    return {"es": es, "ef": ef, "ls": ls, "lf": lf, "slack": slack,
            "critical": critical, "order": order, "project_end": project_end}


def critical_chain(tasks: list[dict], cpm: dict) -> list[str]:
    """Chaîne critique dans l'ordre topologique."""
    chain = [i for i in cpm["order"] if cpm["critical"][i]]
    return chain


def reschedule_project(pid: str) -> list[str]:
    """Décale les tâches trop tôt par rapport à leurs dépendances (cascade)."""
    tasks = project_tasks(pid)
    order, cycle = topo_order(tasks)
    if cycle:
        return []
    by_id = {t["id"]: t for t in tasks}
    moved = []
    for i in order:
        t = by_id[i]
        preds = [by_id[p] for p in t.get("deps", [])]
        if not preds:
            continue
        min_start = max(p["due"] for p in preds) + timedelta(days=1)
        if t["start"] < min_start:
            shift = (min_start - t["start"]).days
            t["start"] += timedelta(days=shift)
            t["due"] += timedelta(days=shift)
            moved.append(i)
    return moved


# ------------------------------------------------------------------ EVM (COPIL)


def _evm_fraction(t: dict, day: date) -> float:
    """Fraction planifiée de la tâche au jour `day` (0 → 1, linéaire)."""
    span = max(1, (t["due"] - t["start"]).days)
    f = (day - t["start"]).days / span
    return max(0.0, min(1.0, f))


def evm_analyze(tasks: list[dict]):
    """
    Analyse EVM d'un lot de tâches (coût prévu `cost`, coût réel `spent`).

    Courbes journalières : PV (planifié, linéaire sur chaque fenêtre de tâche),
    EV (valorisé, linéaire plafonné à l'avancement réel), AC (dépensé, linéaire).
    Retourne None si le lot est vide ou sans coûts prévus, sinon un dict :
      series (dates, pv, ev, ac) · kpis au jour J · rows par tâche.
    """
    if not tasks:
        return None
    bac = sum(float(t.get("cost") or 0) for t in tasks)
    if bac <= 0:
        return None
    lo = min(t["start"] for t in tasks)
    hi = max(t["due"] for t in tasks)

    dates, pv_s, ev_s, ac_s = [], [], [], []
    day, end = lo - timedelta(days=1), hi + timedelta(days=1)
    while day <= end:
        dates.append(day)
        pv_s.append(sum(float(t.get("cost") or 0) * _evm_fraction(t, day)
                        for t in tasks))
        ev_s.append(sum(float(t.get("cost") or 0)
                        * min(_evm_fraction(t, day),
                              max(0.0, min(1.0,
                                           float(t.get("progress") or 0) / 100.0)))
                        for t in tasks))
        ac_s.append(sum(float(t.get("spent") or 0) * _evm_fraction(t, day)
                        for t in tasks))
        day += timedelta(days=1)

    def _at(series, day):
        if day <= dates[0]:
            return series[0]
        if day >= dates[-1]:
            return series[-1]
        return series[(day - dates[0]).days]

    pv, ac = _at(pv_s, TODAY), _at(ac_s, TODAY)
    ev = sum(float(t.get("cost") or 0)
             * max(0.0, min(1.0, float(t.get("progress") or 0) / 100.0))
             for t in tasks)
    sv, cv = ev - pv, ev - ac
    spi = ev / pv if pv > 0 else None
    cpi = ev / ac if ac > 0 else None
    eac = bac / cpi if (cpi is not None and cpi > 0) else None
    vac = (bac - eac) if eac is not None else None
    tcpi = None
    if bac - ev > 0 and bac - ac > 0:
        tcpi = (bac - ev) / (bac - ac)
    kpis = {"bac": bac, "pv": pv, "ev": ev, "ac": ac, "sv": sv, "cv": cv,
            "spi": spi, "cpi": cpi, "eac": eac, "vac": vac, "tcpi": tcpi}
    rows = [{"id": t["id"], "title": t["title"],
             "cost": float(t.get("cost") or 0),
             "spent": float(t.get("spent") or 0),
             "progress": int(t.get("progress") or 0)} for t in tasks]
    return {"series": (dates, pv_s, ev_s, ac_s), "kpis": kpis, "rows": rows}


# ------------------------------------------------------------------ design (CSS)


def inject_design():
    css = """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    .stApp { background: #FFFFFF; }
    html, body, [class*="css"] {
        font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    }
    .block-container { padding-top: 1.1rem; max-width: 1200px; padding-bottom: 3rem; }
    h1, h2, h3 { font-family: 'Inter','Segoe UI',system-ui,sans-serif;
                 letter-spacing: -0.01em; color: #1E293B; }
    section[data-testid="stSidebar"] {
        background: #F8FAFC; border-right: 1px solid #E2E8F0;
    }
    section[data-testid="stSidebar"] * { font-family: 'Inter','Segoe UI',sans-serif; }

    /* --- barre d'onglets (navigation principale, en haut de page) --- */
    div[data-testid="stRadio"] {
        border-bottom: 2px solid #E2E8F0; margin-bottom: 14px;
    }
    div[data-testid="stRadio"] label {
        padding: 7px 14px; margin: 0 2px -2px 2px;
        border-radius: 7px 7px 0 0; font-weight: 700; font-size: 12.5px;
        color: #475569; background: transparent; letter-spacing: .02em;
    }
    div[data-testid="stRadio"] label:hover { background: #F1F5F9; }
    div[data-testid="stRadio"] label:has(input:checked) {
        background: #DBEAFE; color: #1D4ED8;
    }
    div[data-testid="stRadio"] label:has(input:checked) p {
        color: #1D4ED8; font-weight: 700;
    }
    label[data-baseweb="radio"] > div:first-child { display: none; }

    div[data-testid="stMetric"] {
        background: #FFFFFF; border: 1px solid #E2E8F0; border-top: 3px solid #2563EB;
        border-radius: 6px; padding: 10px 14px; box-shadow: none;
    }
    div[data-testid="stForm"] {
        background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 6px;
        padding: 16px; box-shadow: none;
    }
    .stButton > button {
        border-radius: 6px; border: 1px solid #CBD5E1; color: #334155;
        font-weight: 600; padding: .38rem .8rem; font-size: 13px;
    }
    .stButton > button:hover { background: #F1F5F9; border-color: #94A3B8;
                               color: #1E293B; }
    .stButton > button[kind="primary"], .stButton > button[kind="primaryFormSubmit"] {
        background: #2563EB; border: 1px solid #2563EB; color: #FFFFFF;
    }
    .stButton > button[kind="primary"]:hover,
    .stButton > button[kind="primaryFormSubmit"]:hover {
        background: #1D4ED8; border-color: #1D4ED8; color: #FFFFFF;
    }
    div[data-testid="stExpander"] {
        border: 1px solid #E2E8F0; border-radius: 6px; background: #FFFFFF;
    }
    div[data-testid="stDataFrame"] { border: 1px solid #E2E8F0; border-radius: 6px; }
    div[data-testid="stAlert"] { border-radius: 6px; }

    /* --- composants PilotPro (style MS Project pro) --- */
    .pp-breadcrumb { font-size: 10.5px; color: #94A3B8; font-weight: 700;
                     letter-spacing: .07em; text-transform: uppercase;
                     margin-bottom: 4px; }
    .pp-header { display: flex; align-items: center; gap: 12px; margin: 2px 0 14px 0; }
    .pp-header-ico {
        width: 40px; height: 40px; border-radius: 6px; font-size: 20px;
        background: #EFF6FF; border: 1px solid #DBEAFE;
        display: flex; align-items: center; justify-content: center; flex: 0 0 auto;
    }
    .pp-header-title { font-size: 19px; font-weight: 800; color: #1E293B;
                       line-height: 1.1; }
    .pp-header-sub { font-size: 12px; color: #64748B; margin-top: 2px; }

    .pp-section { font-size: 11.5px; font-weight: 800; color: #475569;
                  text-transform: uppercase; letter-spacing: .07em;
                  margin: 16px 0 8px 0; padding-bottom: 5px;
                  border-bottom: 1px solid #F1F5F9; }
    .pp-card { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 6px;
               padding: 13px 16px; margin-bottom: 10px; box-shadow: none; }
    .pp-empty { background: #F8FAFC; border: 1px dashed #CBD5E1; border-radius: 6px;
                padding: 30px 20px; text-align: center; color: #64748B;
                margin-bottom: 12px; }
    .pp-chip { display: inline-block; padding: 2px 9px; border-radius: 4px;
               font-size: 11px; font-weight: 700; margin: 0 6px 6px 0;
               white-space: nowrap; }
    .pp-bar { background: #F1F5F9; border-radius: 999px; height: 7px;
              overflow: hidden; margin: 8px 0 4px 0; }
    .pp-bar-fill { height: 7px; border-radius: 999px; }
    .pp-title { font-size: 15px; font-weight: 700; color: #1E293B; }
    .pp-sub { font-size: 12px; color: #64748B; }
    .pp-muted { color: #94A3B8; font-size: 11.5px; }
    .pp-kpi { font-size: 20px; font-weight: 800; color: #1E293B; }
    .pp-kpi-lbl { font-size: 11.5px; color: #64748B; }
    .pp-chain-arrow { color: #94A3B8; font-weight: 700; margin: 0 4px; }
    .pp-verdict { border-radius: 6px; padding: 11px 14px; margin: 10px 0;
                  font-size: 13.5px; font-weight: 600; }
    .pp-legend-dot { display: inline-block; width: 10px; height: 10px;
                     border-radius: 2px; margin-right: 6px; vertical-align: middle; }
    .pp-logo { width: 34px; height: 34px; border-radius: 6px;
               background: linear-gradient(135deg, #2563EB, #1D4ED8); color: #fff;
               font-weight: 800; font-size: 16px; display: flex;
               align-items: center; justify-content: center; }
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def page_header(icon: str, title: str, sub: str, quick: list | None = None):
    """En-tête de vue + fil d'ariane + liens rapides vers les autres onglets."""
    st.markdown(
        f'<div class="pp-breadcrumb">PilotPro / {esc(title)}</div>'
        f'<div class="pp-header"><div class="pp-header-ico">{icon}</div>'
        f'<div><div class="pp-header-title">{esc(title)}</div>'
        f'<div class="pp-header-sub">{esc(sub)}</div></div></div>',
        unsafe_allow_html=True)
    if quick:
        cols = st.columns(len(quick))
        for col, (label, target) in zip(cols, quick):
            with col:
                if st.button(label, key=f"go_{target}_{label}"):
                    goto(target)


def goto(view: str):
    """Change d'onglet (navigation en haut de page)."""
    st.session_state["nav"] = view
    st.session_state["view"] = view
    st.rerun()


def section(label: str):
    """Titre de section façon MS Project (capitales, filet dessous)."""
    st.markdown(f'<div class="pp-section">{esc(label)}</div>',
                unsafe_allow_html=True)


def chip(label: str, bg: str, fg: str) -> str:
    return (f'<span class="pp-chip" style="background:{bg};color:{fg};">'
            f'{esc(label)}</span>')


def status_chip(status: str) -> str:
    bg, fg = STATUS_STYLES.get(status, ("#E5E7EB", "#4B5563"))
    return chip(status, bg, fg)


def priority_chip(p: str) -> str:
    bg, fg = PRIORITY_STYLES.get(p, ("#F1F5F9", "#475569"))
    return chip(p, bg, fg)


def bar_html(pct: float, color: str) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    return (f'<div class="pp-bar"><div class="pp-bar-fill" '
            f'style="width:{pct:.0f}%;background:{color};"></div></div>')


def empty_state(msg: str, hint: str = ""):
    st.markdown(
        f'<div class="pp-empty"><div style="font-size:30px;margin-bottom:8px;">🗂️</div>'
        f'<div style="font-weight:600;color:#374151;">{esc(msg)}</div>'
        f'<div class="pp-sub" style="margin-top:6px;">{esc(hint)}</div></div>',
        unsafe_allow_html=True)


def flash(key: str):
    msg = st.session_state.pop(key, None)
    if msg:
        st.success(msg)


# ------------------------------------------------------------------ vue : PROJETS


def view_projects():
    page_header("📁", "Projets",
                "Créez et pilotez vos projets — tout est modifiable.",
                quick=[("🗒️ Voir les tâches →", VIEWS[1]),
                       ("📅 Voir le planning →", VIEWS[2]),
                       ("📊 COPIL global →", VIEWS[5])])
    flash("projects_flash")

    SS = st.session_state
    projects, tasks = SS.projects, SS.tasks

    # --- KPI globaux
    done = [t for t in tasks if t["status"] == "Terminé"]
    late = [t for t in tasks if t["due"] < TODAY and t["status"] != "Terminé"]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Projets", len(projects))
    with c2:
        st.metric("Tâches", len(tasks))
    with c3:
        st.metric("Terminées", f"{len(done)}/{len(tasks)}" if tasks else "0")
    with c4:
        st.metric("En retard", len(late), delta=f"-{len(late)}" if late else None)

    st.write("")

    # --- formulaire de création
    with st.expander("➕ Nouveau projet", expanded=(len(projects) == 0)):
        with st.form(key="np_form"):
            col1, col2 = st.columns(2)
            with col1:
                np_name = st.text_input("Nom du projet *", key="np_name",
                                        placeholder="Ex. Refonte du site vitrine")
                np_client = st.text_input("Client / sponsor", key="np_client",
                                          placeholder="Ex. Acme Corp")
            with col2:
                np_deadline = st.date_input("Échéance de fin", key="np_deadline",
                                            value=d(60))
                np_budget = st.number_input(
                    "Budget (€)", key="np_budget", min_value=0.0,
                    value=0.0, step=5000.0, format="%.0f")
            np_color = st.color_picker(
                "Couleur", key="np_color",
                value=DEFAULT_COLORS[len(projects) % len(DEFAULT_COLORS)])
            submit = st.form_submit_button("Créer le projet",
                                           type="primary", key="np_submit")
        if submit:
            name = (np_name or "").strip()
            if not name:
                st.error("⚠️ Le nom du projet est obligatoire.")
            else:
                pid = next_id("P", projects)
                SS.projects.append({
                    "id": pid, "name": name,
                    "client": (np_client or "").strip(),
                    "color": np_color or ACCENT,
                    "deadline": np_deadline, "budget": float(np_budget or 0),
                })
                for k in ("np_name", "np_client", "np_deadline", "np_budget"):
                    SS.pop(k, None)
                SS.projects_flash = f"✅ Projet « {name} » créé ({pid})."
                st.rerun()

    # --- liste des projets
    if not projects:
        empty_state("Aucun projet pour le moment",
                    "Créez votre premier projet avec le formulaire ci-dessus.")
        return

    for p in projects:
        p_tasks = project_tasks(p["id"])
        p_done = [t for t in p_tasks if t["status"] == "Terminé"]
        pct = 100 * len(p_done) / len(p_tasks) if p_tasks else 0.0
        days_left = (p["deadline"] - TODAY).days

        if days_left < 0:
            dl_chip = chip(f"⏰ {esc(p['deadline'].strftime('%d/%m/%Y'))} — dépassée",
                           "#FEE2E2", "#B91C1C")
        elif days_left <= 7:
            dl_chip = chip(f"⏰ {esc(p['deadline'].strftime('%d/%m/%Y'))} — J-{days_left}",
                           "#FEF3C7", "#B45309")
        else:
            dl_chip = chip(f"🗓 {esc(p['deadline'].strftime('%d/%m/%Y'))} — J-{days_left}",
                           "#F1F5F9", "#475569")

        st.markdown(
            f"""<div class="pp-card" style="border-left:4px solid {esc(p['color'])};">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
              <div>
                <div class="pp-title">{esc(p['name'])} <span class="pp-muted">· {esc(p['id'])}</span></div>
                <div class="pp-sub">{esc(p['client']) or '—'}</div>
              </div>
              <div style="text-align:right;">
                {dl_chip}
                <div class="pp-kpi" style="font-size:18px;">{fmt_money(p['budget'])}</div>
              </div>
            </div>
            {bar_html(pct, esc(p['color']))}
            <div class="pp-sub">{len(p_done)}/{len(p_tasks)} tâches terminées · {pct:.0f} %</div>
            </div>""",
            unsafe_allow_html=True)

        # --- modifier / supprimer
        with st.expander(f"✏️ Modifier « {p['name']} »", key=f"px_{p['id']}"):
            with st.form(key=f"ed_{p['id']}_form"):
                e1, e2 = st.columns(2)
                with e1:
                    n_name = st.text_input("Nom", key=f"ed_{p['id']}_name",
                                           value=p["name"])
                    n_client = st.text_input("Client", key=f"ed_{p['id']}_client",
                                             value=p["client"])
                with e2:
                    n_deadline = st.date_input("Échéance",
                                               key=f"ed_{p['id']}_deadline",
                                               value=p["deadline"])
                    n_budget = st.number_input(
                        "Budget (€)", key=f"ed_{p['id']}_budget",
                        min_value=0.0, value=float(p["budget"]), step=5000.0,
                        format="%.0f")
                n_color = st.color_picker("Couleur", key=f"ed_{p['id']}_color",
                                          value=p["color"])
                save = st.form_submit_button("💾 Enregistrer", key=f"ed_{p['id']}_submit",
                                             type="primary")
            if save:
                p["name"] = (n_name or p["name"]).strip()
                p["client"] = (n_client or "").strip()
                p["deadline"] = n_deadline
                p["budget"] = float(n_budget or 0)
                p["color"] = n_color or p["color"]
                SS.projects_flash = f"✅ Projet « {p['name']} » mis à jour."
                st.rerun()
            if st.button("🗒️ Tâches de ce projet →", key=f"ptasks_{p['id']}"):
                st.session_state["tf_sel"] = f"{p['id']} · {p['name']}"
                goto(VIEWS[1])
            if st.button("📊 COPIL de ce projet →", key=f"pcopil_{p['id']}"):
                st.session_state["evm_sel"] = f"{p['id']} · {p['name']}"
                goto(VIEWS[5])
            if st.button("🗑️ Supprimer ce projet (et ses tâches)",
                         key=f"del_{p['id']}"):
                SS.projects = [x for x in SS.projects if x["id"] != p["id"]]
                gone = {t["id"] for t in p_tasks}
                SS.tasks = [t for t in SS.tasks if t["projectId"] != p["id"]]
                for t in SS.tasks:
                    t["deps"] = [x for x in t.get("deps", []) if x not in gone]
                SS.projects_flash = f"🗑️ Projet « {p['name']} » supprimé."
                st.rerun()


# ------------------------------------------------------------------ vue : TÂCHES


def apply_task_edits():
    """Callback du data_editor : applique ajouts / modifications / suppressions."""
    SS = st.session_state
    ed = SS.get("tasks_editor") or {}
    ids = SS.get("tasks_map") or []
    name2pid = {p["name"]: p["id"] for p in SS.projects}
    name2mid = {m["name"]: m["id"] for m in SS.members}
    by_id = task_by_id()

    changed = False

    for r, changes in (ed.get("edited_rows") or {}).items():
        r = int(r)
        if r >= len(ids):
            continue
        t = by_id.get(ids[r])
        if t is None or not changes:
            continue
        changed = True
        if "Tâche" in changes:
            t["title"] = str(changes["Tâche"]).strip() or t["title"]
        if "Projet" in changes:
            pid = name2pid.get(changes["Projet"])
            if pid and pid != t["projectId"]:
                t["projectId"] = pid
                t["deps"] = []          # dépendances limitées au même projet
        if "Assigné" in changes:
            t["assigneeId"] = name2mid.get(changes["Assigné"], "")
        if "Statut" in changes and changes["Statut"] in STATUSES:
            t["status"] = changes["Statut"]
            if t["status"] == "Terminé":
                t["progress"] = 100
        if "Priorité" in changes and changes["Priorité"] in PRIORITIES:
            t["priority"] = changes["Priorité"]
        if "Début" in changes:
            t["start"] = parse_date(changes["Début"], t["start"])
        if "Échéance" in changes:
            t["due"] = parse_date(changes["Échéance"], t["due"])
        if "Estim. (h)" in changes:
            try:
                t["estimate"] = max(0.0, float(changes["Estim. (h)"]))
            except Exception:
                pass
        if "Coût prévu (€)" in changes:
            try:
                t["cost"] = max(0.0, float(changes["Coût prévu (€)"] or 0))
            except Exception:
                pass
        if "Coût réel (€)" in changes:
            try:
                t["spent"] = max(0.0, float(changes["Coût réel (€)"] or 0))
            except Exception:
                pass
        if "Avancement" in changes:
            try:
                t["progress"] = int(max(0, min(100, int(changes["Avancement"]))))
            except Exception:
                pass
        if "Déps" in changes:
            raw = str(changes["Déps"])
            cand = [x.strip().upper().replace(" ", "") for x in raw.split(",")]
            t["deps"] = [x for x in cand if x and x != t["id"]]

    for row in (ed.get("added_rows") or []):
        row = row or {}
        if not SS.projects:
            break
        pid = name2pid.get(row.get("Projet")) or SS.projects[0]["id"]
        mid = name2mid.get(row.get("Assigné"), "")
        start = parse_date(row.get("Début"), TODAY)
        due = parse_date(row.get("Échéance"), start + timedelta(days=1))
        title = str(row.get("Tâche") or "").strip() or "Nouvelle tâche"
        status = row.get("Statut") if row.get("Statut") in STATUSES else "À faire"
        prio = row.get("Priorité") if row.get("Priorité") in PRIORITIES else "Moyenne"
        try:
            est = max(0.0, float(row.get("Estim. (h)") or 0.0))
        except Exception:
            est = 0.0
        try:
            cost = max(0.0, float(row.get("Coût prévu (€)") or 0.0))
        except Exception:
            cost = 0.0
        try:
            spent = max(0.0, float(row.get("Coût réel (€)") or 0.0))
        except Exception:
            spent = 0.0
        try:
            prog = int(max(0, min(100, int(row.get("Avancement") or 0))))
        except Exception:
            prog = 0
        raw = str(row.get("Déps") or "")
        cand = [x.strip().upper().replace(" ", "") for x in raw.split(",")]
        SS.tasks.append({
            "id": next_id("T", SS.tasks),
            "title": title,
            "projectId": pid,
            "assigneeId": mid,
            "status": status,
            "priority": prio,
            "start": start,
            "due": due,
            "estimate": est,
            "cost": cost,
            "spent": spent,
            "progress": 100 if status == "Terminé" else prog,
            "deps": [x for x in cand if x and x in task_by_id()],
        })
        changed = True

    for r in sorted([int(x) for x in (ed.get("deleted_rows") or [])],
                    reverse=True):
        if r >= len(ids):
            continue
        tid = ids[r]
        SS.tasks = [t for t in SS.tasks if t["id"] != tid]
        for t in SS.tasks:
            t["deps"] = [x for x in t.get("deps", []) if x != tid]
        changed = True

    if changed:
        sanitize_deps()
        SS.tasks_flash = "✅ Modifications appliquées."
        SS["tasks_editor"] = {}


def _dep_option(t: dict) -> str:
    return f"{t['id']} · {t['title']}"


def _parse_dep_option(v: str) -> str:
    return v.split("·")[0].strip() if v else ""


def view_tasks():
    page_header("🗒️", "Tâches",
                "Base de tâches façon Notion — édition en ligne, dépendances, formulaire.",
                quick=[("📅 Voir le planning →", VIEWS[2]),
                       ("🔗 Chemin critique →", VIEWS[3])])
    flash("tasks_flash")

    SS = st.session_state
    if not SS.projects:
        empty_state("Aucun projet",
                    "Créez d'abord un projet dans l'onglet « Projets ».")
        return

    # ---- filtre projet (pré-rempli par le lien « Tâches de ce projet »)
    proj_labels = ["Tous les projets"] + [f"{p['id']} · {p['name']}"
                                           for p in SS.projects]
    pick = st.selectbox("Projet affiché", proj_labels, key="tf_sel")
    if pick != proj_labels[0]:
        fpid = pick.split("·")[0].strip()
        shown = [t for t in SS.tasks if t["projectId"] == fpid]
    else:
        shown = list(SS.tasks)
    SS["shown_tasks"] = shown

    # ---------------- ajout d'une tâche
    with st.expander("➕ Ajouter une tâche", expanded=(len(SS.tasks) == 0)):
        proj_labels = [f"{p['id']} · {p['name']}" for p in SS.projects]
        pick = st.selectbox("Projet", proj_labels, key="nt_proj")
        pid = pick.split("·")[0].strip()
        others = [t for t in project_tasks(pid)]
        with st.form(key="nt_form"):
            a1, a2 = st.columns(2)
            with a1:
                nt_title = st.text_input("Intitulé *", key="nt_title",
                                         placeholder="Ex. Rédaction du cahier des charges")
                nt_status = st.selectbox("Statut", STATUSES, key="nt_status",
                                         index=1)
                nt_prio = st.selectbox("Priorité", PRIORITIES, key="nt_prio",
                                       index=2)
                nt_cost = st.number_input("Coût prévu (€)", key="nt_cost",
                                         min_value=0.0, value=0.0, step=100.0,
                                         help="Base du COPIL / EVM (BAC du projet).")
            with a2:
                nt_start = st.date_input("Début", key="nt_start", value=TODAY)
                nt_due = st.date_input("Échéance", key="nt_due", value=d(5))
                nt_est = st.number_input("Estimation (h)", key="nt_est",
                                         min_value=0.0, value=8.0, step=1.0)
            nt_prog = st.slider("Avancement (%)", key="nt_prog",
                                min_value=0, max_value=100, value=0, step=10)
            nt_deps = st.multiselect(
                "Dépend de (fin → début)",
                [_dep_option(t) for t in others], key="nt_deps",
                help="Cette tâche ne pourra commencer qu'après la fin des tâches sélectionnées.")
            submit = st.form_submit_button("Ajouter la tâche", type="primary",
                                           key="nt_submit")
        if submit:
            title = (nt_title or "").strip()
            if not title:
                st.error("⚠️ L'intitulé est obligatoire.")
            elif nt_due < nt_start:
                st.error("⚠️ L'échéance doit être postérieure au début.")
            else:
                SS.tasks.append({
                    "id": next_id("T", SS.tasks),
                    "title": title,
                    "projectId": pid,
                    "assigneeId": "",
                    "status": nt_status,
                    "priority": nt_prio,
                    "start": nt_start,
                    "due": nt_due,
                    "estimate": float(nt_est or 0),
                    "cost": float(nt_cost or 0),
                    "spent": 0.0,
                    "progress": 100 if nt_status == "Terminé" else int(nt_prog),
                    "deps": [_parse_dep_option(x) for x in nt_deps],
                })
                sanitize_deps()
                for k in ("nt_title", "nt_est", "nt_prog", "nt_deps", "nt_cost"):
                    SS.pop(k, None)
                SS.tasks_flash = f"✅ Tâche « {title} » ajoutée."
                st.rerun()

    # ---------------- modification d'une tâche
    if shown:
        labels = {t["id"]: f"{t['title']} · {t['id']} · {get_project(t['projectId'])['name'] if get_project(t['projectId']) else '?'}"
                  for t in shown}
        pick = st.selectbox("✏️ Modifier une tâche",
                           [labels[t["id"]] for t in shown], key="mt_pick")
        tid = pick.split("·")[1].strip() if "·" in pick else pick
        t = get_task(tid)
        if t:
            same = [x for x in project_tasks(t["projectId"]) if x["id"] != t["id"]]
            with st.form(key=f"mt_{t['id']}_form"):
                b1, b2 = st.columns(2)
                with b1:
                    m_title = st.text_input("Intitulé", key=f"mtf_{t['id']}_title",
                                            value=t["title"])
                    m_status = st.selectbox("Statut", STATUSES,
                                            key=f"mtf_{t['id']}_status",
                                            index=STATUSES.index(t["status"]))
                    m_prio = st.selectbox("Priorité", PRIORITIES,
                                          key=f"mtf_{t['id']}_prio",
                                          index=PRIORITIES.index(t["priority"]))
                    m_assignee = st.selectbox(
                        "Assigné à",
                        ["— (non assigné)"] + [m["name"] for m in SS.members],
                        key=f"mtf_{t['id']}_assignee",
                        index=0 if not t["assigneeId"]
                        else ([m["name"] for m in SS.members]
                              .index(get_member(t["assigneeId"])["name"]) + 1
                              if get_member(t["assigneeId"]) else 0))
                with b2:
                    m_start = st.date_input("Début", key=f"mtf_{t['id']}_start",
                                            value=t["start"])
                    m_due = st.date_input("Échéance", key=f"mtf_{t['id']}_due",
                                          value=t["due"])
                    m_est = st.number_input("Estimation (h)",
                                            key=f"mtf_{t['id']}_est",
                                            min_value=0.0,
                                            value=float(t["estimate"]), step=1.0)
                    m_cost = st.number_input(
                        "Coût prévu (€)", key=f"mtf_{t['id']}_cost",
                        min_value=0.0, value=float(t.get("cost") or 0),
                        step=100.0)
                    m_spent = st.number_input(
                        "Coût réel (€)", key=f"mtf_{t['id']}_spent",
                        min_value=0.0, value=float(t.get("spent") or 0),
                        step=100.0, help="Déjà dépensé sur la tâche (COPIL).")
                    m_prog = st.slider("Avancement (%)",
                                       key=f"mtf_{t['id']}_prog",
                                       min_value=0, max_value=100,
                                       value=int(t["progress"]), step=10)
                m_deps = st.multiselect(
                    "Dépend de (fin → début)",
                    [_dep_option(x) for x in same],
                    default=[_dep_option(x) for x in same
                             if x["id"] in t.get("deps", [])],
                    key=f"mtf_{t['id']}_deps",
                    help="Dépendances limitées aux tâches du même projet.")
                save = st.form_submit_button("💾 Enregistrer la tâche",
                                             type="primary",
                                             key=f"mtf_{t['id']}_submit")
            if save:
                t["title"] = (m_title or t["title"]).strip()
                t["status"] = m_status
                if m_status == "Terminé":
                    m_prog = 100
                t["priority"] = m_prio
                t["assigneeId"] = ("" if m_assignee.startswith("—")
                                   else next((m["id"] for m in SS.members
                                              if m["name"] == m_assignee), ""))
                t["start"] = m_start
                t["due"] = m_due
                t["estimate"] = float(m_est or 0)
                t["cost"] = float(m_cost or 0)
                t["spent"] = float(m_spent or 0)
                t["progress"] = int(m_prog)
                t["deps"] = [_parse_dep_option(x) for x in m_deps]
                sanitize_deps()
                for k in list(SS.keys()):
                    if k.startswith(f"mtf_{t['id']}_"):
                        SS.pop(k, None)
                SS.tasks_flash = f"✅ Tâche « {t['title']} » mise à jour."
                st.rerun()
            if st.button("🗑️ Supprimer cette tâche", key=f"mt_del_{t['id']}"):
                SS.tasks = [x for x in SS.tasks if x["id"] != t["id"]]
                for x in SS.tasks:
                    x["deps"] = [y for y in x.get("deps", []) if y != t["id"]]
                SS.tasks_flash = f"🗑️ Tâche « {t['title']} » supprimée."
                st.rerun()

    st.divider()

    # ---------------- base de données en ligne
    section("Toutes les tâches — édition en ligne")
    st.caption("Modifiez directement les cellules · ajoutez une ligne en bas · "
               "supprimez avec la colonne ✏️ à droite.")
    pid2name = {p["id"]: p["name"] for p in SS.projects}
    mid2name = {m["id"]: m["name"] for m in SS.members}
    rows = []
    for t in sorted(shown, key=lambda x: (x["projectId"], x["id"])):
        rows.append({
            "ID": t["id"],
            "Tâche": t["title"],
            "Projet": pid2name.get(t["projectId"], "?"),
            "Assigné": mid2name.get(t["assigneeId"], "—"),
            "Statut": t["status"],
            "Priorité": t["priority"],
            "Début": t["start"],
            "Échéance": t["due"],
            "Estim. (h)": t["estimate"],
            "Coût prévu (€)": t.get("cost", 0),
            "Coût réel (€)": t.get("spent", 0),
            "Avancement": t["progress"],
            "Déps": ", ".join(t.get("deps", [])),
        })
    df = pd.DataFrame(rows, columns=[
        "ID", "Tâche", "Projet", "Assigné", "Statut", "Priorité",
        "Début", "Échéance", "Estim. (h)", "Coût prévu (€)",
        "Coût réel (€)", "Avancement", "Déps"])
    SS["tasks_map"] = [t["id"] for t in sorted(
        shown, key=lambda x: (x["projectId"], x["id"]))]

    st.data_editor(
        df,
        key="tasks_editor",
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        on_change=apply_task_edits,
        column_config={
            "ID": st.column_config.Column("ID", disabled=True, width="small"),
            "Tâche": st.column_config.TextColumn("Tâche", width="large"),
            "Projet": st.column_config.SelectColumn(
                "Projet", options=sorted(pid2name.values()), required=True),
            "Assigné": st.column_config.SelectColumn(
                "Assigné", options=sorted(["—"] + list(mid2name.values()))),
            "Statut": st.column_config.SelectColumn(
                "Statut", options=STATUSES, required=True),
            "Priorité": st.column_config.SelectColumn(
                "Priorité", options=PRIORITIES, required=True),
            "Début": st.column_config.DateColumn("Début", format="DD/MM/YYYY"),
            "Échéance": st.column_config.DateColumn("Échéance", format="DD/MM/YYYY"),
            "Estim. (h)": st.column_config.NumberColumn(
                "Estim. (h)", min_value=0, step=1),
            "Coût prévu (€)": st.column_config.NumberColumn(
                "Coût prévu (€)", min_value=0, step=100, format="%.0f €",
                help="Base EVM : budget alloué à la tâche."),
            "Coût réel (€)": st.column_config.NumberColumn(
                "Coût réel (€)", min_value=0, step=100, format="%.0f €",
                help="COPIL : montant déjà dépensé sur la tâche."),
            "Avancement": st.column_config.NumberColumn(
                "Avancement %", min_value=0, max_value=100, step=5, format="%d"),
            "Déps": st.column_config.TextColumn(
                "Déps", help="IDs des prérecesseurs, ex. : T1, T3"),
        })


# ------------------------------------------------------------------ vue : PLANNING


def _gantt_plotly(tasks: list[dict], show_critical: bool, show_connectors: bool):
    by_id = task_by_id()
    ordered = sorted(tasks, key=lambda t: (t["start"], t["id"]))
    n = len(ordered)
    y_of = {t["id"]: n - 1 - i for i, t in enumerate(ordered)}
    labels = [f"{t['title']} · {t['id']}" for t in ordered]

    # CPM par projet pour les tâches affichées
    crit = {}
    for pid in {t["projectId"] for t in ordered}:
        cpm = cpm_analyze(project_tasks(pid))
        if cpm:
            for i in cpm["critical"]:
                crit[i] = cpm["critical"][i]

    fig = go.Figure()

    # week-ends grisés
    lo = min(t["start"] for t in ordered)
    hi = max(t["due"] for t in ordered)
    day = lo
    while day <= hi:
        if day.weekday() == 5:  # samedi
            fig.add_shape(type="rect", x0=ts_ms(day), x1=ts_ms(day + timedelta(days=2)),
                          y0=-0.6, y1=n - 0.4,
                          fillcolor="rgba(148,163,184,0.10)", line_width=0,
                          layer="below")
        day += timedelta(days=1)

    colors, base, width, text = [], [], [], []
    pcolors, pbase, pwidth = [], [], []
    for t in ordered:
        dur_ms = duration_days(t) * 86400000.0
        c = (get_project(t["projectId"]) or {}).get("color", ACCENT)
        if show_critical and crit.get(t["id"]):
            c = "#DC2626"
        colors.append(c)
        base.append(ts_ms(t["start"]))
        width.append(dur_ms)
        text.append(f"{t['title']} ({t['id']}) — {fmt_date(t['start'])} → "
                    f"{fmt_date(t['due'])} · {t['progress']} %")
        pcolors.append(c)
        pbase.append(ts_ms(t["start"]))
        pwidth.append(dur_ms * max(0.0, min(1.0, t["progress"] / 100.0)))

    fig.add_bar(y=list(y_of[t["id"]] for t in ordered), base=base, x=width,
                orientation="h", width=0.62, marker_color=colors,
                marker_opacity=0.40, text=text, hoverinfo="text",
                showlegend=False)
    fig.add_bar(y=list(y_of[t["id"]] for t in ordered), base=pbase, x=pwidth,
                orientation="h", width=0.62, marker_color=pcolors,
                marker_opacity=1.0, showlegend=False, hoverinfo="skip")

    # connecteurs de dépendances
    if show_connectors:
        for t in ordered:
            for dep in t.get("deps", []):
                if dep not in y_of:
                    continue
                p = by_id[dep]
                x1, x2 = ts_ms(p["due"]), ts_ms(t["start"])
                y1, y2 = y_of[dep], y_of[t["id"]]
                colr = "#DC2626" if (crit.get(dep) and crit.get(t["id"])) else "#94A3B8"
                if x2 >= x1:
                    fig.add_shape(type="line", x0=x1, x1=x2, y0=y1, y1=y1,
                                  line=dict(color=colr, width=1.4))
                    fig.add_shape(type="line", x0=x2, x1=x2, y0=y1, y1=y2,
                                  line=dict(color=colr, width=1.4))
                else:
                    fig.add_shape(type="line", x0=x1, x1=x1, y0=y1, y1=y2,
                                  line=dict(color=colr, width=1.4, dash="dot"))
                    fig.add_shape(type="line", x0=x1, x1=x2, y0=y2, y1=y2,
                                  line=dict(color=colr, width=1.4, dash="dot"))

    # ligne aujourd'hui
    fig.add_shape(type="line", x0=ts_ms(TODAY), x1=ts_ms(TODAY),
                  y0=-0.6, y1=n - 0.4,
                  line=dict(color="#4F46E5", width=1.6, dash="dot"))

    fig.update_xaxes(type="date", tickformat="%d %b",
                     rangeslider=dict(visible=True, thickness=0.05),
                     range=[ts_ms(lo - timedelta(days=2)),
                            ts_ms(hi + timedelta(days=2))])
    fig.update_yaxes(tickvals=list(range(n)), ticktext=labels,
                     autorange="reversed", showgrid=True, gridcolor="#EEF0F3")
    fig.update_layout(height=max(320, 42 * n + 130), margin=dict(
        l=10, r=10, t=10, b=10), paper_bgcolor="white",
        plot_bgcolor="white", bargap=0.25)
    st.plotly_chart(fig, use_container_width=True)


def _gantt_altair(tasks: list[dict]):
    rows = []
    for t in sorted(tasks, key=lambda x: (x["start"], x["id"])):
        rows.append({
            "label": f"{t['title']} · {t['id']}",
            "start": str(t["start"]),
            "due": str(t["due"] + timedelta(days=1)),
            "project": (get_project(t["projectId"]) or {}).get("name", "?"),
            "color": (get_project(t["projectId"]) or {}).get("color", ACCENT),
        })
    df = pd.DataFrame(rows)
    order = df["label"].tolist()
    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=4, height=16).encode(
        x=alt.X("start:T", title=None),
        x2=alt.X2("due:T"),
        y=alt.Y("label:N", sort=order, title=None),
        color=alt.Color("project:N", legend=alt.Legend(title="Projet")),
        tooltip=["label", "project"],
    )
    today = alt.Chart(pd.DataFrame({"d": [str(TODAY)]})).mark_rule(
        color="#4F46E5", strokeDash=[4, 4]).encode(x="d:T")
    st.altair_chart((bars + today).interactive(), use_container_width=True)


def view_planning():
    page_header("📅", "Planning",
                "Gantt façon MS Project — dépendances, chemin critique, week-ends, zoom.",
                quick=[("🔗 Chemin critique →", VIEWS[3]),
                       ("📊 COPIL (EVM) →", VIEWS[5])])
    flash("planning_flash")

    SS = st.session_state
    if not SS.tasks:
        empty_state("Aucune tâche à afficher",
                    "Ajoutez des tâches dans l'onglet « Tâches ».")
        return

    # filtres
    f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
    with f1:
        proj_opts = ["Tous les projets"] + [f"{p['id']} · {p['name']}"
                                            for p in SS.projects]
        fpick = st.selectbox("Projet", proj_opts, key="pl_proj")
    with f2:
        mem_opts = ["Tous les assignés", "(non assigné)"] + \
                   [m["name"] for m in SS.members]
        mpick = st.selectbox("Assigné", mem_opts, key="pl_member")
    with f3:
        show_crit = st.checkbox("Tâches critiques en rouge", value=True,
                                key="pl_crit")
    with f4:
        show_conn = st.checkbox("Connecteurs", value=True, key="pl_conn")

    if fpick != proj_opts[0]:
        pid = fpick.split("·")[0].strip()
        sel = [t for t in SS.tasks if t["projectId"] == pid]
    else:
        sel = list(SS.tasks)
    if mpick == "(non assigné)":
        sel = [t for t in sel if not t["assigneeId"]]
    elif mpick != mem_opts[0]:
        m = next((x for x in SS.members if x["name"] == mpick), None)
        sel = [t for t in sel if m and t["assigneeId"] == m["id"]]

    if st.button("↻ Réaligner les dates sur les dépendances", key="pl_resched"):
        moved = []
        for p in SS.projects:
            moved += reschedule_project(p["id"])
        if moved:
            SS.planning_flash = (f"↻ {len(moved)} tâche(s) décalée(s) : "
                                  + ", ".join(sorted(moved)))
        else:
            SS.planning_flash = "✅ Toutes les tâches sont déjà alignées."
        st.rerun()

    if not sel:
        empty_state("Aucune tâche ne correspond aux filtres.",
                    "Modifiez le projet ou l'assigné sélectionné.")
        return

    # légende
    legend = ""
    for p in SS.projects:
        if any(t["projectId"] == p["id"] for t in sel):
            legend += (f'<span style="margin-right:14px;font-size:12.5px;'
                       f'color:#374151;"><span class="pp-legend-dot" '
                       f'style="background:{esc(p["color"])};"></span>'
                       f'{esc(p["name"])}</span>')
    legend += ('<span style="font-size:12.5px;color:#374151;">'
               '<span class="pp-legend-dot" style="background:#DC2626;"></span>'
               'Chemin critique</span>')
    st.markdown(f'<div style="margin:6px 0 2px 0;">{legend}</div>',
                unsafe_allow_html=True)

    if PLOTLY:
        _gantt_plotly(sel, show_crit, show_conn)
    elif ALTAIR:
        st.caption("ℹ️ Graphique simplifié — installez Plotly pour les "
                   "connecteurs et le chemin critique : pip install plotly")
        _gantt_altair(sel)
    else:
        st.info("Installez plotly ou altair pour afficher le Gantt : "
                "pip install plotly")

    nb_crit = 0
    for pid in {t["projectId"] for t in sel}:
        cpm = cpm_analyze(project_tasks(pid))
        if cpm:
            nb_crit += sum(1 for i in cpm["critical"] if cpm["critical"][i]
                           and i in {t["id"] for t in sel})
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Tâches affichées", len(sel))
    with c2:
        st.metric("Critiques", nb_crit)
    with c3:
        st.metric("Retards", sum(1 for t in sel
                                 if t["due"] < TODAY and t["status"] != "Terminé"))


# ------------------------------------------------------------------ vue : CHEMIN CRITIQUE


def view_critical():
    page_header("🔗", "Chemin critique",
                "Méthode du chemin critique (CPM) — marges, enchaînement, verdict.",
                quick=[("📅 Voir le planning →", VIEWS[2]),
                       ("🗒️ Voir les tâches →", VIEWS[1]),
                       ("📊 COPIL (EVM) →", VIEWS[5])])
    flash("critical_flash")

    SS = st.session_state
    if not SS.projects:
        empty_state("Aucun projet", "Créez un projet pour lancer l'analyse CPM.")
        return
    if not SS.tasks:
        empty_state("Aucune tâche", "Ajoutez des tâches avec des dépendances "
                    "pour calculer le chemin critique.")
        return

    st.caption("💡 **Marge** = nombre de jours de retard possibles sans décaler "
               "la fin du projet. Une tâche à **marge 0** est **critique** : "
               "tout retard la repousse directement sur l'échéance.")

    for p in SS.projects:
        p_tasks = project_tasks(p["id"])
        if not p_tasks:
            continue
        st.markdown(
            f'<div class="pp-card" style="border-left:4px solid {esc(p["color"])};">'
            f'<div class="pp-title">{esc(p["name"])} <span class="pp-muted">· {esc(p["id"])}</span></div>'
            f'<div class="pp-sub">{len(p_tasks)} tâche(s)</div></div>',
            unsafe_allow_html=True)

        cpm = cpm_analyze(p_tasks)
        if cpm is None:
            st.error("⛔ Dépendances circulaires détectées : l'analyse est "
                     "impossible. Vérifiez les dépendances dans l'onglet Tâches.")
            continue

        by_id = {t["id"]: t for t in p_tasks}
        rows = []
        for i in cpm["order"]:
            t = by_id[i]
            rows.append({
                "ID": i,
                "Tâche": t["title"],
                "Début + tôt": fmt_date(cpm["es"][i]),
                "Fin + tôt": fmt_date(cpm["ef"][i]),
                "Début + tard": fmt_date(cpm["ls"][i]),
                "Fin + tard": fmt_date(cpm["lf"][i]),
                "Marge (j)": cpm["slack"][i],
                "Critique": "🔴 oui" if cpm["critical"][i] else "non",
                "Avancement": f"{t['progress']} %",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        # chaîne critique
        chain = critical_chain(p_tasks, cpm)
        if chain:
            parts = []
            for i in chain:
                parts.append(
                    f'<span class="pp-chip" style="background:#FEE2E2;color:#B91C1C;">'
                    f'🔴 {esc(by_id[i]["title"])} ({esc(i)})</span>')
            parts_html = '<span class="pp-chain-arrow">→</span>'.join(parts)
            st.markdown(
                f'<div style="margin:8px 0 4px 0;">'
                f'<span class="pp-sub">Chaîne critique :</span><br>{parts_html}</div>',
                unsafe_allow_html=True)
        else:
            st.markdown('<span class="pp-sub">Aucune tâche critique isolée.</span>',
                        unsafe_allow_html=True)

        # verdict
        end = cpm["project_end"]
        dl = p.get("deadline")
        if dl:
            delta = (dl - end).days
            if delta >= 0:
                verdict = (f'✅ Fin théorique le {fmt_date(end)} — '
                           f'<b>{delta} jour(s) avant</b> l\'échéance '
                           f'({fmt_date(dl)}).')
                bg, fg = "#ECFDF5", "#047857"
            else:
                verdict = (f'🔴 Fin théorique le {fmt_date(end)} — '
                           f'<b>{-delta} jour(s) de retard</b> sur l\'échéance '
                           f'({fmt_date(dl)}).')
                bg, fg = "#FEF2F2", "#B91C1C"
            st.markdown(f'<div class="pp-verdict" style="background:{bg};color:{fg};">'
                        f'{verdict}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="pp-verdict" style="background:#EEF2FF;'
                        f'color:#4338CA;">Fin théorique du projet : '
                        f'{fmt_date(end)}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------ vue : RESSOURCES


def apply_member_edits():
    SS = st.session_state
    ed = SS.get("members_editor") or {}
    ids = SS.get("members_map") or []
    changed = False
    for r, changes in (ed.get("edited_rows") or {}).items():
        r = int(r)
        if r >= len(ids):
            continue
        m = next((x for x in SS.members if x["id"] == ids[r]), None)
        if m is None or not changes:
            continue
        changed = True
        if "Nom" in changes:
            m["name"] = str(changes["Nom"]).strip() or m["name"]
        if "Rôle" in changes:
            m["role"] = str(changes["Rôle"]).strip()
        if "Capacité (h/mois)" in changes:
            try:
                m["capacity"] = max(1.0, float(changes["Capacité (h/mois)"]))
            except Exception:
                pass
        if "Couleur" in changes:
            m["color"] = str(changes["Couleur"]) or m["color"]
    for row in (ed.get("added_rows") or []):
        row = row or {}
        name = str(row.get("Nom") or "").strip() or "Nouveau membre"
        try:
            cap = max(1.0, float(row.get("Capacité (h/mois)") or MONTHLY_MAX_H))
        except Exception:
            cap = float(MONTHLY_MAX_H)
        SS.members.append({
            "id": next_id("M", SS.members),
            "name": name,
            "role": str(row.get("Rôle") or "").strip(),
            "capacity": cap,
            "color": str(row.get("Couleur") or
                         DEFAULT_COLORS[len(SS.members) % len(DEFAULT_COLORS)]),
        })
        changed = True
    for r in sorted([int(x) for x in (ed.get("deleted_rows") or [])],
                    reverse=True):
        if r >= len(ids):
            continue
        mid = ids[r]
        SS.members = [x for x in SS.members if x["id"] != mid]
        for t in SS.tasks:
            if t["assigneeId"] == mid:
                t["assigneeId"] = ""
        changed = True
    if changed:
        SS.team_flash = "✅ Équipe mise à jour."
        SS["members_editor"] = {}


def view_team():
    page_header("👥", "Ressources",
                "Équipe, capacité mensuelle et taux de charge par personne.",
                quick=[("🗒️ Voir les tâches →", VIEWS[1])])
    flash("team_flash")

    SS = st.session_state

    # --- édition de l'équipe
    with st.expander("🧑‍💼 Gérer l'équipe", expanded=(len(SS.members) == 0)):
        rows = [{"ID": m["id"], "Nom": m["name"], "Rôle": m["role"],
                 "Capacité (h/mois)": m["capacity"], "Couleur": m["color"]}
                for m in SS.members]
        df = pd.DataFrame(rows, columns=["ID", "Nom", "Rôle",
                                         "Capacité (h/mois)", "Couleur"])
        SS["members_map"] = [m["id"] for m in SS.members]
        st.data_editor(
            df, key="members_editor", num_rows="dynamic", hide_index=True,
            use_container_width=True, on_change=apply_member_edits,
            column_config={
                "ID": st.column_config.Column("ID", disabled=True, width="small"),
                "Nom": st.column_config.TextColumn("Nom", width="medium"),
                "Rôle": st.column_config.TextColumn("Rôle", width="medium"),
                "Capacité (h/mois)": st.column_config.NumberColumn(
                    "Capacité (h/mois)", min_value=1, step=10,
                    default=MONTHLY_MAX_H),
                "Couleur": st.column_config.TextColumn(
                    "Couleur", help="Code hexadécimal, ex. : #4F46E5"),
            })
        st.caption(f"💡 Capacité par défaut : {MONTHLY_MAX_H} h/mois. "
                   "Ajoutez des lignes directement dans le tableau.")

    if not SS.members:
        empty_state("Aucun membre dans l'équipe",
                    "Ajoutez vos collègues dans le tableau ci-dessus.")
        return

    # --- charge par personne
    section("Taux de charge")
    st.caption("Heures estimées des tâches non terminées, comparées à la capacité mensuelle.")

    total_charge, total_cap = 0.0, 0.0
    cards = []
    for m in SS.members:
        assigned = [t for t in SS.tasks
                    if t["assigneeId"] == m["id"] and t["status"] != "Terminé"]
        charge = sum(float(t["estimate"] or 0) for t in assigned)
        cap = float(m["capacity"] or MONTHLY_MAX_H)
        rate = 100 * charge / cap if cap else 0
        if rate < 70:
            bg, fg = "#ECFDF5", "#047857"
        elif rate <= 100:
            bg, fg = "#FFFBEB", "#B45309"
        else:
            bg, fg = "#FEF2F2", "#B91C1C"
        color = m["color"]

        per_project = {}
        for t in assigned:
            pname = (get_project(t["projectId"]) or {}).get("name", "?")
            per_project[pname] = per_project.get(pname, 0.0) + float(t["estimate"] or 0)
        chips_html = "".join(
            chip(f"{esc(k)} : {v:g} h", "#F1F5F9", "#475569")
            for k, v in per_project.items() if v > 0)

        cards.append(
            f"""<div class="pp-card" style="border-left:4px solid {esc(color)};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <div>
                <div class="pp-title" style="font-size:15px;">{esc(m['name'])}
                  <span class="pp-muted">· {esc(m['id'])}</span></div>
                <div class="pp-sub">{esc(m['role']) or '—'}</div>
              </div>
              <div style="text-align:right;">
                <span class="pp-chip" style="background:{bg};color:{fg};">
                  {rate:.0f} % de charge</span>
                <div class="pp-sub">{charge:g} h / {cap:g} h</div>
              </div>
            </div>
            {bar_html(rate, esc(color))}
            <div style="margin-top:6px;">{chips_html}</div>
            </div>""")
        total_charge += charge
        total_cap += cap

    st.markdown("".join(cards), unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Membres", len(SS.members))
    with c2:
        st.metric("Charge totale", f"{total_charge:g} h")
    with c3:
        st.metric("Capacité totale", f"{total_cap:g} h")


# ------------------------------------------------------------------ vue : COPIL (EVM)


def _scurve_plotly(dates, pv_s, ev_s, ac_s, bac):
    """Courbe en S : PV planifié (pointillé) vs EV valorisé vs AC dépensé."""
    fig = go.Figure()
    xs = [str(x) for x in dates]
    fig.add_scatter(x=xs, y=pv_s, name="PV · planifié", mode="lines",
                    line=dict(color="#94A3B8", width=2, dash="dash"))
    fig.add_scatter(x=xs, y=ev_s, name="EV · valorisé", mode="lines",
                    line=dict(color="#2563EB", width=2.8))
    fig.add_scatter(x=xs, y=ac_s, name="AC · dépensé", mode="lines",
                    line=dict(color="#F59E0B", width=2.8))
    fig.add_hline(y=bac, line=dict(color="#1E293B", width=1.2, dash="dot"),
                  annotation_text=f"BAC · {fmt_money(bac)}",
                  annotation_position="top left",
                  annotation_font=dict(size=11, color="#475569"))
    fig.add_vline(x=str(TODAY), line=dict(color="#DC2626", width=1.4, dash="dot"))
    fig.update_xaxes(type="date", tickformat="%d %b", showgrid=True,
                     gridcolor="#EEF0F3")
    fig.update_yaxes(title="Coût cumulé (€)", showgrid=True, gridcolor="#EEF0F3")
    fig.update_layout(
        height=430, margin=dict(l=10, r=10, t=34, b=10),
        paper_bgcolor="white", plot_bgcolor="white",
        hovermode="x unified", legend=dict(orientation="h", y=1.06,
                                           x=0, font=dict(size=11)))
    st.plotly_chart(fig, use_container_width=True)


def _scurve_altair(dates, pv_s, ev_s, ac_s):
    rows = [{"date": str(dd), "PV · planifié": pv, "EV · valorisé": ev,
             "AC · dépensé": ac}
            for dd, pv, ev, ac in zip(dates, pv_s, ev_s, ac_s)]
    df = pd.DataFrame(rows).melt("date", var_name="Série", value_name="Coût")
    chart = alt.Chart(df).mark_line().encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("Coût:Q"),
        color=alt.Color("Série:N", scale=alt.Scale(
            domain=["PV · planifié", "EV · valorisé", "AC · dépensé"],
            range=["#94A3B8", "#2563EB", "#F59E0B"])),
    )
    st.altair_chart(chart.interactive(), use_container_width=True)


def view_copil():
    page_header("📊", "COPIL (EVM)",
                "Earned Value Management — SPI, CPI, EAC, VAC et courbe en S.",
                quick=[("📅 Voir le planning →", VIEWS[2]),
                       ("🗒️ Voir les tâches →", VIEWS[1]),
                       ("📁 Voir les projets →", VIEWS[0])])
    flash("copil_flash")

    SS = st.session_state
    if not SS.tasks:
        empty_state("Aucune tâche à piloter",
                    "Créez un projet puis des tâches (onglets Projets / Tâches).")
        return

    # ---- filtre projet (pré-rempli par le lien « COPIL de ce projet »)
    proj_labels = ["Tous les projets"] + [f"{p['id']} · {p['name']}"
                                          for p in SS.projects]
    pick = st.selectbox("Projet piloté", proj_labels, key="evm_sel")
    if pick != proj_labels[0]:
        fpid = pick.split("·")[0].strip()
        sel = [t for t in SS.tasks if t["projectId"] == fpid]
        p = get_project(fpid)
        budget_ref = float(p["budget"]) if p else None
    else:
        sel = list(SS.tasks)
        budget_ref = None

    evm = evm_analyze(sel)
    if evm is None:
        empty_state("Pas encore de coûts à piloter",
                    "Renseignez la colonne « Coût prévu (€) » des tâches "
                    "(onglet Tâches) pour activer le COPIL.")
        if st.button("🗒️ Ouvrir les tâches →", key="evm_go_tasks"):
            goto(VIEWS[1])
        return

    k = evm["kpis"]
    dates, pv_s, ev_s, ac_s = evm["series"]

    # ---- verdict délai + budget
    if k["spi"] is None:
        sched_html = ('<div class="pp-verdict" style="background:#F8FAFC;'
                      'color:#475569;">⏸️ Planning non mesurable '
                      '(aucune fenêtre de tâche atteinte aujourd\'hui).</div>')
    elif k["spi"] >= 1.0:
        sched_html = (f'<div class="pp-verdict" style="background:#ECFDF5;'
                      f'color:#065F46;">🟢 En avance sur le planning — '
                      f'SPI {k["spi"]:.2f} · avance de '
                      f'{fmt_money(k["sv"])}</div>')
    else:
        sched_html = (f'<div class="pp-verdict" style="background:#FEF2F2;'
                      f'color:#991B1B;">🔴 En retard sur le planning — '
                      f'SPI {k["spi"]:.2f} · retard de '
                      f'{fmt_money(abs(k["sv"]))}</div>')
    if k["cpi"] is None:
        cost_html = ('<div class="pp-verdict" style="background:#F8FAFC;'
                     'color:#475569;">⏸️ Budget non mesurable '
                     '(aucun coût réel saisi).</div>')
    elif k["cpi"] >= 1.0:
        cost_html = (f'<div class="pp-verdict" style="background:#ECFDF5;'
                     f'color:#065F46;">🟢 Sous le budget — CPI '
                     f'{k["cpi"]:.2f} · économie de '
                     f'{fmt_money(abs(k["cv"]))}</div>')
    else:
        cost_html = (f'<div class="pp-verdict" style="background:#FEF2F2;'
                     f'color:#991B1B;">🔴 Dépassement du budget — CPI '
                     f'{k["cpi"]:.2f} · dépassement de '
                     f'{fmt_money(abs(k["cv"]))}</div>')
    st.markdown(sched_html + cost_html, unsafe_allow_html=True)

    if budget_ref is not None and abs(budget_ref - k["bac"]) > 0.01:
        st.info(f"💡 Budget projet : {fmt_money(budget_ref)} · coûts prévus "
                f"des tâches : {fmt_money(k['bac'])}. "
                f"Ajustez le budget ou les coûts des tâches pour aligner le BAC.")

    # ---- KPI EVM
    section("Indicateurs aujourd'hui")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("BAC — budget", fmt_money(k["bac"]),
                  help="Budget à l'achèvement : somme des coûts prévus.")
    with c2:
        st.metric("PV — planifié", fmt_money(k["pv"]),
                  help="Valeur du travail qui aurait dû être faite à ce jour.")
    with c3:
        st.metric("EV — valorisé", fmt_money(k["ev"]),
                  delta=fmt_money(k["sv"]) if k["sv"] else None,
                  delta_color="normal",
                  help="Valeur du réellement accompli (coût × avancement).")
    with c4:
        st.metric("AC — dépensé", fmt_money(k["ac"]),
                  help="Coûts réels engagés à ce jour.")
    c5, c6, c7, c8 = st.columns(4)
    with c5:
        st.metric("SPI — planning", f"{k['spi']:.2f}" if k["spi"] is not None else "—",
                  help="EV / PV · > 1 = en avance, < 1 = en retard.")
    with c6:
        st.metric("CPI — coûts", f"{k['cpi']:.2f}" if k["cpi"] is not None else "—",
                  help="EV / AC · > 1 = sous le budget, < 1 = dépassement.")
    with c7:
        st.metric("EAC — prévision", fmt_money(k["eac"]) if k["eac"] else "—",
                  help="Coût total prévisionnel à l'achèvement : BAC / CPI.")
    with c8:
        st.metric("VAC — marge", fmt_money(k["vac"]) if k["vac"] is not None else "—",
                  help="BAC − EAC · positif = marge budgétaire restante.")
    if k["tcpi"] is not None:
        st.caption(f"🎯 TCPI {k['tcpi']:.2f} — efficacité nécessaire sur le "
                   "reste du projet pour tenir le budget (1,0 = juste).")

    # ---- courbe en S
    section("Courbe en S — coûts cumulés")
    st.caption("PV = planifié (pointillé) · EV = valorisé (bleu) · "
               "AC = dépensé (orange) · point rouge vertical = aujourd'hui.")
    if PLOTLY:
        _scurve_plotly(dates, pv_s, ev_s, ac_s, k["bac"])
    elif ALTAIR:
        st.caption("ℹ️ Graphique simplifié — installez Plotly pour la ligne "
                   "BAC et la marque « aujourd'hui » : pip install plotly")
        _scurve_altair(dates, pv_s, ev_s, ac_s)
    else:
        st.info("Installez plotly ou altair pour afficher la courbe en S : "
                "pip install plotly")

    # ---- détail par tâche
    section("Détail par tâche")
    st.caption("Coût prévu, dépensé et valeur acquise (coût × avancement).")
    det_rows = []
    for r in sorted(evm["rows"], key=lambda x: x["id"]):
        t = get_task(r["id"]) or {}
        det_rows.append({
            "ID": r["id"],
            "Tâche": r["title"],
            "Projet": (get_project(t.get("projectId", "")) or {}).get("name", "?"),
            "Coût prévu (€)": round(r["cost"]),
            "Dépensé (€)": round(r["spent"]),
            "Avancement (%)": r["progress"],
            "Valeur acquise (€)": round(r["cost"] * r["progress"] / 100),
        })
    st.dataframe(pd.DataFrame(det_rows), use_container_width=True,
                 hide_index=True)

    tot_cost = sum(r["cost"] for r in evm["rows"])
    tot_spent = sum(r["spent"] for r in evm["rows"])
    cA, cB, cC = st.columns(3)
    with cA:
        st.metric("Coûts prévus", fmt_money(tot_cost))
    with cB:
        st.metric("Dépensé à ce jour", fmt_money(tot_spent))
    with cC:
        st.metric("Reste à dépenser",
                  fmt_money(max(0.0, k["eac"] - k["ac"]))
                  if k["eac"] else "—")


# ------------------------------------------------------------------ navigation


def main():
    init_state()
    inject_design()

    with st.sidebar:
        st.markdown(
            """<div style="display:flex;gap:10px;align-items:center;padding:4px 4px 14px 4px;">
            <div class="pp-logo">P</div>
            <div><div style="font-weight:800;font-size:15px;color:#1E293B;">PilotPro</div>
            <div style="font-size:11px;color:#64748B;">Notion × MS Project</div></div>
            </div>""",
            unsafe_allow_html=True)
        st.caption(f"📅 Aujourd'hui : {fmt_date(TODAY)}\n\n"
                   f"📁 {len(st.session_state.projects)} projet(s) · "
                   f"🗒️ {len(st.session_state.tasks)} tâche(s) · "
                   f"👥 {len(st.session_state.members)} membre(s)")
        st.divider()
        st.caption("🧭 Naviguez avec les **onglets en haut de page**.\n\n"
                   "💡 Des liens rapides en haut de chaque vue relient "
                   "les 6 onglets entre eux.\n\n"
                   "Les données sont conservées pendant la session.")

    # ---- onglets principaux (visibles et persistants en haut de page) ----
    st.radio("Navigation", VIEWS, key="nav", horizontal=True,
             label_visibility="collapsed")
    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)

    view = st.session_state.get("nav", VIEWS[0])
    st.session_state["view"] = view
    if view == VIEWS[0]:
        view_projects()
    elif view == VIEWS[1]:
        view_tasks()
    elif view == VIEWS[2]:
        view_planning()
    elif view == VIEWS[3]:
        view_critical()
    elif view == VIEWS[4]:
        view_team()
    elif view == VIEWS[5]:
        view_copil()


if __name__ == "__main__":
    main()