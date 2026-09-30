"""
🚀 PilotPro — Le logiciel du chef de projet ultime (version Python / Streamlit)

Tableau de bord · Kanban · Tâches · Planning · Équipe · Budget & EVM · Rapports
Thème clair moderne, suivi EVM complet (PV, EV, AC, CPI, SPI, EAC, VAC, TCPI),
courbes en S cumulées, cases à cocher par projet.

Installation et lancement :
    pip install streamlit pandas
    streamlit run pilotpro.py

Plotly est OPTIONNEL : s'il est absent (ex. Streamlit Cloud sans requirements.txt),
l'application bascule automatiquement sur les graphiques natifs Streamlit/Altair.
Pour les graphiques interactifs complets : ajoutez « plotly » dans requirements.txt.
"""

import json
import uuid
from datetime import date, timedelta

import pandas as pd
import streamlit as st

try:
    import plotly.express as px
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# ==================================================================
# CONFIGURATION
# ==================================================================

st.set_page_config(page_title="PilotPro", page_icon="🚀", layout="wide")

TODAY = date.today()


def d(offset: int) -> date:
    """Date relative à aujourd'hui (offset en jours)."""
    return TODAY + timedelta(days=offset)


def fmt_d(dt: date) -> str:
    return dt.strftime("%d %b")


def fmt_k(v: float) -> str:
    return f"{round(v / 1000):,}".replace(",", " ") + " k€"


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ==================================================================
# DONNÉES DE DÉMO
# ==================================================================

MEMBERS = [
    {"id": "m1", "name": "Thibault D'Halluin", "role": "Product Owner", "initials": "TD", "color": "#818cf8", "capacity": 30},
    {"id": "m2", "name": "Amélie Laurent", "role": "Cheffe de projet", "initials": "AL", "color": "#f472b6", "capacity": 35},
    {"id": "m3", "name": "Karim Benali", "role": "Dev Lead", "initials": "KB", "color": "#34d399", "capacity": 40},
    {"id": "m4", "name": "Sofia Moreau", "role": "UX Designer", "initials": "SM", "color": "#fbbf24", "capacity": 32},
    {"id": "m5", "name": "Léa Dubois", "role": "QA / Tests", "initials": "LD", "color": "#22d3ee", "capacity": 30},
    {"id": "m6", "name": "Marc Petit", "role": "Dev Full-stack", "initials": "MP", "color": "#f87171", "capacity": 40},
]

PROJECTS = [
    {"id": "p1", "name": "Refonte site vitrine", "client": "Groupe Vallon", "color": "#818cf8", "deadline": d(21), "bac": 120000, "costFactor": 1.05},
    {"id": "p2", "name": "App mobile fidélité", "client": "NovaRetail", "color": "#34d399", "deadline": d(45), "bac": 250000, "costFactor": 0.94},
    {"id": "p3", "name": "Migration ERP", "client": "Interne", "color": "#fbbf24", "deadline": d(60), "bac": 400000, "costFactor": 1.15},
    {"id": "p4", "name": "Portail client B2B", "client": "TechniPro", "color": "#22d3ee", "deadline": d(14), "bac": 180000, "costFactor": 1.02},
    {"id": "p5", "name": "Refonte intranet RH", "client": "Interne", "color": "#f472b6", "deadline": d(35), "bac": 150000, "costFactor": 1.08},
]

STATUSES = [
    {"id": "backlog", "label": "Backlog", "color": "#94a3b8"},
    {"id": "todo", "label": "À faire", "color": "#38bdf8"},
    {"id": "doing", "label": "En cours", "color": "#a78bfa"},
    {"id": "review", "label": "En revue", "color": "#fbbf24"},
    {"id": "done", "label": "Terminé", "color": "#34d399"},
]

PRIORITIES = [
    {"id": "critique", "label": "Critique", "color": "#f87171"},
    {"id": "haute", "label": "Haute", "color": "#fb923c"},
    {"id": "moyenne", "label": "Moyenne", "color": "#fbbf24"},
    {"id": "basse", "label": "Basse", "color": "#94a3b8"},
]

HEALTH = {
    "ok": ("🟢 Sain", "#10b981"),
    "warn": ("🟠 Vigilance", "#f59e0b"),
    "bad": ("🔴 Critique", "#ef4444"),
}

DEMO_TASKS = [
    {"id": "t1", "title": "Atelier cadrage avec le client", "projectId": "p1", "assigneeId": "m2", "status": "done", "priority": "haute", "due": d(-8), "start": d(-12), "estimate": 6, "progress": 100},
    {"id": "t2", "title": "Wireframes page d'accueil", "projectId": "p1", "assigneeId": "m4", "status": "done", "priority": "haute", "due": d(-5), "start": d(-11), "estimate": 10, "progress": 100},
    {"id": "t3", "title": "Maquettes haute fidélité", "projectId": "p1", "assigneeId": "m4", "status": "review", "priority": "haute", "due": d(1), "start": d(-4), "estimate": 12, "progress": 90},
    {"id": "t4", "title": "Intégration header + navigation", "projectId": "p1", "assigneeId": "m6", "status": "doing", "priority": "moyenne", "due": d(4), "start": d(-2), "estimate": 8, "progress": 55},
    {"id": "t5", "title": "SEO : audit mots-clés", "projectId": "p1", "assigneeId": "m1", "status": "todo", "priority": "basse", "due": d(9), "start": d(3), "estimate": 5, "progress": 0},
    {"id": "t6", "title": "Cahier des charges fonctionnel", "projectId": "p2", "assigneeId": "m1", "status": "done", "priority": "critique", "due": d(-10), "start": d(-15), "estimate": 8, "progress": 100},
    {"id": "t7", "title": "Architecture API backend", "projectId": "p2", "assigneeId": "m3", "status": "doing", "priority": "critique", "due": d(3), "start": d(-6), "estimate": 16, "progress": 60},
    {"id": "t8", "title": "Écrans onboarding mobile", "projectId": "p2", "assigneeId": "m4", "status": "todo", "priority": "haute", "due": d(7), "start": d(-3), "estimate": 14, "progress": 10},
    {"id": "t9", "title": "Système de points fidélité", "projectId": "p2", "assigneeId": "m3", "status": "backlog", "priority": "moyenne", "due": d(18), "start": d(10), "estimate": 20, "progress": 0},
    {"id": "t10", "title": "Plan de tests UAT", "projectId": "p2", "assigneeId": "m5", "status": "backlog", "priority": "moyenne", "due": d(20), "start": d(12), "estimate": 8, "progress": 0},
    {"id": "t11", "title": "Cartographie des données ERP", "projectId": "p3", "assigneeId": "m3", "status": "doing", "priority": "critique", "due": d(-1), "start": d(-9), "estimate": 18, "progress": 75},
    {"id": "t12", "title": "Choix solution ERP (3 devis)", "projectId": "p3", "assigneeId": "m2", "status": "review", "priority": "haute", "due": d(-2), "start": d(-14), "estimate": 10, "progress": 95},
    {"id": "t13", "title": "Formation des équipes clés", "projectId": "p3", "assigneeId": "m2", "status": "todo", "priority": "moyenne", "due": d(25), "start": d(15), "estimate": 12, "progress": 0},
    {"id": "t14", "title": "Plan de reprise des données", "projectId": "p3", "assigneeId": "m6", "status": "backlog", "priority": "haute", "due": d(30), "start": d(18), "estimate": 16, "progress": 0},
    {"id": "t15", "title": "Authentification SSO", "projectId": "p4", "assigneeId": "m6", "status": "doing", "priority": "critique", "due": d(0), "start": d(-7), "estimate": 12, "progress": 70},
    {"id": "t16", "title": "Tableau de bord commandes", "projectId": "p4", "assigneeId": "m3", "status": "todo", "priority": "haute", "due": d(6), "start": d(1), "estimate": 14, "progress": 0},
    {"id": "t17", "title": "Recette fonctionnelle v1", "projectId": "p4", "assigneeId": "m5", "status": "todo", "priority": "haute", "due": d(10), "start": d(5), "estimate": 10, "progress": 0},
    {"id": "t18", "title": "Revue sécurité & RGPD", "projectId": "p4", "assigneeId": "m5", "status": "backlog", "priority": "moyenne", "due": d(12), "start": d(6), "estimate": 6, "progress": 0},
    {"id": "t19", "title": "Rédaction guide utilisateur", "projectId": "p4", "assigneeId": "m1", "status": "backlog", "priority": "basse", "due": d(16), "start": d(9), "estimate": 8, "progress": 0},
    {"id": "t20", "title": "Correction bugs remontés en recette", "projectId": "p1", "assigneeId": "m6", "status": "review", "priority": "haute", "due": d(-3), "start": d(-8), "estimate": 7, "progress": 85},
    {"id": "t21", "title": "Audit de l'intranet existant", "projectId": "p5", "assigneeId": "m2", "status": "done", "priority": "haute", "due": d(-6), "start": d(-20), "estimate": 10, "progress": 100},
    {"id": "t22", "title": "Charte graphique & design système", "projectId": "p5", "assigneeId": "m4", "status": "doing", "priority": "haute", "due": d(5), "start": d(-4), "estimate": 12, "progress": 45},
    {"id": "t23", "title": "Portail RH self-service", "projectId": "p5", "assigneeId": "m6", "status": "todo", "priority": "critique", "due": d(18), "start": d(8), "estimate": 20, "progress": 0},
    {"id": "t24", "title": "Reprise des données congés & frais", "projectId": "p5", "assigneeId": "m3", "status": "backlog", "priority": "moyenne", "due": d(28), "start": d(14), "estimate": 10, "progress": 0},
]

STATUS_IDS = [s["id"] for s in STATUSES]
PRIO_IDS = [p["id"] for p in PRIORITIES]


def get_member(mid):
    return next(m for m in MEMBERS if m["id"] == mid)


def get_project(pid):
    return next(p for p in PROJECTS if p["id"] == pid)


def status_of(t):
    return next(s for s in STATUSES if s["id"] == t["status"])


def prio_of(t):
    return next(p for p in PRIORITIES if p["id"] == t["priority"])


def is_late(t):
    return t["status"] != "done" and t["due"] < TODAY


# ==================================================================
# EVM — EARNED VALUE MANAGEMENT
# ==================================================================

def span_days(t):
    return max(1, (t["due"] - t["start"]).days)


def planned_frac(t, day):
    """Fraction de la tâche qui devait être livrée à `day` selon le planning."""
    return clamp01((day - t["start"]).days / span_days(t))


def earned_now(t):
    """Fraction réellement acquise à ce jour."""
    return 1.0 if t["status"] == "done" else t["progress"] / 100


def earned_frac_at(t, day):
    """Fraction acquise à `day` (reconstituée linéairement jusqu'à ce jour)."""
    if day > TODAY:
        return 0.0
    if t["status"] == "done":
        return clamp01((day - t["start"]).days / span_days(t))
    elapsed = max(1, (TODAY - t["start"]).days)
    return t["progress"] / 100 * clamp01((day - t["start"]).days / elapsed)


def evm_metrics(pid, tasks):
    p = get_project(pid)
    ts = [t for t in tasks if t["projectId"] == pid]
    total_est = sum(t["estimate"] for t in ts) or 1
    cost_of = lambda t: p["bac"] * t["estimate"] / total_est
    pv = sum(cost_of(t) * planned_frac(t, TODAY) for t in ts)
    ev = sum(cost_of(t) * earned_now(t) for t in ts)
    ac = ev * p["costFactor"]
    cpi = ev / ac if ac > 0 else 1.0
    spi = ev / pv if pv > 0 else 1.0
    eac = p["bac"] / cpi if cpi > 0 else p["bac"]
    cv, sv = ev - ac, ev - pv
    vac = p["bac"] - eac
    tcpi = (p["bac"] - ev) / (p["bac"] - ac) if (p["bac"] - ac) != 0 else 1.0
    health = "ok" if (cpi >= 0.95 and spi >= 0.95) else ("warn" if (cpi >= 0.8 and spi >= 0.8) else "bad")
    return {"p": p, "pv": pv, "ev": ev, "ac": ac, "cpi": cpi, "spi": spi,
            "eac": eac, "etc": eac - ac, "vac": vac, "cv": cv, "sv": sv,
            "tcpi": tcpi, "health": health, "pct": ev / p["bac"] if p["bac"] else 0}


def evm_aggregate(pids, tasks):
    """Cumul EVM d'une sélection de projets (CPI / SPI pondérés)."""
    if not pids:
        return None
    ms = [evm_metrics(pid, tasks) for pid in pids]
    bac = sum(m["p"]["bac"] for m in ms)
    pv = sum(m["pv"] for m in ms)
    ev = sum(m["ev"] for m in ms)
    ac = sum(m["ac"] for m in ms)
    cpi = ev / ac if ac > 0 else 1.0
    spi = ev / pv if pv > 0 else 1.0
    eac = bac / cpi if cpi > 0 else bac
    cv, sv = ev - ac, ev - pv
    vac = bac - eac
    tcpi = (bac - ev) / (bac - ac) if (bac - ac) != 0 else 1.0
    health = "ok" if (cpi >= 0.95 and spi >= 0.95) else ("warn" if (cpi >= 0.8 and spi >= 0.8) else "bad")
    return {"bac": bac, "pv": pv, "ev": ev, "ac": ac, "cpi": cpi, "spi": spi,
            "eac": eac, "etc": eac - ac, "vac": vac, "cv": cv, "sv": sv,
            "tcpi": tcpi, "health": health, "pct": ev / bac if bac else 0, "count": len(pids)}


def _curve_points(parts, bac, ev_today, ac_today, eac_total, start_d, end_d):
    """Points communs des courbes en S (une liste par projet fournie)."""
    total = max(7, (end_d - start_d).days)
    step = max(1, round(total / 18))
    offsets = set(range(0, total + 1, step))
    today_off = (TODAY - start_d).days
    if 0 <= today_off <= total:
        offsets.add(today_off)
    offsets.add(total)
    end_from_today = max(1, (end_d - TODAY).days)
    pts = []
    for off in sorted(offsets):
        day = start_d + timedelta(days=off)
        is_future = day > TODAY
        is_today = day == TODAY
        pv = ev_a = ac_a = 0.0
        for cost_of, ts, factor in parts:
            for t in ts:
                pv += cost_of(t) * planned_frac(t, day)
                f = cost_of(t) * earned_frac_at(t, day)
                ev_a += f
                ac_a += f * factor
        f_frac = clamp01((day - TODAY).days / end_from_today)
        pts.append({
            "date": day,
            "pv": round(pv / 100) / 10,
            "ev": None if is_future else round(ev_a / 100) / 10,
            "ac": None if is_future else round(ac_a / 100) / 10,
            "evF": round((ev_today + (bac - ev_today) * f_frac) / 100) / 10 if (is_future or is_today) else None,
            "acF": round((ac_today + (eac_total - ac_today) * f_frac) / 100) / 10 if (is_future or is_today) else None,
        })
    return pts


def _cost_factory(bac: float, total_est: float):
    """Fabrique la fonction coût d'une tâche (évite le piège des closures en boucle)."""
    return lambda t: bac * t["estimate"] / total_est


def s_curve(pid, tasks):
    m = evm_metrics(pid, tasks)
    p = m["p"]
    ts = [t for t in tasks if t["projectId"] == pid]
    total_est = sum(t["estimate"] for t in ts) or 1
    parts = [(_cost_factory(p["bac"], total_est), ts, p["costFactor"])]
    start_d = min((t["start"] for t in ts), default=TODAY)
    return _curve_points(parts, p["bac"], m["ev"], m["ac"], m["eac"], start_d, p["deadline"])


def s_curve_multi(pids, tasks):
    parts, starts, ends, evs, acs, eacs = [], [], [], [], [], []
    bacs = 0.0
    for pid in pids:
        m = evm_metrics(pid, tasks)
        p = m["p"]
        ts = [t for t in tasks if t["projectId"] == pid]
        total_est = sum(t["estimate"] for t in ts) or 1
        parts.append((_cost_factory(p["bac"], total_est), ts, p["costFactor"]))
        starts.append(min((t["start"] for t in ts), default=TODAY))
        ends.append(p["deadline"])
        evs.append(m["ev"])
        acs.append(m["ac"])
        eacs.append(m["eac"])
        bacs += p["bac"]
    if not parts:
        return []
    return _curve_points(parts, bacs, sum(evs), sum(acs), sum(eacs), min(starts), max(ends))


def perf_color(v):
    return "#10b981" if v >= 0.95 else ("#f59e0b" if v >= 0.85 else "#ef4444")


def delta_color(v):
    return "#10b981" if v >= 0 else "#ef4444"


def plot_s_curve(pts, height=340, show_legend=True):
    xs = [p["date"] for p in pts]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=[p["pv"] for p in pts], name="Planifié (PV)",
                             line=dict(color="#94a3b8", width=2), connectgaps=False))
    fig.add_trace(go.Scatter(x=xs, y=[p["ev"] for p in pts], name="Acquis (EV)",
                             line=dict(color="#10b981", width=2.5), connectgaps=False))
    fig.add_trace(go.Scatter(x=xs, y=[p["ac"] for p in pts], name="Réel (AC)",
                             line=dict(color="#ef4444", width=2.5), connectgaps=False))
    fig.add_trace(go.Scatter(x=xs, y=[p["evF"] for p in pts], name="EV prévisionnel",
                             line=dict(color="#10b981", width=1.5, dash="dash"), connectgaps=False))
    fig.add_trace(go.Scatter(x=xs, y=[p["acF"] for p in pts], name="AC prévisionnel (EAC)",
                             line=dict(color="#ef4444", width=1.5, dash="dash"), connectgaps=False))
    fig.add_vline(x=pd.Timestamp(TODAY), line=dict(color="#6366f1", dash="dot"),
                  annotation_text="Aujourd'hui", annotation_font=dict(color="#4f46e5", size=10))
    fig.update_layout(height=height, template="plotly_white", margin=dict(l=10, r=10, t=20, b=10),
                      yaxis_title="k€", showlegend=show_legend,
                      legend=dict(orientation="h", y=-0.2))
    return fig


def show_s_curve(pts, height=340, show_legend=True):
    """Affiche la courbe en S : Plotly si disponible, sinon graphiques natifs Streamlit."""
    if PLOTLY_AVAILABLE:
        st.plotly_chart(plot_s_curve(pts, height=height, show_legend=show_legend), use_container_width=True)
        return
    df = pd.DataFrame({
        "Planifié (PV)": [p["pv"] for p in pts],
        "Acquis (EV)": [p["ev"] for p in pts],
        "Réel (AC)": [p["ac"] for p in pts],
        "EV prévisionnel": [p["evF"] for p in pts],
        "AC prévisionnel (EAC)": [p["acF"] for p in pts],
    }, index=pd.to_datetime([p["date"] for p in pts]))
    st.caption(f"📍 Aujourd'hui ({fmt_d(TODAY)}) : EV = "
               f"{next((p['ev'] for p in pts if p['ev'] is not None), 0):.1f} k€")
    st.line_chart(df, height=height)


# ==================================================================
# ÉTAT DE SESSION
# ==================================================================

if "tasks" not in st.session_state:
    st.session_state.tasks = [dict(t) for t in DEMO_TASKS]

tasks = st.session_state.tasks


# ==================================================================
# COMPOSANTS D'INTERFACE
# ==================================================================

def md_metric(label, value_html):
    st.markdown(
        f"<div style='border:1px solid #e2e8f0;border-radius:10px;padding:8px 12px;background:#f8fafc'>"
        f"<div style='font-size:.65rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em'>{label}</div>"
        f"<div style='font-size:1.25rem;font-weight:800'>{value_html}</div></div>",
        unsafe_allow_html=True)


def kpi_row(items):
    cols = st.columns(len(items))
    for col, (label, value, sub) in zip(cols, items):
        col.metric(label=label, value=value)
        col.caption(sub)


def task_editor(t, key_prefix, in_expander=True):
    """Éditeur complet d'une tâche (statut, priorité, assigné, dates, avancement)."""
    new_status = st.selectbox("Statut", STATUS_IDS, index=STATUS_IDS.index(t["status"]), key=f"{key_prefix}_st_{t['id']}")
    if new_status != t["status"]:
        t["status"] = new_status
        if new_status == "done":
            t["progress"] = 100
        st.rerun()
    new_prio = st.selectbox("Priorité", PRIO_IDS, index=PRIO_IDS.index(t["priority"]), key=f"{key_prefix}_pr_{t['id']}")
    if new_prio != t["priority"]:
        t["priority"] = new_prio
        st.rerun()
    member_names = [m["name"] for m in MEMBERS]
    new_assignee = st.selectbox("Assigné à", member_names, index=[m["id"] for m in MEMBERS].index(t["assigneeId"]), key=f"{key_prefix}_as_{t['id']}")
    new_id = next(m["id"] for m in MEMBERS if m["name"] == new_assignee)
    if new_id != t["assigneeId"]:
        t["assigneeId"] = new_id
        st.rerun()
    c1, c2 = st.columns(2)
    new_start = c1.date_input("Début", value=t["start"], key=f"{key_prefix}_sd_{t['id']}", format="DD/MM/YYYY")
    new_due = c2.date_input("Échéance", value=t["due"], key=f"{key_prefix}_du_{t['id']}", format="DD/MM/YYYY")
    if new_start != t["start"]:
        t["start"] = new_start
        st.rerun()
    if new_due != t["due"]:
        t["due"] = new_due
        st.rerun()
    c3, c4 = st.columns(2)
    new_est = c3.number_input("Estimation (h)", min_value=1, value=t["estimate"], key=f"{key_prefix}_es_{t['id']}")
    if new_est != t["estimate"]:
        t["estimate"] = int(new_est)
        st.rerun()
    new_prog = c4.slider("Avancement (%)", 0, 100, t["progress"], 5, key=f"{key_prefix}_pg_{t['id']}")
    if new_prog != t["progress"]:
        t["progress"] = int(new_prog)
        st.rerun()
    if st.button("🗑 Supprimer la tâche", key=f"{key_prefix}_del_{t['id']}"):
        st.session_state.tasks = [x for x in tasks if x["id"] != t["id"]]
        st.rerun()


def new_task_form():
    with st.expander("➕ Nouvelle tâche"):
        with st.form("new_task_form", border=True):
            title = st.text_input("Titre de la tâche")
            c1, c2 = st.columns(2)
            project_name = c1.selectbox("Projet", [p["name"] for p in PROJECTS])
            assignee_name = c2.selectbox("Assigné à", [m["name"] for m in MEMBERS])
            c3, c4 = st.columns(2)
            priority = c3.selectbox("Priorité", PRIO_IDS, index=2)
            status = c4.selectbox("Statut", STATUS_IDS, index=1)
            c5, c6 = st.columns(2)
            start = c5.date_input("Début", value=TODAY, format="DD/MM/YYYY")
            due = c6.date_input("Échéance", value=d(7), format="DD/MM/YYYY")
            c7, c8 = st.columns(2)
            estimate = c7.number_input("Estimation (heures)", min_value=1, value=4)
            submitted = st.form_submit_button("Créer la tâche", use_container_width=True, type="primary")
        if submitted and title.strip():
            st.session_state.tasks.insert(0, {
                "id": "t" + uuid.uuid4().hex[:6],
                "title": title.strip(),
                "projectId": next(p["id"] for p in PROJECTS if p["name"] == project_name),
                "assigneeId": next(m["id"] for m in MEMBERS if m["name"] == assignee_name),
                "status": status, "priority": priority,
                "start": start, "due": due, "estimate": int(estimate), "progress": 0,
            })
            st.rerun()


# ==================================================================
# VUES
# ==================================================================

def view_dashboard():
    st.subheader("🏠 Vue d'ensemble du portefeuille")
    total = len(tasks)
    done = [t for t in tasks if t["status"] == "done"]
    late = [t for t in tasks if is_late(t)]
    total_est = sum(t["estimate"] for t in tasks) or 1
    weighted = sum(t["estimate"] * (100 if t["status"] == "done" else t["progress"]) / 100 for t in tasks) / total_est
    open_est = sum(t["estimate"] * (1 - (100 if t["status"] == "done" else t["progress"]) / 100) for t in tasks if t["status"] != "done")
    capacity = sum(m["capacity"] for m in MEMBERS)
    load = open_est / capacity * 100
    soon = [p for p in PROJECTS if p["deadline"] < d(14)]

    kpi_row([
        ("Avancement global", f"{weighted:.0f}%", f"{len(done)}/{total} tâches terminées"),
        ("En retard", str(len(late)), "échéances dépassées"),
        ("Charge équipe", f"{load:.0f}%", f"{open_est:.0f}h restantes / {capacity}h de capacité"),
        ("Projets actifs", str(len(PROJECTS)), f"{len(soon)} échéance(s) < 14 j" if soon else "échéances sereines"),
    ])
    st.divider()

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**📈 Burndown — 14 derniers jours**")
        days = [d(-i) for i in range(13, -1, -1)]
        ideal = [round(total * i / 13) for i in range(13, -1, -1)]
        remaining = [total - len([t for t in done if t["due"] <= day]) for day in days]
        if PLOTLY_AVAILABLE:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=days, y=ideal, name="Idéal",
                                     line=dict(color="#94a3b8", width=1.5, dash="dash")))
            fig.add_trace(go.Scatter(x=days, y=remaining, name="Restant",
                                     line=dict(color="#6366f1", width=2.5), fill="tozeroy",
                                     fillcolor="rgba(99,102,241,0.12)"))
            fig.update_layout(height=250, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10),
                              legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.line_chart(pd.DataFrame({"Idéal": ideal, "Restant": remaining},
                                       index=pd.to_datetime(days)), height=250)
    with right:
        st.markdown("**🥧 Répartition par statut**")
        counts = [(s["label"], len([t for t in tasks if t["status"] == s["id"]]), s["color"]) for s in STATUSES]
        if PLOTLY_AVAILABLE:
            fig = px.pie(names=[c[0] for c in counts], values=[c[1] for c in counts],
                         color=[c[0] for c in counts], color_discrete_map={c[0]: c[2] for c in counts},
                         hole=0.55)
            fig.update_traces(textinfo="value", showlegend=True)
            fig.update_layout(height=250, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.bar_chart(pd.Series({c[0]: c[1] for c in counts}, name="Tâches"),
                         height=250, horizontal=True)

    left2, right2 = st.columns([3, 2])
    with left2:
        st.markdown("**📈 Avancement par projet**")
        for p in PROJECTS:
            ts = [t for t in tasks if t["projectId"] == p["id"]]
            est = sum(t["estimate"] for t in ts) or 1
            pct = round(sum(t["estimate"] * (100 if t["status"] == "done" else t["progress"]) / 100 for t in ts) / est)
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"**{p['name']}** <span style='color:#94a3b8'>· {p['client']}</span>", unsafe_allow_html=True)
            c2.markdown(f"**{pct}%**", unsafe_allow_html=True)
            c2.markdown(f"<div style='height:8px;border-radius:4px;background:#e2e8f0'>"
                        f"<div style='height:8px;border-radius:4px;width:{pct}%;background:{p['color']}'></div></div>",
                        unsafe_allow_html=True)
    with right2:
        st.markdown("**⏰ Prochaines échéances**")
        upcoming = sorted([t for t in tasks if t["status"] != "done"], key=lambda t: t["due"])[:6]
        for t in upcoming:
            m = get_member(t["assigneeId"])
            flag = "⚠️ " if is_late(t) else ""
            color = "#ef4444" if is_late(t) else "#94a3b8"
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:8px;padding:4px 0'>"
                f"<span style='width:26px;height:26px;border-radius:50%;background:{m['color']};"
                f"color:#0f172a;font-size:11px;font-weight:800;display:inline-flex;align-items:center;justify-content:center'>{m['initials']}</span>"
                f"<span style='flex:1;font-size:.85rem'>{flag}{t['title']}</span>"
                f"<span style='font-size:.75rem;color:{color};font-weight:700'>{'⚠ ' if is_late(t) else ''}{fmt_d(t['due'])}</span></div>",
                unsafe_allow_html=True)


def view_kanban():
    new_task_form()
    st.divider()
    cols = st.columns(5)
    for col, s in zip(cols, STATUSES):
        items = [t for t in tasks if t["status"] == s["id"]]
        with col:
            st.markdown(f"<span style='color:{s['color']}'>●</span> **{s['label']}** "
                        f"<span style='color:#94a3b8'>({len(items)})</span>", unsafe_allow_html=True)
            for t in items:
                p, prio = get_project(t["projectId"]), prio_of(t)
                with st.container(border=True):
                    st.markdown(f"**{t['title']}**")
                    st.markdown(
                        f"<span style='color:{p['color']};font-size:.68rem;font-weight:800'>{p['name'].upper()}</span> · "
                        f"<span style='color:{prio['color']};font-size:.68rem;font-weight:800'>{prio['label'].upper()}</span>",
                        unsafe_allow_html=True)
                    if t["status"] != "done" and t["progress"] > 0:
                        st.progress(t["progress"])
                    late_html = f"<span style='color:#ef4444;font-weight:800'>⚠ {fmt_d(t['due'])}</span>" if is_late(t) \
                        else f"<span style='color:#94a3b8'>{fmt_d(t['due'])}</span>"
                    st.markdown(late_html, unsafe_allow_html=True)
                    with st.expander("Éditer"):
                        task_editor(t, "kb")


def view_tasks():
    new_task_form()
    st.divider()
    c1, c2, c3, c4, c5 = st.columns([2.4, 1.3, 1.3, 1.3, 1])
    q = c1.text_input("🔍 Rechercher", "")
    f_status = c2.selectbox("Statut", ["all"] + STATUS_IDS, format_func=lambda x: "Tous" if x == "all" else x)
    f_prio = c3.selectbox("Priorité", ["all"] + PRIO_IDS, format_func=lambda x: "Toutes" if x == "all" else x)
    f_member = c4.selectbox("Assigné", ["all"] + [m["id"] for m in MEMBERS],
                            format_func=lambda x: "Toute l'équipe" if x == "all" else get_member(x)["name"])
    f_late = c5.checkbox("Retards uniquement")

    rows = []
    for t in tasks:
        if q and q.lower() not in t["title"].lower():
            continue
        if f_status != "all" and t["status"] != f_status:
            continue
        if f_prio != "all" and t["priority"] != f_prio:
            continue
        if f_member != "all" and t["assigneeId"] != f_member:
            continue
        if f_late and not is_late(t):
            continue
        p, m, s, prio = get_project(t["projectId"]), get_member(t["assigneeId"]), status_of(t), prio_of(t)
        rows.append({
            "Tâche": t["title"], "Projet": p["name"], "Assigné": m["name"],
            "Priorité": prio["label"], "Statut": s["label"],
            "Échéance": ("⚠ " if is_late(t) else "") + t["due"].strftime("%d/%m/%Y"),
            "Avancement": f"{100 if t['status'] == 'done' else t['progress']}%",
            "Estimation (h)": t["estimate"],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=420)
    st.caption(f"{len(rows)} tâche(s) affichée(s)")

    st.divider()
    st.markdown("**✏️ Modifier une tâche**")
    options = {f"{t['title']}  ·  {get_project(t['projectId'])['name']}": t for t in tasks}
    if options:
        choice = st.selectbox("Tâche", list(options.keys()))
        task_editor(options[choice], "ed")


def view_planning():
    st.subheader("📅 Planning prévisionnel (Gantt)")
    f_project = st.selectbox("Projet", ["all"] + [p["id"] for p in PROJECTS],
                             format_func=lambda x: "Tous les projets" if x == "all" else get_project(x)["name"])
    shown = tasks if f_project == "all" else [t for t in tasks if t["projectId"] == f_project]
    if not shown:
        st.info("Aucune tâche.")
        return
    df = pd.DataFrame([{
        "title": t["title"], "start": pd.Timestamp(t["start"]), "end": pd.Timestamp(t["due"]),
        "project": get_project(t["projectId"])["name"], "assignee": get_member(t["assigneeId"])["name"],
        "estimate": t["estimate"],
    } for t in shown])
    colors = {p["name"]: p["color"] for p in PROJECTS}
    if PLOTLY_AVAILABLE:
        fig = px.timeline(df, x_start="start", x_end="end", y="title", color="project",
                          color_discrete_map=colors, hover_data=["assignee", "estimate"])
        fig.update_yaxes(autorange="reversed")
        fig.add_vline(x=pd.Timestamp(TODAY), line=dict(color="#6366f1", dash="dot"),
                      annotation_text="Aujourd'hui", annotation_font=dict(color="#4f46e5", size=10))
        fig.update_layout(height=max(300, 40 * len(shown) + 80), template="plotly_white",
                          margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        import altair as alt
        base = alt.Chart(df).mark_bar().encode(
            y=alt.Y("title", sort=list(df["title"]), axis=alt.Axis(title=None)),
            x=alt.X("start", title="Date"),
            x2="end",
            color=alt.Color("project", scale=alt.Scale(domain=list(colors), range=list(colors.values())),
                            legend=None),
            tooltip=["title", "project", "assignee", "estimate"],
        )
        today = alt.Chart(pd.DataFrame({"x": [pd.Timestamp(TODAY)]})).mark_rule(
            color="#6366f1", strokeDash=[4, 4]).encode(x="x")
        st.altair_chart((base + today).properties(height=max(300, 40 * len(shown) + 80)),
                        use_container_width=True)
    st.caption("Week-ends non distingués dans cette version — la ligne bleue pointillée marque aujourd'hui.")


def view_team():
    st.subheader("👥 Charge de travail de l'équipe")
    grid = st.columns(3)
    for i, m in enumerate(MEMBERS):
        mine = [t for t in tasks if t["assigneeId"] == m["id"]]
        open_tasks = [t for t in mine if t["status"] != "done"]
        remaining = round(sum(t["estimate"] * (1 - t["progress"] / 100) for t in open_tasks))
        load = min(100, round(remaining / m["capacity"] * 100))
        late = [t for t in open_tasks if is_late(t)]
        color = "#ef4444" if load > 100 else ("#f59e0b" if load > 80 else "#10b981")
        with grid[i % 3]:
            with st.container(border=True):
                st.markdown(
                    f"<span style='width:38px;height:38px;border-radius:50%;background:{m['color']};"
                    f"color:#0f172a;font-weight:800;display:inline-flex;align-items:center;justify-content:center'>{m['initials']}</span> "
                    f"**{m['name']}** &nbsp;<span style='color:#94a3b8;font-size:.8rem'>{m['role']}</span>"
                    + (f" &nbsp;<span style='color:#ef4444;font-weight:800;font-size:.75rem'>{len(late)} en retard</span>" if late else ""),
                    unsafe_allow_html=True)
                st.markdown(f"**Charge :** <span style='color:{color}'>{remaining}h / {m['capacity']}h</span>", unsafe_allow_html=True)
                st.progress(load)
                st.markdown(f"<span style='font-size:.75rem;color:#94a3b8'>Tâches ouvertes : {len(open_tasks)}</span>", unsafe_allow_html=True)
                for t in open_tasks[:3]:
                    st.markdown(f"<span style='font-size:.78rem;color:#475569'>• {t['title']} "
                                f"({t['estimate'] - round(t['estimate'] * t['progress'] / 100)}h)</span>", unsafe_allow_html=True)
                if len(open_tasks) > 3:
                    st.markdown(f"<span style='font-size:.75rem;color:#94a3b8'>+ {len(open_tasks) - 3} autre(s)…</span>", unsafe_allow_html=True)


def view_evm():
    st.subheader("💶 Budget & EVM — gestion de la valeur acquise")
    cols = st.columns(len(PROJECTS))
    selected = []
    for col, p in zip(cols, PROJECTS):
        with col:
            h = HEALTH[evm_metrics(p["id"], tasks)["health"]]
            if st.checkbox(p["name"], value=True, key=f"chk_{p['id']}"):
                selected.append(p["id"])
            st.caption(h[0])
    if not selected:
        st.info("Cochez au moins un projet ci-dessus pour afficher le suivi budgétaire.")
        return
    m = evm_aggregate(selected, tasks)
    consumed = m["ac"] / m["bac"] * 100

    st.markdown(f"**KPI cumulés — {m['count']} projet(s) suivi(s)**")
    kpi_row([
        ("Budget total (BAC)", fmt_k(m["bac"]), "budget engagé cumulé"),
        ("Valeur planifiée (PV)", fmt_k(m["pv"]), "travail planifié à ce jour"),
        ("Valeur acquise (EV)", fmt_k(m["ev"]), f"avancement réel : {m['pct'] * 100:.0f} %"),
        ("Coût réel (AC)", fmt_k(m["ac"]), f"{consumed:.0f} % consommés vs {m['pct'] * 100:.0f} % réalisés"),
    ])

    ind = st.columns(8)
    items = [
        ("CPI · coût", f"{m['cpi']:.2f}", perf_color(m["cpi"]), "CPI = EV / AC. > 1 : sous le budget"),
        ("SPI · délai", f"{m['spi']:.2f}", perf_color(m["spi"]), "SPI = EV / PV. > 1 : en avance"),
        ("CV", fmt_k(m["cv"]), delta_color(m["cv"]), "Écart de coût = EV − AC"),
        ("SV", fmt_k(m["sv"]), delta_color(m["sv"]), "Écart de délai = EV − PV"),
        ("EAC", fmt_k(m["eac"]), delta_color(m["bac"] - m["eac"]), "Coût prévisionnel à terminaison = BAC / CPI"),
        ("ETC", fmt_k(m["etc"]), "#0f172a", "Coût restant à engager = EAC − AC"),
        ("VAC", fmt_k(m["vac"]), delta_color(m["vac"]), "Variance à terminaison = BAC − EAC"),
        ("TCPI", f"{m['tcpi']:.2f}", "#10b981" if m["tcpi"] <= 1 else ("#f59e0b" if m["tcpi"] <= 1.15 else "#ef4444"),
         "Efficacité requise = (BAC − EV) / (BAC − AC)"),
    ]
    for col, (label, value, color, tip) in zip(ind, items):
        with col:
            md_metric(label, f"<span style='color:{color}'>{value}</span>")
            st.caption(tip)

    st.divider()
    mode = st.radio("Mode d'affichage", ["Cumul", "Par projet"], horizontal=True, label_visibility="collapsed")
    if mode == "Cumul":
        st.markdown(f"**📈 Courbe en S cumulée — {m['count']} projet(s)** "
                    f"<span style='color:#94a3b8;font-size:.8rem'>(k€, avec projections pointillées jusqu'à l'EAC)</span>",
                    unsafe_allow_html=True)
        show_s_curve(s_curve_multi(selected, tasks))
    else:
        for pid in selected:
            p = get_project(pid)
            e = evm_metrics(pid, tasks)
            st.markdown(f"**● {p['name']}** &nbsp;<span style='font-size:.8rem'>CPI "
                        f"<b style='color:{perf_color(e['cpi'])}'>{e['cpi']:.2f}</b> · SPI "
                        f"<b style='color:{perf_color(e['spi'])}'>{e['spi']:.2f}</b></span>", unsafe_allow_html=True)
            show_s_curve(s_curve(pid, tasks), height=240, show_legend=False)

    st.divider()
    st.markdown("**📋 Vue consolidée — projets cochés uniquement**")
    rows = []
    for pid in selected:
        e = evm_metrics(pid, tasks)
        rows.append({
            "Projet": get_project(pid)["name"], "BAC": fmt_k(e["p"]["bac"]), "PV": fmt_k(e["pv"]),
            "EV": fmt_k(e["ev"]), "AC": fmt_k(e["ac"]), "CV": fmt_k(e["cv"]), "SV": fmt_k(e["sv"]),
            "CPI": f"{e['cpi']:.2f}", "SPI": f"{e['spi']:.2f}", "EAC": fmt_k(e["eac"]),
            "VAC": fmt_k(e["vac"]), "Santé": HEALTH[e["health"]][0],
        })
    rows.append({
        "Projet": f"Σ Cumul sélection ({m['count']})", "BAC": fmt_k(m["bac"]), "PV": fmt_k(m["pv"]),
        "EV": fmt_k(m["ev"]), "AC": fmt_k(m["ac"]), "CV": fmt_k(m["cv"]), "SV": fmt_k(m["sv"]),
        "CPI": f"{m['cpi']:.2f}", "SPI": f"{m['spi']:.2f}", "EAC": fmt_k(m["eac"]),
        "VAC": fmt_k(m["vac"]), "Santé": HEALTH[m["health"]][0],
    })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("PV = valeur planifiée · EV = valeur acquise · AC = coût réel · EAC = BAC / CPI · VAC = BAC − EAC. "
               "Coûts réels modélisés à partir de l'avancement des tâches × facteur de coût du projet (données de démo).")


def view_reports():
    st.subheader("📊 Rapports")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**💪 Charge restante par membre (h)**")
        data = []
        for m in MEMBERS:
            remaining = round(sum(t["estimate"] * (1 - t["progress"] / 100)
                                  for t in tasks if t["assigneeId"] == m["id"] and t["status"] != "done"))
            data.append({"Membre": m["initials"], "Capacité": m["capacity"], "Restant": remaining, "color": m["color"]})
        df = pd.DataFrame(data)
        if PLOTLY_AVAILABLE:
            fig = go.Figure()
            fig.add_bar(x=df["Membre"], y=df["Capacité"], name="Capacité", marker_color="#e2e8f0")
            fig.add_bar(x=df["Membre"], y=df["Restant"], name="Restant", marker_color=df["color"])
            fig.update_layout(barmode="overlay", height=260, template="plotly_white",
                              margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.bar_chart(df.set_index("Membre")[["Capacité", "Restant"]], height=260)

        st.markdown("**🚨 Priorités ouvertes**")
        counts = [(p["label"], len([t for t in tasks if t["priority"] == p["id"] and t["status"] != "done"]), p["color"]) for p in PRIORITIES]
        if PLOTLY_AVAILABLE:
            fig = px.pie(names=[c[0] for c in counts], values=[c[1] for c in counts],
                         color=[c[0] for c in counts], color_discrete_map={c[0]: c[2] for c in counts}, hole=0.4)
            fig.update_layout(height=260, template="plotly_white", margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.bar_chart(pd.Series({c[0]: c[1] for c in counts}, name="Tâches ouvertes"),
                         height=260, horizontal=True)
    with c2:
        st.markdown("**🗂️ Heures par projet**")
        data = []
        for p in PROJECTS:
            ts = [t for t in tasks if t["projectId"] == p["id"]]
            data.append({
                "Projet": p["name"],
                "Heures totales": sum(t["estimate"] for t in ts),
                "Heures restantes": round(sum(t["estimate"] * (1 - (100 if t["status"] == "done" else t["progress"]) / 100) for t in ts)),
            })
        df = pd.DataFrame(data)
        if PLOTLY_AVAILABLE:
            fig = go.Figure()
            fig.add_bar(y=df["Projet"], x=df["Heures totales"], name="Heures totales", orientation="h", marker_color="#94a3b8")
            fig.add_bar(y=df["Projet"], x=df["Heures restantes"], name="Heures restantes", orientation="h", marker_color="#6366f1")
            fig.update_layout(barmode="overlay", height=260, template="plotly_white",
                              margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.bar_chart(df.set_index("Projet")[["Heures totales", "Heures restantes"]],
                         height=260, horizontal=True)

        st.markdown("**📌 Statistiques clés**")
        total_h = sum(t["estimate"] for t in tasks)
        remaining_h = sum(t["estimate"] * (1 - (100 if t["status"] == "done" else t["progress"]) / 100) for t in tasks)
        done_n = len([t for t in tasks if t["status"] == "done"])
        late_n = len([t for t in tasks if is_late(t)])
        grid = st.columns(2)
        stats = [
            ("Heures estimées (total)", f"{total_h}h"),
            ("Heures restantes", f"{remaining_h:.0f}h"),
            ("Tâches terminées", f"{done_n}/{len(tasks)}"),
            ("Taux de retard", f"{late_n / max(1, len(tasks)) * 100:.0f}%"),
            ("Charge moyenne / membre", f"{remaining_h / len(MEMBERS):.0f}h"),
            ("Projets au planning", str(len(PROJECTS))),
        ]
        for col, (label, value) in zip(grid * 3, stats):
            md_metric(label, value)


# ==================================================================
# BARRE LATÉRALE & NAVIGATION
# ==================================================================

with st.sidebar:
    st.markdown("## 🚀 PilotPro")
    st.caption("Le logiciel du chef de projet ultime")
    if not PLOTLY_AVAILABLE:
        st.info("💡 Plotly n'est pas installé : l'app utilise les graphiques natifs. "
                "Ajoutez `plotly` dans requirements.txt pour les graphiques interactifs.", icon="📈")
    st.divider()
    late_count = len([t for t in tasks if is_late(t)])
    nav = st.radio(
        "Navigation",
        ["Tableau de bord", "Kanban", "Tâches", "Planning", "Équipe", "Budget & EVM", "Rapports"],
        index=0, label_visibility="collapsed")
    st.divider()
    with st.expander("💾 Données"):
        payload = json.dumps([{**t, "start": t["start"].isoformat(), "due": t["due"].isoformat()} for t in tasks],
                             ensure_ascii=False, indent=2)
        st.download_button("Exporter les tâches (JSON)", data=payload,
                           file_name="pilotpro_tasks.json", mime="application/json", use_container_width=True)
        if st.button("🔄 Réinitialiser les données de démo", use_container_width=True):
            st.session_state.tasks = [dict(t) for t in DEMO_TASKS]
            st.rerun()
    st.caption(f"⚠️ {late_count} tâche(s) en retard" if late_count else "✨ Aucun retard détecté")

st.title(nav)
st.caption(TODAY.strftime("%A %d %B %Y").capitalize())

VIEWS = {
    "Tableau de bord": view_dashboard,
    "Kanban": view_kanban,
    "Tâches": view_tasks,
    "Planning": view_planning,
    "Équipe": view_team,
    "Budget & EVM": view_evm,
    "Rapports": view_reports,
}
VIEWS[nav]()