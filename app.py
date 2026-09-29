from __future__ import annotations
from datetime import datetime, timezone, timedelta, date
import base64
import hashlib
import io
import logging
import os
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# =========================================================
# 0. SISTEM, LOGGING VE ORTAM YAPILANDIRMASI
# =========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AIBS_CORE")

st.set_page_config(
    page_title="Aygaz Arşiv Sistemi",
    page_icon="Aygaz.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("AIBS_DB_PATH", BASE_DIR / "aibs_database.db"))
ENVIRONMENT = os.getenv("AIBS_ENV", "DEMO").strip().upper()
SSO_HEADER_USER = os.getenv("AIBS_SSO_USER_HEADER", "X-Remote-User")
SSO_HEADER_ROLE = os.getenv("AIBS_SSO_ROLE_HEADER", "X-Remote-Role")

TR_TZ = timezone(timedelta(hours=3))
TR_AYLAR = {
    1: "Oca", 2: "Şub", 3: "Mar", 4: "Nis", 5: "May", 6: "Haz",
    7: "Tem", 8: "Ağu", 9: "Eyl", 10: "Eki", 11: "Kas", 12: "Ara"
}

def suanki_zaman() -> datetime:
    return datetime.now(TR_TZ)

def formatli_tarih() -> str:
    now = suanki_zaman()
    ay = TR_AYLAR[now.month]
    return f"{now.day:02d} {ay} {now.year} · {now.strftime('%H:%M')}"

def format_db_date(date_val: Any) -> str:
    if not date_val or pd.isna(date_val):
        return "-"
    val_str = str(date_val).strip()
    if not val_str or val_str.lower() in ("none", "nan", "nat", "null"):
        return "-"
    if re.match(r"^\d{4}-\d{2}-\d{2}", val_str):
        try:
            parts = val_str[:10].split("-")
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            ay_adi = TR_AYLAR.get(m, str(m))
            return f"{d:02d} {ay_adi} {y}"
        except Exception:
            return val_str
    return val_str

CURRENT_YEAR = suanki_zaman().year

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
SESSION_ID = st.session_state["session_id"]

if "last_viewed_doc" not in st.session_state:
    st.session_state["last_viewed_doc"] = None

if "last_logged_user" not in st.session_state:
    st.session_state["last_logged_user"] = None

# =========================================================
# 1. KURUMSAL ARAYÜZ, CSS VE SIDEBAR BUTONU
# =========================================================
components.html(
    """
    <script>
    const parentDoc = window.parent.document;

    function getNativeSidebarElements() {
        const sidebar = parentDoc.querySelector('[data-testid="stSidebar"]');
        const collapseBtn = parentDoc.querySelector('[data-testid="stSidebarCollapseButton"] button') ||
                            parentDoc.querySelector('button[aria-label="Collapse sidebar"]');
        const expandBtn = parentDoc.querySelector('[data-testid="stSidebarCollapsedControl"] button') ||
                          parentDoc.querySelector('[data-testid="collapsedControl"] button') ||
                          parentDoc.querySelector('button[aria-label="Expand sidebar"]');
        return { sidebar, collapseBtn, expandBtn };
    }

    function isSidebarOpen() {
        const { sidebar, expandBtn } = getNativeSidebarElements();
        if (sidebar) {
            const ariaExpanded = sidebar.getAttribute('aria-expanded');
            if (ariaExpanded === 'true') return true;
            if (ariaExpanded === 'false') return false;
            const rect = sidebar.getBoundingClientRect();
            if (rect.width > 50) return true;
        }
        if (expandBtn) {
            const style = window.getComputedStyle(expandBtn);
            if (style.display !== 'none' && style.visibility !== 'hidden') {
                return false;
            }
        }
        return true;
    }

    function updateArrow() {
        const btn = parentDoc.getElementById("aygaz-sidebar-button");
        if (!btn) return;
        const open = isSidebarOpen();
        btn.innerHTML = open ? "‹" : "›";
        btn.setAttribute("title", open ? "Menüyü Kapat" : "Menüyü Aç");
    }

    function toggleSidebar() {
        const { collapseBtn, expandBtn } = getNativeSidebarElements();
        const open = isSidebarOpen();
        if (open && collapseBtn) {
            collapseBtn.click();
        } else if (!open && expandBtn) {
            expandBtn.click();
        } else {
            const fallback = collapseBtn || expandBtn;
            if (fallback) fallback.click();
        }
        setTimeout(updateArrow, 120);
        setTimeout(updateArrow, 300);
    }

    let btn = parentDoc.getElementById("aygaz-sidebar-button");
    if (!btn) {
        btn = parentDoc.createElement("button");
        btn.id = "aygaz-sidebar-button";
        btn.style.position = "fixed";
        btn.style.left = "10px";
        btn.style.top = "10px";
        btn.style.width = "38px";
        btn.style.height = "38px";
        btn.style.zIndex = "999999999";
        btn.style.background = "#0072bc";
        btn.style.color = "#ffffff";
        btn.style.border = "1px solid #005b94";
        btn.style.borderRadius = "7px";
        btn.style.fontSize = "24px";
        btn.style.lineHeight = "34px";
        btn.style.textAlign = "center";
        btn.style.cursor = "pointer";
        btn.style.boxShadow = "0 2px 8px rgba(0,0,0,.25)";
        btn.style.transition = "background-color 0.15s ease";
        btn.onclick = toggleSidebar;
        parentDoc.body.appendChild(btn);
    }

    updateArrow();
    setInterval(updateArrow, 400);
    </script>
    """,
    height=0,
    width=0
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');

:root { 
    --ink: #17232d; 
    --muted: #687984; 
    --line: #d8e2e8; 
    --paper: #f5f8fa; 
    --white: #ffffff; 
    --aygaz: #0072bc; 
    --aygaz-dark: #005b94; 
    --btn-primary: #005691;
    --btn-primary-hover: #004070;
    --teal: #148b80; 
    --teal-hover: #0f6c63; 
    --orange: #d47d36; 
}

html, body, [class*="css"] { 
    font-family: 'DM Sans', sans-serif; 
}

.stApp { 
    background: var(--paper); 
    color: var(--ink); 
}

table, table *, .dataframe, .dataframe *, [data-testid="stTable"] * {
    background-color: #ffffff !important;
    color: #0f172a !important;
}

table th, .dataframe th, [data-testid="stTable"] th {
    background-color: #005696 !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    padding: 10px 12px !important;
    border: none !important;
}

table td, .dataframe td, [data-testid="stTable"] td {
    background-color: #ffffff !important;
    color: #0f172a !important;
    padding: 8px 12px !important;
    border-bottom: 1px solid #e2e8f0 !important;
}

table tr:hover td, .dataframe tr:hover td {
    background-color: #f1f5f9 !important;
}

[data-testid="stDataFrame"] { 
    background: #ffffff !important; 
    border: 1px solid #b9d8eb !important; 
    border-radius: 7px;
}
[data-testid="stDataFrame"] iframe { background: #ffffff !important; }
[data-testid="stDataFrame"] [role="columnheader"] { background: #0072bc !important; color: #ffffff !important; }
[data-testid="stDataFrame"] [role="gridcell"] { background: #ffffff !important; color: #17232d !important; }

[data-testid="stSidebar"] { 
    background: #0072bc !important; 
    border-right: 0 !important; 
}

[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] .stRadio span { 
    color: #ffffff !important; 
}

[data-testid="stSidebar"] [data-testid="stSelectbox"] div[data-baseweb="select"] > div { 
    background-color: #ffffff !important; 
    border-radius: 7px !important; 
    border: 1px solid #ffffff !important;
}

[data-testid="stSidebar"] [data-testid="stSelectbox"] div[data-baseweb="select"] * { 
    color: #000000 !important; 
    -webkit-text-fill-color: #000000 !important; 
    fill: #000000 !important;
    stroke: #000000 !important;
    font-weight: 600 !important; 
    opacity: 1 !important; 
}

[data-testid="stSidebar"] hr { border-color: #5aa6d2; }
[data-testid="stSidebar"] .stRadio label { padding: 9px 11px; border-radius: 7px; }
[data-testid="stSidebar"] .stRadio label:hover { background: #005b94; }

.stButton button, 
.stDownloadButton button, 
.stFormSubmitButton button,
div[data-testid="stFormSubmitButton"] > button { 
    background-color: var(--btn-primary) !important; 
    border: 1px solid var(--btn-primary) !important; 
    border-radius: 6px !important; 
    font-weight: 600 !important; 
    min-height: 38px !important; 
    color: #ffffff !important; 
    box-shadow: none !important;
}

.stButton button *, 
.stDownloadButton button *, 
.stFormSubmitButton button *,
div[data-testid="stFormSubmitButton"] > button * { 
    color: #ffffff !important; 
    -webkit-text-fill-color: #ffffff !important; 
}

.stButton button:hover, 
.stDownloadButton button:hover, 
.stFormSubmitButton button:hover,
div[data-testid="stFormSubmitButton"] > button:hover { 
    background-color: var(--btn-primary-hover) !important; 
    border-color: var(--btn-primary-hover) !important; 
    color: #ffffff !important; 
}

.main .stTextInput input, 
.main .stTextArea textarea, 
.main div[data-baseweb="select"] > div { 
    background-color: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 6px !important;
    color: #0f172a !important;
    -webkit-text-fill-color: #0f172a !important;
}

.main .stTextInput input:focus, 
.main .stTextArea textarea:focus {
    border-color: var(--aygaz) !important;
    box-shadow: 0 0 0 1px var(--aygaz) !important;
}

h1, h2, h3, h4 { color: var(--ink) !important; letter-spacing: 0 !important; }
h1 { font-size: 30px !important; } 
h2 { font-size: 21px !important; } 
h3 { font-size: 16px !important; }
p, label, .stCaption { color: var(--muted); }

.brand { padding: 10px 0 25px; } 
.brand-mark { font-family: 'Space Mono'; color: #ffffff; font-size: 18px; letter-spacing: 2px; }
.brand-name { color: white; font-size: 21px; font-weight: 700; margin-top: 8px; } 
.brand-meta { color: #d9effb; font-size: 11px; margin-top: 3px; }

.topbar { background: white; border-bottom: 1px solid var(--line); margin: -1rem -1rem 25px; padding: 14px 28px; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 2px 10px rgba(20,49,67,.04); }
.aygaz-lockup { display: flex; align-items: center; gap: 11px; color: var(--aygaz-dark); font-size: 17px; font-weight: 700; letter-spacing: .2px; }
.aygaz-symbol { width: 29px; height: 29px; border-radius: 7px; background: var(--aygaz); display: grid; place-items: center; color: white; font-family: 'Space Mono'; font-size: 14px; font-weight: 700; box-shadow: inset 0 -3px 0 rgba(0,0,0,.12); }
.topbar-user { display: flex; align-items: center; gap: 9px; color: var(--ink); font-size: 12px; font-weight: 600; }
.topbar-user-dot { width: 28px; height: 28px; border-radius: 50%; background: #e3f0f8; color: var(--aygaz-dark); display: grid; place-items: center; font-family: 'Space Mono'; font-size: 10px; }
.scope { background: #eaf4fa; border: 1px solid #c9e2f2; color: #075b91; border-radius: 5px; padding: 8px 11px; font-size: 12px; margin-bottom: 17px; }
.eyebrow { font-family: 'Space Mono'; color: var(--aygaz); font-size: 11px; letter-spacing: 1.4px; text-transform: uppercase; }
.page-head { display: flex; justify-content: space-between; align-items: end; margin: 4px 0 22px; } 
.page-head p { margin: 4px 0 0; font-size: 13px; }
.stamp { border: 1px solid var(--line); background: white; padding: 9px 13px; border-radius: 7px; font-family: 'Space Mono'; font-size: 11px; color: var(--muted); }
.metric { background: white; border: 1px solid var(--line); border-radius: 8px; padding: 16px 17px; min-height: 103px; }
.metric-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 1px; font-weight: 700; } 
.metric-value { color: var(--ink); font-size: 27px; font-weight: 700; margin: 8px 0 2px; } 
.metric-note { color: var(--muted); font-size: 11px; }
.panel { background: white; border: 1px solid var(--line); border-radius: 8px; padding: 18px; } 
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; } 
.panel-title { font-size: 15px; font-weight: 700; color: var(--ink); }
.mono { font-family: 'Space Mono'; } 
.hint { background: #e6f3ef; border-left: 3px solid var(--teal); padding: 11px 13px; border-radius: 4px; font-size: 12px; color: #24544d; } 
.risk { background: #fff3e8; border-left: 3px solid var(--orange); padding: 11px 13px; border-radius: 4px; font-size: 12px; color: #75451f; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 2. VERİTABANI BAĞLANTISI VE GÜVENLİ MİGRASYON MOTORU
# =========================================================
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

def validate_identifier(name: str) -> str:
    if not IDENTIFIER_REGEX.match(name):
        raise ValueError(f"Geçersiz SQL belirteci: {name}")
    return name

def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    validate_identifier(table_name)
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}

def ensure_column_exists(conn: sqlite3.Connection, table_name: str, col_name: str, col_type: str) -> None:
    validate_identifier(table_name)
    validate_identifier(col_name)
    cols = get_table_columns(conn, table_name)
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
        logger.info(f"Migration: {table_name}.{col_name} kolonu başarıyla eklendi.")

def execute_migrations() -> None:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
        """)
        
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS institutions (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT NOT NULL UNIQUE,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS units (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT NOT NULL UNIQUE,
                inst_code TEXT,
                inst_name TEXT,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS series (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                unit_code TEXT,
                unit_name TEXT,
                series_code TEXT NOT NULL UNIQUE,
                retention_year INTEGER,
                legal_basis TEXT,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS user_permissions (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                unit_code TEXT NOT NULL DEFAULT 'ALL',
                auth_codes TEXT,
                role_desc TEXT,
                password_hash TEXT,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS aygaz_main_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_reg_no TEXT NOT NULL UNIQUE,
                doc_no TEXT,
                doc_name TEXT NOT NULL,
                series_code TEXT,
                unit_code TEXT,
                first_doc_date TEXT,
                last_doc_date TEXT,
                box_no TEXT,
                shelf_no TEXT,
                institution TEXT,
                status TEXT DEFAULT 'Depoda',
                destruction_status TEXT DEFAULT 'BEKLİYOR',
                destruction_date TEXT,
                retention_end_year INTEGER
            );
            CREATE TABLE IF NOT EXISTS archive_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                req_no TEXT NOT NULL UNIQUE,
                requester TEXT NOT NULL,
                unit_code TEXT NOT NULL,
                doc_item TEXT NOT NULL,
                delivery_type TEXT NOT NULL,
                urgency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Onay Bekliyor',
                notes TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS request_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                req_no TEXT NOT NULL,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS archive_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                user TEXT NOT NULL,
                action_type TEXT NOT NULL,
                details TEXT,
                object_id TEXT,
                session_id TEXT,
                result TEXT DEFAULT 'SUCCESS',
                previous_hash TEXT,
                event_hash TEXT NOT NULL
            );
        """)

        ensure_column_exists(conn, "institutions", "active", "INTEGER DEFAULT 1")
        ensure_column_exists(conn, "units", "active", "INTEGER DEFAULT 1")
        ensure_column_exists(conn, "series", "active", "INTEGER DEFAULT 1")
        ensure_column_exists(conn, "series", "trigger_event", "TEXT DEFAULT 'Dosyanın Kapanışı'")
        ensure_column_exists(conn, "series", "disposition", "TEXT DEFAULT 'İMHA'")
        ensure_column_exists(conn, "series", "confidentiality", "TEXT DEFAULT 'INTERNAL'")

        ensure_column_exists(conn, "user_permissions", "active", "INTEGER DEFAULT 1")
        ensure_column_exists(conn, "user_permissions", "created_at", "TEXT")
        ensure_column_exists(conn, "user_permissions", "updated_at", "TEXT")
        ensure_column_exists(conn, "user_permissions", "created_by", "TEXT")
        ensure_column_exists(conn, "user_permissions", "updated_by", "TEXT")
        ensure_column_exists(conn, "user_permissions", "password_hash", "TEXT")

        ensure_column_exists(conn, "aygaz_main_archive", "destruction_date", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "destruction_status", "TEXT DEFAULT 'BEKLİYOR'")
        ensure_column_exists(conn, "aygaz_main_archive", "retention_end_year", "INTEGER")
        ensure_column_exists(conn, "aygaz_main_archive", "classification", "TEXT DEFAULT 'INTERNAL'")
        ensure_column_exists(conn, "aygaz_main_archive", "legal_hold", "INTEGER DEFAULT 0")
        ensure_column_exists(conn, "aygaz_main_archive", "legal_hold_reason", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "legal_hold_by", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "legal_hold_at", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "destruction_requested_by", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "destruction_requested_at", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "destruction_approved_by", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "destruction_approved_at", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "created_by", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "created_at", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "updated_by", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "updated_at", "TEXT")

        ensure_column_exists(conn, "archive_requests", "unit_code", "TEXT")
        ensure_column_exists(conn, "archive_requests", "notes", "TEXT")
        ensure_column_exists(conn, "archive_requests", "requester_username", "TEXT")
        ensure_column_exists(conn, "archive_requests", "doc_reg_no", "TEXT")

        ensure_column_exists(conn, "archive_audit", "object_id", "TEXT")
        ensure_column_exists(conn, "archive_audit", "session_id", "TEXT")
        ensure_column_exists(conn, "archive_audit", "result", "TEXT DEFAULT 'SUCCESS'")
        ensure_column_exists(conn, "archive_audit", "previous_hash", "TEXT")
        ensure_column_exists(conn, "archive_audit", "event_hash", "TEXT")

        cursor.execute("""
            UPDATE aygaz_main_archive 
            SET destruction_status = 'BEKLİYOR' 
            WHERE destruction_status IS NULL 
               OR UPPER(destruction_status) IN ('EDILMEDI', 'EDİLMEDİ', 'BEKLEMEDE')
        """)

        # 90101 seed kaydının serisini uyumlu seri 9 ile senkronize et
        cursor.execute("""
            UPDATE aygaz_main_archive 
            SET series_code = '9' 
            WHERE doc_reg_no = '90101' AND (series_code = '6' OR series_code NOT IN (SELECT series_code FROM series))
        """)

        cursor.executescript("""
            CREATE INDEX IF NOT EXISTS idx_archive_search ON aygaz_main_archive (unit_code, series_code, status);
            CREATE INDEX IF NOT EXISTS idx_archive_retention ON aygaz_main_archive (retention_end_year, destruction_status);
            CREATE INDEX IF NOT EXISTS idx_request_queue ON archive_requests (unit_code, status, created_at);
            CREATE INDEX IF NOT EXISTS idx_audit_time ON archive_audit (timestamp);
        """)

        cursor.executemany("INSERT OR IGNORE INTO institutions (id, name, code, active) VALUES (?, ?, ?, 1)", [
            (1, "AYGAZ A.Ş.", "10"), (11, "ZİNERJİ A.Ş.", "40"),
            (12, "ANADOLU HİSARI TANKERCİLİK", "30"), (13, "AYGAZ DOĞALGAZ", "20"),
            (15, "AKPA A.Ş.", "50"), (17, "GAZAL A.Ş.", "60"),
        ])

        cursor.executemany("INSERT OR IGNORE INTO units (id, name, code, inst_code, inst_name, active) VALUES (?, ?, ?, ?, ?, 1)", [
            (1, "TANIMSIZ", "0", "10", "AYGAZ A.Ş."),
            (2, "BİLGİ SİSTEM MÜDÜRLÜĞÜ", "1001", "10", "AYGAZ A.Ş."),
            (3, "BÜTÇE PLANLAMA VE KONTROL MÜDÜRLÜĞÜ", "1002", "10", "AYGAZ A.Ş."),
            (4, "FİNANSMAN MÜDÜRLÜĞÜ", "1003", "10", "AYGAZ A.Ş."),
            (5, "MUHASEBE MÜDÜRLÜĞÜ", "1004", "10", "AYGAZ A.Ş."),
            (6, "BAYİ GELİŞTİRME MÜDÜRLÜĞÜ", "1005", "10", "AYGAZ A.Ş."),
            (7, "İNSAN KAYNAKLARI MÜDÜRLÜĞÜ", "1006", "10", "AYGAZ A.Ş."),
            (8, "GEMİ İŞLETME MÜDÜRLÜĞÜ", "1007", "10", "AYGAZ A.Ş."),
            (9, "İŞLETME MÜHENDİSLİK YATIRIMLAR MÜDÜRLÜĞÜ", "1008", "10", "AYGAZ A.Ş."),
        ])

        cursor.executemany("INSERT OR IGNORE INTO series (id, name, unit_code, unit_name, series_code, retention_year, legal_basis, trigger_event, active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)", [
            (1, "PERSONEL ÖZLÜK DOSYALARI", "1006", "İNSAN KAYNAKLARI MÜDÜRLÜĞÜ", "1", 10, "İş Kanunu Md. 75", "İş İlişkisinin Sona Ermesi"),
            (3, "MAKBUZ VE TAHSİLAT BELGELERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "3", 10, "VUK Md. 253", "Belgenin Düzenlenmesi"),
            (4, "MAHSUP VE YEVMİYE FİŞLERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "4", 10, "TTK Md. 82", "Hesap Döneminin Kapanışı"),
            (9, "TİCARİ BAYİLİK VE MÜLKİYET SÖZLEŞMELERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "9", 100, "Süresiz Saklama", "Sözleşmenin Sona Ermesi"),
            (11, "İŞ SAĞLIĞI VE AMBARLI TEFTİŞ RAPORLARI", "1008", "İŞLETME MÜHENDİSLİK YATIRIMLAR MÜDÜRLÜĞÜ", "11", 15, "6331 Sayılı İSGK", "Rapor Tarihi"),
        ])

        cursor.execute("UPDATE user_permissions SET active = 1 WHERE active IS NULL")
        cursor.execute("INSERT OR IGNORE INTO user_permissions (id, username, full_name, unit_code, auth_codes, role_desc, active) VALUES (?, ?, ?, ?, ?, ?, 1)", 
                       (1, "local\\admin", "Arşiv Yöneticisi", "ALL", "ADMIN,TALEP_YONETIM,IMHA_TALEP,IMHA_ONAY,DENETIM,LEGAL_HOLD,TANIM_YONETIM,RAPOR_GORUNTULE,ARASIRMA_EXPORT", "Yönetici"))
        # İkinci örnek kullanıcı: İmha ayrılığı ve birim görev testi
        cursor.execute("INSERT OR IGNORE INTO user_permissions (id, username, full_name, unit_code, auth_codes, role_desc, active) VALUES (?, ?, ?, ?, ?, ?, 1)", 
                       (2, "local\\muhasebe_sorumlusu", "Muhasebe Arşiv Yetkilisi", "1004", "TALEP_YONETIM,IMHA_TALEP,RAPOR_GORUNTULE", "Arşiv Personeli"))

        if cursor.execute("SELECT COUNT(*) FROM aygaz_main_archive").fetchone()[0] == 0:
            cursor.executemany("""
                INSERT INTO aygaz_main_archive 
                (doc_reg_no, doc_no, doc_name, series_code, unit_code, first_doc_date, last_doc_date, box_no, shelf_no, institution, status, destruction_status, retention_end_year, classification, legal_hold)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                ("90101", "1411-23-201", "Bayi faaliyet raporları", "9", "1004", "01/08/2023", "31/08/2023", "23050", "H11.211", "AYGAZ A.Ş.", "Depoda", "BEKLİYOR", 2028, "INTERNAL", 0),
                ("90102", "1411-23-202", "Ticari bayilik sözleşmeleri", "9", "1004", "01/08/2023", "31/08/2023", "23051", "H11.212", "AYGAZ A.Ş.", "Zimmette", "BEKLİYOR", 2123, "CONFIDENTIAL", 0),
                ("90085", "1205-22-040", "İSG saha denetim raporları", "11", "1008", "10/05/2022", "15/05/2022", "22910", "H10.014", "AYGAZ A.Ş.", "Depoda", "BEKLİYOR", 2037, "INTERNAL", 0),
            ])

        now_str = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (1, ?)", (now_str,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.critical(f"Kritik Migration Hatası: {e}")
        st.error("Veritabanı şeması başlatılamadı. Veri bütünlüğünü korumak adına uygulama durduruldu.")
        st.stop()
    finally:
        conn.close()

execute_migrations()

# =========================================================
# 3. GÜVENLİ VERİ ERİŞİMİ VE SHA-256 AUDIT ENGINE
# =========================================================
def read_df(query: str, params: tuple | list = ()) -> pd.DataFrame:
    conn = get_db()
    try:
        return pd.read_sql_query(query, conn, params=params)
    except Exception as e:
        logger.error(f"SQL Çalıştırma Hatası: {e} | Sorgu: {query} | Parametreler: {params}")
        st.error("Veri okunurken bir hata oluştu.")
        return pd.DataFrame()
    finally:
        conn.close()

def audit(user: str, action: str, details: str, object_id: str = "", result: str = "SUCCESS") -> None:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        now_str = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
        last_row = cursor.execute("SELECT event_hash FROM archive_audit ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = last_row[0] if (last_row and last_row[0]) else "0" * 64
        
        raw_payload = f"{now_str}|{user}|{action}|{details}|{object_id}|{SESSION_ID}|{result}|{prev_hash}"
        event_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
        
        cursor.execute("""
            INSERT INTO archive_audit (timestamp, user, action_type, details, object_id, session_id, result, previous_hash, event_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (now_str, user, action, details, object_id, SESSION_ID, result, prev_hash, event_hash))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Audit loglama hatası: {e}")
    finally:
        conn.close()

def verify_audit_hash_chain() -> tuple[bool, str]:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, timestamp, user, action_type, details, object_id, session_id, result, previous_hash, event_hash 
            FROM archive_audit ORDER BY id ASC
        """)
        rows = cursor.fetchall()
        if not rows:
            return True, "Denetim kaydı bulunmuyor."
        
        expected_prev = "0" * 64
        for r in rows:
            r_id, r_time, r_user, r_act, r_det, r_obj, r_sess, r_res, r_prev, r_event = r
            if r_prev != expected_prev:
                return False, f"Kayıt #{r_id}: Önceki hash değeri eşleşmiyor."
            
            raw_payload = f"{r_time}|{r_user}|{r_act}|{r_det or ''}|{r_obj or ''}|{r_sess or ''}|{r_res or 'SUCCESS'}|{r_prev}"
            calc_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
            if calc_hash != r_event:
                return False, f"Kayıt #{r_id}: SHA-256 imzası hesaplanan değer ile uyuşmuyor."
            
            expected_prev = r_event
        return True, f"Toplam {len(rows)} adet denetim kaydının hash zinciri doğrulandı."
    except Exception as e:
        logger.error(f"Hash zinciri doğrulama hatası: {e}")
        return False, f"Doğrulama sırasında hata oluştu: {e}"
    finally:
        conn.close()

# =========================================================
# 4. MERKEZİ RBAC VE YETKİ KONTROL MOTORU
# =========================================================
def normalize_auth_codes(auth_codes: Any) -> set[str]:
    if not auth_codes or pd.isna(auth_codes):
        return set()
    return {code.strip().upper() for code in str(auth_codes).split(",") if code.strip()}

def is_admin_user(user_row: pd.Series) -> bool:
    role = str(user_row.get("role_desc", "") or "").strip().lower()
    auth_codes = normalize_auth_codes(user_row.get("auth_codes", ""))
    return ("admin" in role or "yönetici" in role or "ADMIN" in auth_codes or "*" in auth_codes)

def has_permission(user_row: pd.Series, permission: str) -> bool:
    permission = permission.strip().upper()
    auth_codes = normalize_auth_codes(user_row.get("auth_codes", ""))
    if is_admin_user(user_row):
        return True
    return permission in auth_codes

def can_manage_definitions(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "TANIM_YONETIM")

def can_manage_requests(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "TALEP_YONETIM") or has_permission(user_row, "REQUEST_MANAGE")

def can_create_destruction_request(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "IMHA_TALEP") or has_permission(user_row, "IMHA") or has_permission(user_row, "DESTRUCTION")

def can_approve_destruction(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "IMHA_ONAY") or has_permission(user_row, "IMHA") or has_permission(user_row, "DESTRUCTION")

def can_manage_destruction(user_row: pd.Series) -> bool:
    return can_create_destruction_request(user_row) or can_approve_destruction(user_row)

def can_view_reports(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "RAPOR_GORUNTULE") or has_permission(user_row, "REPORTS")

def can_view_audit(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "DENETIM") or has_permission(user_row, "AUDIT")

def can_manage_legal_hold(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "LEGAL_HOLD")

def assert_unit_access(active_row: pd.Series, target_unit: str) -> bool:
    user_unit = str(active_row.get("unit_code", "")).strip().upper()
    if user_unit == "ALL":
        return True
    return user_unit == str(target_unit).strip().upper()

def enforce_permission(active_row: pd.Series, permission: str, target_unit: str | None = None) -> None:
    if not has_permission(active_row, permission):
        audit(str(active_row.get("username")), "Yetkisiz Islem Denemesi", f"Eksik yetki: {permission}", result="BLOCKED")
        st.error(f"Güvenlik Uyarısı: Bu işlem için '{permission}' yetkiniz bulunmamaktadır.")
        st.stop()
    if target_unit is not None and not assert_unit_access(active_row, target_unit):
        audit(str(active_row.get("username")), "Yetkisiz Kapsam Denemesi", f"Yetkisiz birim: {target_unit}", result="BLOCKED")
        st.error(f"Güvenlik Uyarısı: '{target_unit}' birimine erişim yetkiniz bulunmamaktadır.")
        st.stop()

# =========================================================
# 5. SAKLAMA SÜRESİ VE OLAY BAZLI HESAPLAMA MOTORU
# =========================================================
def parse_date_string(date_str: str) -> tuple[int | None, int | None, int | None]:
    if not date_str or pd.isna(date_str):
        return None, None, None
    s = str(date_str).strip()
    m_tr = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$", s)
    if m_tr:
        return int(m_tr.group(3)), int(m_tr.group(2)), int(m_tr.group(1))
    m_iso = re.match(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$", s)
    if m_iso:
        return int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
    return None, None, None

def get_active_definitions() -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, Any]]]:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT code, name FROM institutions WHERE active = 1")
        inst_dict = {str(r[0]).strip(): str(r[1]).strip() for r in cursor.fetchall()}

        cursor.execute("SELECT code, name FROM units WHERE active = 1")
        unit_dict = {str(r[0]).strip(): str(r[1]).strip() for r in cursor.fetchall()}

        cursor.execute("SELECT series_code, name, retention_year, unit_code, trigger_event, legal_basis FROM series WHERE active = 1")
        series_dict = {
            str(r[0]).strip(): {
                "name": str(r[1]).strip(),
                "retention_year": int(r[2]) if r[2] is not None else 10,
                "unit_code": str(r[3]).strip(),
                "trigger_event": str(r[4] or "Dosyanın Kapanışı").strip(),
                "legal_basis": str(r[5] or "").strip()
            } for r in cursor.fetchall()
        }
        return inst_dict, unit_dict, series_dict
    finally:
        conn.close()

def compute_retention_year(series_code: str, first_date: str, last_date: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT retention_year, legal_basis, trigger_event FROM series WHERE series_code = ? AND active = 1", (series_code,))
        row = cursor.fetchone()
        if not row:
            return CURRENT_YEAR + 10
        ret_year = int(row[0]) if row[0] is not None else 10
        legal_basis = str(row[1] or "").lower()
        trigger_event = str(row[2] or "").lower()

        if ret_year >= 99 or "süresiz" in legal_basis:
            return 9999

        # Olay tetikleyicisine ve tarihlere göre başlangıç yılını seç
        y_last, _, _ = parse_date_string(last_date)
        y_first, _, _ = parse_date_string(first_date)

        if "düzenlenme" in trigger_event or "tarih" in trigger_event:
            base_year = y_first or y_last or CURRENT_YEAR
        else:
            base_year = y_last or y_first or CURRENT_YEAR

        return base_year + ret_year
    except Exception as e:
        logger.error(f"Saklama süresi hesaplama hatası: {e}")
        return CURRENT_YEAR + 10
    finally:
        conn.close()

# =========================================================
# 6. IMPORT NORMALIZER VE EXCEL SERVİSİ
# =========================================================
def normalize_import_val(val: Any, default: str = "") -> str:
    if val is None or pd.isna(val):
        return default
    s = str(val).strip()
    if s.lower() in ("nan", "none", "nat", "null"):
        return default
    return s

def normalize_int_val(val: Any, default: int) -> int:
    if val is None or pd.isna(val):
        return default
    try:
        s = str(val).strip().split(".")[0]
        return int(s)
    except Exception:
        return default

def convert_df_to_excel(sheets_dict: dict[str, pd.DataFrame]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in sheets_dict.items():
            clean_sheet = str(sheet_name)[:31]
            df.to_excel(writer, index=False, sheet_name=clean_sheet)
    return output.getvalue()

def download_excel(label: str, dataframe: pd.DataFrame, filename: str, sheet_name: str = "Arşiv Kataloğu", extra_sheets: dict | None = None, user: str = "local\\admin") -> None:
    try:
        sheets = {sheet_name: dataframe}
        if extra_sheets:
            sheets.update(extra_sheets)
        excel_data = convert_df_to_excel(sheets)
        audit(user, "Excel Dışa Aktarma", f"{filename} ({len(dataframe)} kayıt)", object_id=filename)
        st.download_button(
            label=label,
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        logger.error(f"Excel dışa aktarma hatası: {e}")
        st.error("Excel dosyası hazırlanırken bir hata oluştu.")

def logo_data_uri() -> str:
    logo_path = BASE_DIR / "Aygaz.png"
    if logo_path.exists():
        encoded_logo = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded_logo}"
    return ""

def wordmark_data_uri() -> str:
    wordmark_path = BASE_DIR / "aygaz_logo.jpg"
    if wordmark_path.exists():
        encoded_wordmark = base64.b64encode(wordmark_path.read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded_wordmark}"
    return ""

# =========================================================
# 7. AUTHENTICATION & DEMO/PROD AYRIM KATMANI
# =========================================================
users_df = read_df("SELECT id, username, full_name, unit_code, auth_codes, role_desc, active FROM user_permissions WHERE active = 1 ORDER BY id")
if users_df.empty:
    users_df = pd.DataFrame([{"id": 1, "username": "local\\admin", "full_name": "Arşiv Yöneticisi", "unit_code": "ALL", "auth_codes": "*", "role_desc": "Yönetici", "active": 1}])

with st.sidebar:
    sidebar_wordmark = wordmark_data_uri()
    sidebar_brand = (
        f'<img src="{sidebar_wordmark}" alt="AYGAZ" style="width:148px;height:auto;display:block;margin:0 0 12px -4px">'
        if sidebar_wordmark else '<div class="brand-mark">AYGAZ</div>'
    )
    st.markdown(
        f'<div class="brand">{sidebar_brand}'
        f'<div class="brand-name">Arşiv Sistemi</div>'
        f'<div class="brand-meta">AMBARLI OPERASYON MERKEZİ</div></div>',
        unsafe_allow_html=True
    )

    # Üretim (PRODUCTION) modunda kimlik kurumsal SSO başlığından alınır
    if ENVIRONMENT == "PRODUCTION":
        sso_user = os.getenv("REMOTE_USER", "").strip() or os.getenv("HTTP_X_AUTHENTICATED_USER", "unknown_user")
        matched_users = users_df[users_df["username"].str.lower() == sso_user.lower()]
        if not matched_users.empty:
            active_row = matched_users.iloc[0]
        else:
            st.error("Kurumsal SSO ile eşleşen aktif kullanıcı hesabı bulunamadı.")
            st.stop()
        st.caption(f"Kurumsal Kimlik: {active_row['full_name']}")
    else:
        # DEMO modunda kontrollü kullanıcı seçimi
        user_labels = [f"{row.full_name} · {row.unit_code}" for row in users_df.itertuples()]
        configured_user = os.getenv("AIBS_USER", "").casefold()
        default_index = next((index for index, row in enumerate(users_df.itertuples()) if str(row.username).casefold() == configured_user), 0)

        selected_user_label = st.selectbox("Kullanıcı", user_labels, index=default_index, label_visibility="visible")
        active_row = users_df.iloc[user_labels.index(selected_user_label)]

    active_name = str(active_row["full_name"])
    active_unit = str(active_row["unit_code"]).strip()
    active_user = str(active_row["username"]).strip()
    is_admin = is_admin_user(active_row)

    if st.session_state.get("last_logged_user") != active_user:
        st.session_state["last_logged_user"] = active_user
        audit(active_user, "Kullanıcı Oturumu Değiştirildi", f"{active_name} ({active_unit}) seçildi.", object_id=active_user)

    st.caption(f"{active_row['role_desc']} · {active_unit}")
    st.markdown("---")

    menu_options = ["Katalog", "İşlem Kuyruğu"]
    if can_manage_definitions(active_row):
        menu_options.append("Tanımlar")
    if can_manage_destruction(active_row):
        menu_options.append("Saklama ve imha")
    if can_view_reports(active_row):
        menu_options.append("Günlükler")
    if can_view_audit(active_row):
        menu_options.append("Denetim izi")

    menu = st.radio("Çalışma alanı", menu_options, label_visibility="visible")
    st.markdown("---")
    st.caption("Sistem durumu")
    st.markdown('<div style="color:#ffffff;font-size:12px;font-weight:600;">Veritabanı bağlı</div>', unsafe_allow_html=True)
    st.caption(suanki_zaman().strftime("Son senkronizasyon  %d.%m.%Y · %H:%M"))

# =========================================================
# 8. ÜST BİLGİ PANELİ (TOPBAR)
# =========================================================
user_initial = active_name[:1].upper() if active_name else "K"
scope_label = "Tüm birimler" if active_unit == "ALL" else f"Birim kapsamı: {active_unit}"
logo_src = logo_data_uri()
logo_markup = f'<img src="{logo_src}" alt="Aygaz logosu" style="width:34px;height:34px;object-fit:contain">' if logo_src else '<div class="aygaz-symbol">A</div>'
st.markdown(f'<div class="topbar"><div class="aygaz-lockup">{logo_markup}<span>AYGAZ ARŞİV SİSTEMİ</span></div><div class="topbar-user"><div class="topbar-user-dot">{user_initial}</div><span>{active_name}</span><span class="mono" style="color:#687984;font-size:10px">{scope_label}</span></div></div>', unsafe_allow_html=True)

st.markdown(
    '<div class="scope">'
    '<strong>DEMONSTRASYON SÜRÜMÜ</strong> · '
    'Bu sürüm test ve sunum amaçlıdır. Üretim ortamına alınmadan önce '
    'kurumsal kimlik doğrulama, yetkilendirme, veri güvenliği ve kapsamlı '
    'denetim/loglama mekanizmaları uygulanmalıdır.'
    '</div>',
    unsafe_allow_html=True
)

scope_sql = " AND unit_code = ?" if active_unit != "ALL" else ""
scope_params = (active_unit,) if active_unit != "ALL" else ()
scoped_count_df = read_df("SELECT COUNT(*) AS value FROM aygaz_main_archive WHERE 1=1" + scope_sql, scope_params)
scoped_count = scoped_count_df.iloc[0]["value"] if not scoped_count_df.empty else 0

open_requests_df = read_df("SELECT COUNT(*) AS value FROM archive_requests WHERE status NOT IN ('Tamamlandı / İade', 'Teslim Edildi', 'İptal / Red')" + scope_sql, scope_params)
open_requests = open_requests_df.iloc[0]["value"] if not open_requests_df.empty else 0

custody_count_df = read_df("SELECT COUNT(*) AS value FROM aygaz_main_archive WHERE status = 'Zimmette'" + scope_sql, scope_params)
custody_count = custody_count_df.iloc[0]["value"] if not custody_count_df.empty else 0

retention_count_df = read_df("SELECT COUNT(*) AS value FROM aygaz_main_archive WHERE retention_end_year <= ? AND (destruction_status IS NULL OR destruction_status != 'İMHA EDİLDİ')" + scope_sql, (CURRENT_YEAR,) + scope_params)
retention_count = retention_count_df.iloc[0]["value"] if not retention_count_df.empty else 0

def header(title: str, description: str) -> None:
    st.markdown(f'<div class="page-head"><div><div class="eyebrow">AYGAZ ARŞİV SİSTEMİ / {menu.upper()}</div><h1>{title}</h1><p>{description}</p></div><div class="stamp">{formatli_tarih()}</div></div>', unsafe_allow_html=True)

# =========================================================
# 9. MENÜ: KATALOG
# =========================================================
if menu == "Katalog":
    header("Arşiv kataloğu", "Belgeyi adıyla değil, fiziksel hayat döngüsüyle bulun.")
    metrics = [
        ("Toplam Kayıt", f"{scoped_count:,}", "yetki kapsamındaki kayıtlar"),
        ("Aktif Talep", f"{open_requests}", "işlem kuyruğunda"),
        ("Zimmette", f"{custody_count}", "kullanıcıda aktif"),
        ("Süresi Dolan", f"{retention_count}", f"{CURRENT_YEAR} ve öncesi")
    ]
    columns = st.columns(4)
    for column, (label, value, note) in zip(columns, metrics):
        with column:
            st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    left, right = st.columns([7, 3])
    with left:
        search = st.text_input("Katalogda ara", placeholder="Kayıt no, belge adı, kutu veya raf...", label_visibility="collapsed")
        f1, f2, f3 = st.columns([2, 2, 1])
        with f1: status = st.selectbox("Durum", ["Tümü", "Depoda", "Zimmette", "İmha Listesinde"])
        with f2: unit = st.text_input("Birim kodu", placeholder="Örn. 1004")
        with f3: limit = st.selectbox("Görünüm", [25, 50, 100])
        
        query = """
            SELECT doc_reg_no AS [Kayıt No], doc_no AS [Dosya No], doc_name AS [Belge], 
                   series_code AS [Seri], unit_code AS [Birim], first_doc_date AS [İlk Evrak Tarihi], 
                   last_doc_date AS [Son Evrak Tarihi], box_no AS [Kutu No], shelf_no AS [Yer No], 
                   institution AS [Kurum], status AS [Durum], destruction_status AS [İmha Durumu], 
                   CASE WHEN retention_end_year >= 9000 THEN 'Süresiz' ELSE CAST(retention_end_year AS TEXT) END AS [Saklama Sonu], 
                   legal_hold AS [Hukuki Engel] 
            FROM aygaz_main_archive WHERE 1=1
        """
        params: list[Any] = []
        if active_unit != "ALL": 
            query += " AND unit_code = ?"
            params.append(active_unit)
        
        if search.strip(): 
            query += " AND (doc_reg_no LIKE ? OR doc_no LIKE ? OR doc_name LIKE ? OR box_no LIKE ? OR shelf_no LIKE ?)"
            params.extend([f"%{search.strip()}%"] * 5)
            
        if status == "İmha Listesinde":
            query += " AND (destruction_status IS NULL OR destruction_status != 'İMHA EDİLDİ') AND CAST(retention_end_year AS INTEGER) <= ?"
            params.append(CURRENT_YEAR)
        elif status != "Tümü":
            query += " AND status = ?"
            params.append(status)
            
        if unit.strip() and active_unit == "ALL": 
            query += " AND unit_code LIKE ?"
            params.append(f"%{unit.strip()}%")
            
        catalog_df = read_df(query + " ORDER BY id DESC LIMIT ?", params + [limit])
        st.dataframe(catalog_df, width="stretch", hide_index=True, height=390)
        st.caption(f"{len(catalog_df)} kayıt gösteriliyor · Filtreler doğrudan arşiv kataloğuna uygulanıyor")
        download_excel("Katalog Excel indir", catalog_df, "aygaz-arsiv-katalog.xlsx", user=active_user)
        
        inst_dict, unit_dict, series_dict = get_active_definitions()

        if is_admin or can_manage_definitions(active_row):
            with st.expander("Yeni arşiv kaydı"):
                with st.form("new_archive_record"):
                    a1, a2, a3 = st.columns(3)
                    with a1:
                        new_reg = st.text_input("Kayıt no")
                        new_doc_no = st.text_input("Dosya no")
                        new_doc_name = st.text_input("Belge adı")
                    with a2:
                        available_series = list(series_dict.keys())
                        new_series = st.selectbox("Seri Kodu", options=available_series, format_func=lambda x: f"{x} - {series_dict[x]['name']}")
                        
                        available_units = [u for u in unit_dict.keys() if assert_unit_access(active_row, u)]
                        if not available_units:
                            available_units = [active_unit]
                        new_unit = st.selectbox("Birim Kodu", options=available_units, format_func=lambda x: f"{x} - {unit_dict.get(x, x)}")
                        new_box = st.text_input("Kutu no")
                    with a3:
                        new_shelf = st.text_input("Raf / yer no")
                        new_first_date = st.text_input("İlk evrak tarihi", placeholder="GG/AA/YYYY")
                        new_last_date = st.text_input("Son evrak tarihi", placeholder="GG/AA/YYYY")
                    
                    if st.form_submit_button("Arşiv kaydını oluştur", type="primary"):
                        if not (new_reg.strip() and new_doc_name.strip() and new_unit.strip() and new_series.strip()):
                            st.error("Kayıt No, Belge Adı, Birim ve Seri alanları zorunludur.")
                        elif not assert_unit_access(active_row, new_unit.strip()):
                            st.error(f"Yetki sınırınız gereği yalnızca {active_unit} birimine kayıt ekleyebilirsiniz.")
                        elif new_unit.strip() not in unit_dict:
                            st.error(f"Seçilen birim kodu ({new_unit}) veritabanında aktif tanımlar arasında bulunamadı.")
                        elif new_series.strip() not in series_dict:
                            st.error(f"Seçilen seri kodu ({new_series}) veritabanında aktif tanımlar arasında bulunamadı.")
                        else:
                            conn = get_db()
                            now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                            calculated_end_year = compute_retention_year(new_series.strip(), new_first_date.strip(), new_last_date.strip())
                            
                            try:
                                conn.execute("""
                                    INSERT INTO aygaz_main_archive 
                                    (doc_reg_no, doc_no, doc_name, series_code, unit_code, first_doc_date, last_doc_date, box_no, shelf_no, institution, status, destruction_status, retention_end_year, created_by, created_at) 
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (new_reg.strip(), new_doc_no.strip(), new_doc_name.strip(), new_series.strip(), new_unit.strip(), new_first_date.strip(), new_last_date.strip(), new_box.strip(), new_shelf.strip(), "AYGAZ A.Ş.", "Depoda", "BEKLİYOR", calculated_end_year, active_user, now_stamp))
                                conn.commit()
                                audit(active_user, "Arşiv kaydı oluşturma", f"{new_reg} · {new_doc_name} (Saklama Bitiş: {calculated_end_year})", object_id=new_reg.strip())
                                st.success(f"Arşiv kaydı oluşturuldu. Saklama Bitiş Yılı: {calculated_end_year if calculated_end_year < 9000 else 'Süresiz'}")
                                st.rerun()
                            except sqlite3.IntegrityError:
                                st.error("Bu kayıt numarası sistemde zaten mevcut.")
                            finally:
                                conn.close()

            with st.expander("Toplu Arşiv Kaydı Yükle (Excel/CSV)"):
                uploaded_file = st.file_uploader("Eski sistemden dışa aktarılan Excel/CSV dosyasını seçin", type=["xlsx", "xls", "csv"])
                if uploaded_file:
                    try:
                        import_df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv") else pd.read_excel(uploaded_file)
                        st.write("Yüklenecek Veri Önizlemesi:", import_df.head(3))
                        if st.button("Veritabanına Aktarımı Başlat", type="primary"):
                            conn = get_db()
                            cursor = conn.cursor()
                            inserted_count = 0
                            updated_count = 0
                            rejected_rows: list[str] = []
                            now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                            
                            try:
                                cursor.execute("BEGIN TRANSACTION")
                                for idx, row in import_df.iterrows():
                                    row_num = idx + 2
                                    row_reg = normalize_import_val(row.get("Kayıt No"))
                                    doc_name_val = normalize_import_val(row.get("Belge", row.get("Belge Adı")))
                                    row_unit = normalize_import_val(row.get("Birim"))
                                    series_val = normalize_import_val(row.get("Seri"))
                                    inst_val = normalize_import_val(row.get("Kurum"), default="AYGAZ A.Ş.")
                                    status_val = normalize_import_val(row.get("Durum"), default="Depoda")
                                    first_d_val = normalize_import_val(row.get("İlk Evrak Tarihi"))
                                    last_d_val = normalize_import_val(row.get("Son Evrak Tarihi"))

                                    if not row_reg:
                                        rejected_rows.append(f"Satır {row_num}: Kayıt No boş olamaz.")
                                        continue
                                    if not doc_name_val:
                                        rejected_rows.append(f"Satır {row_num} (Kayıt {row_reg}): Belge adı boş bırakılamaz.")
                                        continue
                                    if not row_unit or row_unit not in unit_dict:
                                        rejected_rows.append(f"Satır {row_num} (Kayıt {row_reg}): Birim kodu ({row_unit}) sistemde aktif tanımlar arasında yok.")
                                        continue
                                    if not assert_unit_access(active_row, row_unit):
                                        rejected_rows.append(f"Satır {row_num} (Kayıt {row_reg}): Birim yetki kapsamınızın ({active_unit}) dışındadır.")
                                        continue
                                    if not series_val or series_val not in series_dict:
                                        rejected_rows.append(f"Satır {row_num} (Kayıt {row_reg}): Seri kodu ({series_val}) sistemde aktif tanımlar arasında yok.")
                                        continue
                                    if inst_val not in inst_dict and inst_val not in inst_dict.values():
                                        rejected_rows.append(f"Satır {row_num} (Kayıt {row_reg}): Kurum ({inst_val}) sistemde tanımlı değil.")
                                        continue
                                    if status_val not in ("Depoda", "Zimmette", "İmha Bekliyor", "İmha Edildi"):
                                        rejected_rows.append(f"Satır {row_num} (Kayıt {row_reg}): Durum değeri ('{status_val}') geçersiz.")
                                        continue

                                    # Tarih format doğrulama
                                    if first_d_val and parse_date_string(first_d_val)[0] is None:
                                        rejected_rows.append(f"Satır {row_num} (Kayıt {row_reg}): İlk evrak tarihi geçersiz formatta.")
                                        continue
                                    if last_d_val and parse_date_string(last_d_val)[0] is None:
                                        rejected_rows.append(f"Satır {row_num} (Kayıt {row_reg}): Son evrak tarihi geçersiz formatta.")
                                        continue

                                    doc_no_val = normalize_import_val(row.get("Dosya No"))
                                    box_val = normalize_import_val(row.get("Kutu No"))
                                    shelf_val = normalize_import_val(row.get("Yer No"))
                                    
                                    # Saklama süresini hesapla veya doğrula
                                    provided_ret = row.get("Saklama Sonu")
                                    if provided_ret is not None and not pd.isna(provided_ret) and str(provided_ret).strip().lower() not in ("süresiz", "nan", "none", ""):
                                        ret_end_val = normalize_int_val(provided_ret, default=compute_retention_year(series_val, first_d_val, last_d_val))
                                    else:
                                        ret_end_val = compute_retention_year(series_val, first_d_val, last_d_val)

                                    cursor.execute("SELECT id, unit_code FROM aygaz_main_archive WHERE doc_reg_no = ?", (row_reg,))
                                    existing = cursor.fetchone()
                                    if existing:
                                        existing_unit = existing[1]
                                        if not assert_unit_access(active_row, existing_unit):
                                            rejected_rows.append(f"Satır {row_num} (Kayıt {row_reg}): Mevcut kayıt birim kapsamınız dışındadır.")
                                            continue
                                        cursor.execute("""
                                            UPDATE aygaz_main_archive SET
                                                doc_no = ?, doc_name = ?, series_code = ?, unit_code = ?,
                                                first_doc_date = ?, last_doc_date = ?, box_no = ?, shelf_no = ?,
                                                institution = ?, status = ?, retention_end_year = ?,
                                                updated_by = ?, updated_at = ?
                                            WHERE doc_reg_no = ?
                                        """, (doc_no_val, doc_name_val, series_val, row_unit, first_d_val, last_d_val, box_val, shelf_val, inst_val, status_val, ret_end_val, active_user, now_stamp, row_reg))
                                        updated_count += 1
                                    else:
                                        cursor.execute("""
                                            INSERT INTO aygaz_main_archive 
                                            (doc_reg_no, doc_no, doc_name, series_code, unit_code, first_doc_date, last_doc_date, box_no, shelf_no, institution, status, destruction_status, retention_end_year, created_by, created_at)
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """, (row_reg, doc_no_val, doc_name_val, series_val, row_unit, first_d_val, last_d_val, box_val, shelf_val, inst_val, status_val, "BEKLİYOR", ret_end_val, active_user, now_stamp))
                                        inserted_count += 1

                                conn.commit()
                                audit(active_user, "Toplu Veri İçe Aktarma", f"Eklendi: {inserted_count}, Güncellendi: {updated_count}, Reddedildi: {len(rejected_rows)}")
                                st.success(f"Aktarım tamamlandı. Eklenen: {inserted_count}, Güncellenen: {updated_count}, Hatalı/Reddedilen: {len(rejected_rows)}")
                                if rejected_rows:
                                    st.warning("Aşağıdaki satırlar doğrulama kurallarına uymadığı için içeri alınmadı:\n" + "\n".join(rejected_rows[:10]))
                                    if len(rejected_rows) > 10:
                                        st.caption(f"... ve {len(rejected_rows) - 10} adet daha kayıt reddedildi.")
                                st.rerun()
                            except Exception as import_err:
                                conn.rollback()
                                logger.error(f"Toplu aktarım hatası: {import_err}")
                                st.error("İçe aktarım sırasında bir hata oluştu ve veri bütünlüğünü korumak adına tüm işlem geri alındı.")
                            finally:
                                conn.close()
                    except Exception as e:
                        logger.error(f"Dosya okuma hatası: {e}")
                        st.error("Dosya biçimi okunamadı. Lütfen geçerli bir Excel veya CSV dosyası yükleyiniz.")

    with right:
        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">Kayıt Detayı</div></div>', unsafe_allow_html=True)
        if not catalog_df.empty:
            selected_reg = st.selectbox("İncelenecek kayıt", catalog_df["Kayıt No"].tolist(), label_visibility="collapsed")
            selected = catalog_df[catalog_df["Kayıt No"] == selected_reg].iloc[0]
            
            if st.session_state.get("last_viewed_doc") != selected_reg:
                st.session_state["last_viewed_doc"] = selected_reg
                audit(active_user, "Kayıt Görüntüleme", f"Kayıt No: {selected['Kayıt No']} incelendi", object_id=str(selected["Kayıt No"]))

            hold_val = int(selected.get("Hukuki Engel", 0))
            hold_txt = "AKTİF KİLİT" if hold_val == 1 else "KİLİT YOK"
            hold_color = "#d47d36" if hold_val == 1 else "#148b80"
            
            st.markdown(f'<div class="eyebrow">KAYIT / {selected["Kayıt No"]}</div><h3>{selected["Belge"]}</h3><p><b>Fiziksel konum</b><br><span class="mono">KUTU {selected["Kutu No"]} · RAF {selected["Yer No"]}</span></p><p><b>Birim</b> {selected["Birim"]}<br><b>Seri</b> {selected["Seri"]}<br><b>Saklama Sonu:</b> {selected["Saklama Sonu"]}<br><b>Hukuki Durum:</b> <span style="color:{hold_color};font-weight:700">{hold_txt}</span></p><div style="color:#0072bc;font-weight:700">● {selected["Durum"]}</div>', unsafe_allow_html=True)

            if can_manage_legal_hold(active_row):
                if hold_val == 1:
                    with st.form(f"rel_hold_{selected_reg}"):
                        rel_reason = st.text_input("Kaldırma Gerekçesi")
                        if st.form_submit_button("Hukuki Kilidi Kaldır", type="primary"):
                            enforce_permission(active_row, "LEGAL_HOLD", str(selected["Birim"]))
                            if not rel_reason.strip():
                                st.error("Hukuki kilidi kaldırmak için geçerli bir gerekçe girmelisiniz.")
                            else:
                                conn = get_db()
                                cursor = conn.cursor()
                                scope_where = " AND unit_code = ?" if active_unit != "ALL" else ""
                                scope_p = [f"Kaldırıldı: {rel_reason.strip()}", active_user, suanki_zaman().strftime("%Y-%m-%d %H:%M:%S"), selected['Kayıt No']]
                                if active_unit != "ALL":
                                    scope_p.append(active_unit)
                                cursor.execute(f"""
                                    UPDATE aygaz_main_archive SET 
                                        legal_hold = 0, legal_hold_reason = ?, legal_hold_by = ?, legal_hold_at = ?
                                    WHERE doc_reg_no = ? {scope_where}
                                """, tuple(scope_p))
                                if cursor.rowcount == 1:
                                    conn.commit()
                                    audit(active_user, "Hukuki Kilit Kaldırma", f"Kayıt {selected['Kayıt No']} kilidi kaldırıldı. Gerekçe: {rel_reason.strip()}", object_id=str(selected['Kayıt No']))
                                    st.success("Hukuki kilit kaldırıldı.")
                                    st.rerun()
                                else:
                                    conn.rollback()
                                    st.error("Kilit kaldırma işlemi yetki veya kayıt durumu nedeniyle başarısız oldu.")
                                conn.close()
                else:
                    with st.form(f"set_hold_{selected_reg}"):
                        set_reason = st.text_input("Bloke Gerekçesi (Dava, Teftiş vb.)")
                        if st.form_submit_button("Hukuki Kilit Koy (Hold)", type="primary"):
                            enforce_permission(active_row, "LEGAL_HOLD", str(selected["Birim"]))
                            if not set_reason.strip():
                                st.error("Hukuki kilit koyabilmek için zorunlu gerekçe girmelisiniz.")
                            else:
                                conn = get_db()
                                cursor = conn.cursor()
                                scope_where = " AND unit_code = ?" if active_unit != "ALL" else ""
                                scope_p = [set_reason.strip(), active_user, suanki_zaman().strftime("%Y-%m-%d %H:%M:%S"), selected['Kayıt No']]
                                if active_unit != "ALL":
                                    scope_p.append(active_unit)
                                cursor.execute(f"""
                                    UPDATE aygaz_main_archive SET 
                                        legal_hold = 1, legal_hold_reason = ?, legal_hold_by = ?, legal_hold_at = ?
                                    WHERE doc_reg_no = ? {scope_where}
                                """, tuple(scope_p))
                                if cursor.rowcount == 1:
                                    conn.commit()
                                    audit(active_user, "Hukuki Kilit Koyma", f"Kayıt {selected['Kayıt No']} kilitlendi. Gerekçe: {set_reason.strip()}", object_id=str(selected['Kayıt No']))
                                    st.success("Hukuki kilit konuldu.")
                                    st.rerun()
                                else:
                                    conn.rollback()
                                    st.error("Kilit koyma işlemi yetki veya kayıt durumu nedeniyle gerçekleştirilemedi.")
                                conn.close()

            if st.button("Bu kayıt için talep aç", type="primary", width="stretch"): 
                st.session_state["request_doc_reg"] = str(selected['Kayıt No']).strip()
                st.session_state["request_doc_name"] = str(selected['Belge']).strip()
                st.session_state["request_open"] = True
                st.rerun()
        else: 
            st.info("Filtrelere uyan kayıt bulunamadı.")
        st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.get("request_open"):
        st.markdown("### Yeni erişim talebi")
        with st.form("catalog_request"):
            c1, c2 = st.columns(2)
            with c1: 
                req_reg = st.session_state.get("request_doc_reg", "")
                req_title = st.session_state.get("request_doc_name", "")
                st.text_input("Kayıt No", value=req_reg, disabled=True)
                st.text_input("Belge Adı", value=req_title, disabled=True)
                request_type = st.selectbox("Erişim biçimi", ["Fiziksel zimmet", "Dijital tarama (PDF)"])
            with c2: 
                request_urgency = st.selectbox("Öncelik", ["Normal", "Acil", "Kritik"])
                request_note = st.text_area("Gerekçe", placeholder="İnceleme amacı veya teslim notu...")
            if st.form_submit_button("Talebi kuyruğa al", type="primary"):
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT unit_code, doc_name FROM aygaz_main_archive WHERE doc_reg_no = ?", (req_reg,))
                doc_record = cursor.fetchone()
                if not doc_record:
                    st.error("Talep açılmak istenen arşiv kaydı veritabanında bulunamadı.")
                elif not assert_unit_access(active_row, doc_record[0]):
                    st.error(f"Bu kayıt {doc_record[0]} birimine aittir. Kapsamınız dışındaki kayda talep açamazsınız.")
                else:
                    request_no = f"TR-{uuid.uuid4().hex[:8].upper()}"
                    now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                    doc_item_label = f"#{req_reg} · {doc_record[1]}"
                    cursor.execute("""
                        INSERT INTO archive_requests (req_no, requester, requester_username, unit_code, doc_reg_no, doc_item, delivery_type, urgency, status, notes, created_at) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (request_no, active_name, active_user, doc_record[0], req_reg, doc_item_label, request_type, request_urgency, "Onay Bekliyor", request_note, now_stamp))
                    conn.commit()
                    audit(active_user, "Erişim Talebi Oluşturma", f"{request_no} · {doc_item_label}", object_id=request_no)
                    st.session_state["request_open"] = False
                    st.success(f"{request_no} numaralı talep kuyruğa alındı.")
                    st.rerun()
                conn.close()

# =========================================================
# 10. MENÜ: İŞLEM KUYRUĞU (GEÇİŞ MATRİSİ KONTROLLÜ)
# =========================================================
elif menu == "İşlem Kuyruğu":
    header("İşlem kuyruğu", "Arşiv belgelerine yönelik erişim taleplerini, zimmet ve iade hareketlerini takip et ve yönet.")
    can_manage = can_manage_requests(active_row)
    
    filter_sql = ""
    filter_params: list[Any] = []
    if not can_manage:
        filter_sql = " AND (requester_username = ? OR requester = ?)"
        filter_params.extend([active_user, active_name])
    elif active_unit != "ALL":
        filter_sql = " AND unit_code = ?"
        filter_params.append(active_unit)

    queue_df = read_df(
        """
        SELECT id, req_no AS [Talep], requester AS [Talep Eden], requester_username AS [Sicil], unit_code AS [Birim],
               doc_item AS [Kayıt], delivery_type AS [Teslim], urgency AS [Öncelik],
               status AS [Durum], created_at AS [Oluşturuldu], notes AS [Not]
        FROM archive_requests WHERE 1=1 """ + filter_sql + """ ORDER BY id DESC
        """,
        filter_params
    )

    q1, q2, q3 = st.columns(3)
    q1.metric("Toplam Talep", len(queue_df))
    q2.metric("Onay Bekleyen", int((queue_df["Durum"] == "Onay Bekliyor").sum()) if not queue_df.empty and "Durum" in queue_df else 0)
    q3.metric("Acil İşler", int(queue_df["Öncelik"].isin(["Acil", "Kritik"]).sum()) if not queue_df.empty and "Öncelik" in queue_df else 0)
    st.markdown("<br>", unsafe_allow_html=True)

    if queue_df.empty or "Talep" not in queue_df.columns:
        st.info("Görüntülenecek talep bulunmamaktadır.")
    else:
        st.dataframe(queue_df.drop(columns=["id", "Sicil"], errors="ignore"), width="stretch", hide_index=True, height=350)
        st.markdown("### Talep işlemleri")
        
        ALLOWED_TRANSITIONS = {
            "Onay Bekliyor": ["Hazırlanıyor", "İptal / Red"],
            "Hazırlanıyor": ["Kuryede", "İptal / Red"],
            "Kuryede": ["Teslim Edildi", "İptal / Red"],
            "Teslim Edildi": ["Tamamlandı / İade"],
            "Tamamlandı / İade": [],
            "İptal / Red": []
        }

        u1, u2, u3 = st.columns([2, 2, 1])
        with u1:
            selected_request = st.selectbox("Talep", queue_df["Talep"].tolist())
            cur_req_row = queue_df[queue_df["Talep"] == selected_request].iloc[0]
            current_status = str(cur_req_row["Durum"])
        with u2:
            possible_next = ALLOWED_TRANSITIONS.get(current_status, [])
            if not possible_next:
                st.info(f"Bu talep '{current_status}' durumundadır ve başka duruma geçirilemez.")
                new_status = None
            else:
                new_status = st.selectbox("Yeni durum", possible_next)
        with u3:
            if can_manage and new_status:
                if st.button("Güncelle", type="primary", width="stretch"):
                    enforce_permission(active_row, "TALEP_YONETIM", str(cur_req_row["Birim"]))
                    conn = get_db()
                    cursor = conn.cursor()
                    scope_where = " AND unit_code = ?" if active_unit != "ALL" else ""
                    scope_p = [new_status, selected_request, current_status]
                    if active_unit != "ALL":
                        scope_p.append(active_unit)
                    
                    cursor.execute(f"UPDATE archive_requests SET status = ? WHERE req_no = ? AND status = ? {scope_where}", tuple(scope_p))
                    if cursor.rowcount == 1:
                        if new_status == "Teslim Edildi":
                            cursor.execute("SELECT doc_reg_no FROM archive_requests WHERE req_no = ?", (selected_request,))
                            d_reg = cursor.fetchone()
                            if d_reg and d_reg[0]:
                                cursor.execute("UPDATE aygaz_main_archive SET status = 'Zimmette' WHERE doc_reg_no = ?", (d_reg[0],))
                        elif new_status == "Tamamlandı / İade":
                            cursor.execute("SELECT doc_reg_no FROM archive_requests WHERE req_no = ?", (selected_request,))
                            d_reg = cursor.fetchone()
                            if d_reg and d_reg[0]:
                                cursor.execute("UPDATE aygaz_main_archive SET status = 'Depoda' WHERE doc_reg_no = ?", (d_reg[0],))
                        conn.commit()
                        audit(active_user, "Talep Durumu Güncelleme", f"{selected_request} ({current_status} → {new_status})", object_id=selected_request)
                        st.success("Talep durumu güncellendi.")
                        st.rerun()
                    else:
                        conn.rollback()
                        st.error("Talep güncellenemedi: Durum değişmiş olabilir veya yetki kapsamınız yetersizdir.")
                    conn.close()
            elif not can_manage:
                st.caption("Talep durumunu yalnızca yetkili kullanıcılar güncelleyebilir.")

        st.markdown("### Talep içi mesajlaşma")
        message_df = read_df("SELECT sender AS [Gönderen], message AS [Mesaj], created_at AS [Tarih] FROM request_messages WHERE req_no = ? ORDER BY id ASC", params=[selected_request])
        if not message_df.empty:
            st.dataframe(message_df, width="stretch", hide_index=True)

        with st.form("request_message_form"):
            message = st.text_input("Mesaj", placeholder="Konum, teslimat veya inceleme notu...")
            if st.form_submit_button("Mesajı kaydet") and message.strip():
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT unit_code, requester_username, requester FROM archive_requests WHERE req_no = ?", (selected_request,))
                req_info = cursor.fetchone()
                if not req_info:
                    st.error("Talep bulunamadı.")
                else:
                    req_unit, req_usr, req_name = req_info[0], req_info[1], req_info[2]
                    is_owner = (req_usr == active_user or req_name == active_name)
                    has_scope = assert_unit_access(active_row, req_unit)
                    if not (can_manage and has_scope) and not is_owner:
                        st.error("Bu talebe mesaj ekleme yetkiniz bulunmamaktadır.")
                    else:
                        now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                        cursor.execute("INSERT INTO request_messages (req_no, sender, message, created_at) VALUES (?, ?, ?, ?)", (selected_request, active_name, message.strip(), now_stamp))
                        conn.commit()
                        audit(active_user, "Talep Mesajı Ekleme", f"{selected_request} talebine mesaj eklendi", object_id=selected_request)
                        st.success("Mesaj kaydedildi.")
                        st.rerun()
                conn.close()

# =========================================================
# 11. MENÜ: TANIMLAR
# =========================================================
elif menu == "Tanımlar" and can_manage_definitions(active_row):
    header("Tanımlar", "Mevcut Aygaz arşiv sınıflandırmasını bozmadan kurum, birim ve seri kayıtlarını incele.")
    definition_tabs = st.tabs(["Birimler", "Seriler", "Kurumlar", "Kullanıcılar"])
    
    with definition_tabs[0]:
        unit_search = st.text_input("Birimlerde ara", placeholder="Birim adı veya kodu...")
        unit_query = "SELECT id AS [ID], name AS [Birim Adı], code AS [Birim Kodu], inst_code AS [Kurum Kodu], inst_name AS [Kurum Adı] FROM units WHERE active = 1"
        unit_params: list[Any] = []
        if unit_search.strip():
            unit_query += " AND (name LIKE ? OR code LIKE ?)"
            unit_params.extend([f"%{unit_search.strip()}%"] * 2)
        st.dataframe(read_df(unit_query + " ORDER BY id", unit_params), width="stretch", hide_index=True, height=400)
        with st.expander("Yeni birim kaydı"):
            with st.form("new_unit"):
                new_unit_name = st.text_input("Birim adı")
                new_unit_code = st.text_input("Birim kodu")
                new_unit_inst = st.text_input("Kurum kodu", value="10")
                if st.form_submit_button("Birimi kaydet", type="primary") and new_unit_name.strip() and new_unit_code.strip():
                    enforce_permission(active_row, "TANIM_YONETIM")
                    conn = get_db()
                    try:
                        conn.execute("INSERT INTO units (name, code, inst_code, inst_name, active) VALUES (?, ?, ?, ?, 1)", (new_unit_name.strip(), new_unit_code.strip(), new_unit_inst.strip(), "AYGAZ A.Ş."))
                        conn.commit()
                        audit(active_user, "Birim Tanımı Ekleme", f"{new_unit_code} · {new_unit_name}", object_id=new_unit_code.strip())
                        st.success("Birim kaydedildi.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Bu birim kodu zaten kayıtlı.")
                    finally:
                        conn.close()

    with definition_tabs[1]:
        series_search = st.text_input("Serilerde ara", placeholder="Seri adı, kodu veya mevzuat...")
        series_query = "SELECT id AS [ID], name AS [Seri Adı], unit_code AS [Birim Kodu], unit_name AS [Birim], series_code AS [Seri Kodu], CASE WHEN retention_year >= 99 THEN 'Süresiz' ELSE CAST(retention_year AS TEXT) END AS [Saklama (Yıl)], legal_basis AS [Mevzuat Dayanağı], trigger_event AS [Süreç Tetikleyicisi] FROM series WHERE active = 1"
        series_params: list[Any] = []
        if series_search.strip():
            series_query += " AND (name LIKE ? OR series_code LIKE ? OR legal_basis LIKE ?)"
            series_params.extend([f"%{series_search.strip()}%"] * 3)
        st.dataframe(read_df(series_query + " ORDER BY id", series_params), width="stretch", hide_index=True, height=400)
        with st.expander("Yeni seri kaydı"):
            with st.form("new_series"):
                new_series_name = st.text_input("Seri adı")
                new_series_code = st.text_input("Seri kodu")
                new_series_unit = st.text_input("Birim kodu")
                new_series_is_permanent = st.checkbox("Süresiz Saklama")
                new_series_retention = st.number_input("Süre (yıl)", min_value=0, value=10, disabled=new_series_is_permanent)
                new_series_basis = st.text_input("Mevzuat dayanağı")
                new_series_trigger = st.text_input("Süreç tetikleyicisi", value="Dosyanın Kapanışı")
                if st.form_submit_button("Seriyi kaydet", type="primary") and new_series_name.strip() and new_series_code.strip():
                    enforce_permission(active_row, "TANIM_YONETIM")
                    conn = get_db()
                    try:
                        ret_to_save = 100 if new_series_is_permanent else int(new_series_retention)
                        conn.execute("INSERT INTO series (name, unit_code, unit_name, series_code, retention_year, legal_basis, trigger_event, active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)", (new_series_name.strip(), new_series_unit.strip(), "", new_series_code.strip(), ret_to_save, new_series_basis.strip(), new_series_trigger.strip()))
                        conn.commit()
                        audit(active_user, "Seri Tanımı Ekleme", f"{new_series_code} · {new_series_name}", object_id=new_series_code.strip())
                        st.success("Seri kaydedildi.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Bu seri kodu zaten kayıtlı.")
                    finally:
                        conn.close()

    with definition_tabs[2]:
        institution_search = st.text_input("Kurumlarda ara", placeholder="Kurum adı veya kodu...")
        institution_query = "SELECT id AS [ID], name AS [Kurum Adı], code AS [Kurum Kodu] FROM institutions WHERE active = 1"
        institution_params: list[Any] = []
        if institution_search.strip():
            institution_query += " AND (name LIKE ? OR code LIKE ?)"
            institution_params.extend([f"%{institution_search.strip()}%"] * 2)
        st.dataframe(read_df(institution_query + " ORDER BY id", institution_params), width="stretch", hide_index=True, height=400)
        with st.expander("Yeni kurum kaydı"):
            with st.form("new_institution"):
                new_institution_name = st.text_input("Kurum adı")
                new_institution_code = st.text_input("Kurum kodu")
                if st.form_submit_button("Kurumu kaydet", type="primary") and new_institution_name.strip() and new_institution_code.strip():
                    enforce_permission(active_row, "TANIM_YONETIM")
                    conn = get_db()
                    try:
                        conn.execute("INSERT INTO institutions (name, code, active) VALUES (?, ?, 1)", (new_institution_name.strip(), new_institution_code.strip()))
                        conn.commit()
                        audit(active_user, "Kurum Tanımı Ekleme", f"{new_institution_code} · {new_institution_name}", object_id=new_institution_code.strip())
                        st.success("Kurum kaydedildi.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Bu kurum kodu zaten kayıtlı.")
                    finally:
                        conn.close()

    with definition_tabs[3]:
        st.markdown("### Sistem Kullanıcıları ve Yetkilendirme (RBAC)")
        all_users = read_df("SELECT id AS [ID], username AS [Kullanıcı Adı], full_name AS [Ad Soyad], unit_code AS [Birim], auth_codes AS [Yetkiler], role_desc AS [Rol], active AS [Aktif] FROM user_permissions ORDER BY id")
        st.dataframe(all_users, width="stretch", hide_index=True)
        
        c_u1, c_u2 = st.columns(2)
        with c_u1:
            with st.expander("Yeni Kullanıcı Tanımla"):
                with st.form("new_user_form"):
                    u_name = st.text_input("Kullanıcı Adı / Sicil No")
                    u_fullname = st.text_input("Ad Soyad")
                    u_unit = st.text_input("Birim Kodu (Tümü için ALL)")
                    u_role = st.selectbox("Rol Tanımı", ["Arşiv Sorumlusu", "Birim Kullanıcısı", "Yönetici"])
                    u_auth = st.multiselect("Yetki Kodları", ["ADMIN", "TALEP_YONETIM", "IMHA_TALEP", "IMHA_ONAY", "DENETIM", "LEGAL_HOLD", "TANIM_YONETIM", "RAPOR_GORUNTULE", "ARASIRMA_EXPORT"], default=["TALEP_YONETIM"])
                    if st.form_submit_button("Kullanıcıyı Kaydet", type="primary") and u_name.strip() and u_fullname.strip():
                        enforce_permission(active_row, "ADMIN")
                        conn = get_db()
                        now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                        try:
                            conn.execute("""
                                INSERT INTO user_permissions (username, full_name, unit_code, auth_codes, role_desc, active, created_at, created_by) 
                                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                            """, (u_name.strip(), u_fullname.strip(), u_unit.strip(), ",".join(u_auth), u_role, now_stamp, active_user))
                            conn.commit()
                            audit(active_user, "Kullanıcı Tanımlama", f"Kullanıcı eklendi: {u_name} ({u_fullname}), Birim: {u_unit}, Rol: {u_role}, Yetkiler: {','.join(u_auth)}", object_id=u_name.strip())
                            st.success("Kullanıcı başarıyla kaydedildi.")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Bu kullanıcı adı zaten mevcut.")
                        finally:
                            conn.close()

        with c_u2:
            with st.expander("Kullanıcı Düzenle / Pasifleştir"):
                if not all_users.empty:
                    with st.form("edit_user_form"):
                        target_username = st.selectbox("Düzenlenecek Kullanıcı", all_users["Kullanıcı Adı"].tolist())
                        target_row = all_users[all_users["Kullanıcı Adı"] == target_username].iloc[0]
                        edit_fullname = st.text_input("Ad Soyad", value=str(target_row["Ad Soyad"]))
                        edit_unit = st.text_input("Birim Kodu", value=str(target_row["Birim"]))
                        edit_role = st.text_input("Rol Tanımı", value=str(target_row["Rol"]))
                        edit_auth = st.text_input("Yetki Kodları (virgülle ayırın)", value=str(target_row["Yetkiler"] or ""))
                        edit_active = st.checkbox("Aktif Durumda", value=bool(target_row["Aktif"] == 1))
                        if st.form_submit_button("Güncelle", type="primary"):
                            enforce_permission(active_row, "ADMIN")
                            conn = get_db()
                            cursor = conn.cursor()
                            cursor.execute("SELECT COUNT(*) FROM user_permissions WHERE active = 1 AND (LOWER(role_desc) LIKE '%yönetici%' OR LOWER(role_desc) LIKE '%admin%' OR auth_codes LIKE '%ADMIN%')")
                            active_admin_count = cursor.fetchone()[0]
                            is_target_admin = is_admin_user(target_row)
                            
                            if is_target_admin and not edit_active and active_admin_count <= 1:
                                st.error("Sistemdeki son aktif yönetici hesabı pasifleştirilemez.")
                            elif target_username == active_user and not edit_active:
                                st.error("Kendi aktif kullanıcı hesabınızı pasif duruma alamazsınız.")
                            else:
                                now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                                old_state = f"Ad Soyad: {target_row['Ad Soyad']}, Birim: {target_row['Birim']}, Rol: {target_row['Rol']}, Yetkiler: {target_row['Yetkiler']}, Aktif: {target_row['Aktif']}"
                                new_state = f"Ad Soyad: {edit_fullname.strip()}, Birim: {edit_unit.strip()}, Rol: {edit_role.strip()}, Yetkiler: {edit_auth.strip()}, Aktif: {1 if edit_active else 0}"
                                cursor.execute("""
                                    UPDATE user_permissions SET
                                        full_name = ?, unit_code = ?, role_desc = ?, auth_codes = ?, active = ?, updated_at = ?, updated_by = ?
                                    WHERE username = ?
                                """, (edit_fullname.strip(), edit_unit.strip(), edit_role.strip(), edit_auth.strip(), 1 if edit_active else 0, now_stamp, active_user, target_username))
                                conn.commit()
                                audit(active_user, "Kullanıcı Güncelleme", f"Kullanıcı: {target_username} | Eski: [{old_state}] -> Yeni: [{new_state}]", object_id=target_username)
                                st.success("Kullanıcı güncellendi.")
                                st.rerun()
                            conn.close()

# =========================================================
# 12. MENÜ: SAKLAMA VE İMHA (DEVLET/KURUMSAL STANDART ONAY ZİNCİRİ)
# =========================================================
elif menu == "Saklama ve imha" and can_manage_destruction(active_row):
    header("Saklama ve imha yönetimi", "Yasal saklama süresi dolan belgelerin onay zinciri ve imha icrası.")
    tab1, tab2 = st.tabs(["Süresi Dolanlar (İmha Bekleyenler)", "İmha Edilen Belgeler Arşivi"])

    with tab1:
        st.markdown("#### İmha Edilecek Belgeler Listesi")
        scope_dest_sql = " AND unit_code = ?" if active_unit != "ALL" else ""
        scope_dest_params = [CURRENT_YEAR]
        if active_unit != "ALL":
            scope_dest_params.append(active_unit)
        
        pending_df = read_df("""
            SELECT doc_reg_no AS 'Kayıt No', doc_no AS 'Dosya No', doc_name AS 'Belge Adı', 
                   unit_code AS 'Birim', 
                   CASE WHEN retention_end_year >= 9000 THEN 'Süresiz' ELSE CAST(retention_end_year AS TEXT) END AS 'İmha Yılı', 
                   destruction_status AS 'Durum', legal_hold AS 'Hukuki Engel',
                   destruction_requested_by AS 'İmha Talep Eden'
            FROM aygaz_main_archive 
            WHERE (destruction_status IS NULL OR destruction_status != 'İMHA EDİLDİ') 
              AND CAST(retention_end_year AS INTEGER) <= ? """ + scope_dest_sql, tuple(scope_dest_params))

        if not pending_df.empty and "Kayıt No" in pending_df.columns:
            st.dataframe(pending_df, width="stretch", hide_index=True)
            st.markdown("---")
            st.markdown("**Kontrollü İmha İş Akışı (Onay Zinciri)**")
            
            col_sel, col_act1, col_act2 = st.columns([2, 1, 1])
            with col_sel:
                selected_record_no = st.selectbox("İşlem yapılacak belgeyi seçin:", pending_df["Kayıt No"].tolist())
                selected_item = pending_df[pending_df["Kayıt No"] == selected_record_no].iloc[0]
            
            cur_status = str(selected_item["Durum"])
            is_held = int(selected_item["Hukuki Engel"]) == 1
            requester = str(selected_item.get("İmha Talep Eden", "") or "")

            with col_act1:
                st.write("")
                st.write("")
                if cur_status == "BEKLİYOR" and can_create_destruction_request(active_row):
                    if st.button("İmha Talebi Oluştur", type="primary", use_container_width=True):
                        enforce_permission(active_row, "IMHA_TALEP", str(selected_item["Birim"]))
                        if is_held:
                            st.error("Bu kayıt üzerinde aktif bir Hukuki Engel (Hold) bulunmaktadır. İmha talebi açılamaz.")
                        else:
                            conn = get_db()
                            cursor = conn.cursor()
                            now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                            scope_cond = " AND unit_code = ?" if active_unit != "ALL" else ""
                            req_params = [active_user, now_stamp, str(selected_record_no), CURRENT_YEAR]
                            if active_unit != "ALL":
                                req_params.append(active_unit)
                            
                            cursor.execute(f"""
                                UPDATE aygaz_main_archive SET 
                                    destruction_status = 'ONAY BEKLİYOR', 
                                    destruction_requested_by = ?,
                                    destruction_requested_at = ?
                                WHERE doc_reg_no = ? 
                                  AND destruction_status = 'BEKLİYOR'
                                  AND CAST(retention_end_year AS INTEGER) <= ?
                                  AND (legal_hold = 0 OR legal_hold IS NULL)
                                  {scope_cond}
                            """, tuple(req_params))
                            
                            if cursor.rowcount == 1:
                                conn.commit()
                                audit(active_user, "İmha Talebi Açma", f"Kayıt No {selected_record_no} için imha talebi açıldı.", object_id=str(selected_record_no))
                                st.success("İmha talebi oluşturuldu, onay bekleniyor.")
                                st.rerun()
                            else:
                                conn.rollback()
                                st.error("İmha talebi oluşturulamadı: Kayıt hukuki kilit altında olabilir, saklama süresi dolmamış olabilir veya birim yetkiniz yetersizdir.")
                            conn.close()

            with col_act2:
                st.write("")
                st.write("")
                if cur_status == "ONAY BEKLİYOR" and can_approve_destruction(active_row):
                    if st.button("İmha İşlemini Onayla", type="primary", use_container_width=True):
                        enforce_permission(active_row, "IMHA_ONAY", str(selected_item["Birim"]))
                        conn = get_db()
                        cursor = conn.cursor()
                        iso_today = suanki_zaman().strftime("%Y-%m-%d")
                        now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                        scope_cond = " AND unit_code = ?" if active_unit != "ALL" else ""
                        appr_params = [iso_today, active_user, now_stamp, str(selected_record_no), active_user, CURRENT_YEAR]
                        if active_unit != "ALL":
                            appr_params.append(active_unit)

                        cursor.execute(f"""
                            UPDATE aygaz_main_archive SET 
                                destruction_status = 'İMHA EDİLDİ', 
                                destruction_date = ?,
                                destruction_approved_by = ?,
                                destruction_approved_at = ?
                            WHERE doc_reg_no = ? 
                              AND destruction_status = 'ONAY BEKLİYOR'
                              AND destruction_requested_by != ?
                              AND (legal_hold = 0 OR legal_hold IS NULL)
                              AND CAST(retention_end_year AS INTEGER) <= ?
                              {scope_cond}
                        """, tuple(appr_params))

                        if cursor.rowcount == 1:
                            conn.commit()
                            audit(active_user, "Belge İmhası Onaylama", f"Kayıt No {selected_record_no} resmi olarak imha edildi.", object_id=str(selected_record_no))
                            st.success(f"Kayıt No {selected_record_no} başarıyla imha edildi olarak işlendi.")
                            st.rerun()
                        else:
                            conn.rollback()
                            st.error("İmha onayı başarısız: Görevler ayrılığı kuralı (kendi talebinizi onaylayamazsınız), aktif hukuki kilit veya birim yetki kısıtı nedeniyle işlem durduruldu.")
                        conn.close()
        else:
            st.info("İmha süresi dolmuş bekleyen belge bulunmamaktadır.")

    with tab2:
        st.markdown(f"#### {CURRENT_YEAR} Yılı İmha Tutanağı ve Arşivi")
        destroyed_query = """
            SELECT doc_reg_no AS 'Kayıt No', doc_no AS 'Dosya No', doc_name AS 'Belge Adı', 
                   unit_code AS 'Birim', retention_end_year AS 'İmha Yılı', 
                   destruction_date AS 'İmha Tarihi', destruction_status AS 'Durum',
                   destruction_requested_by AS 'Talep Eden', destruction_approved_by AS 'Onaylayan'
            FROM aygaz_main_archive 
            WHERE destruction_status = 'İMHA EDİLDİ'
              AND (destruction_date LIKE ? OR CAST(retention_end_year AS TEXT) = ?)
        """
        dest_params: list[Any] = [f"%{CURRENT_YEAR}%", str(CURRENT_YEAR)]
        if active_unit != "ALL":
            destroyed_query += " AND unit_code = ?"
            dest_params.append(active_unit)

        destroyed_df = read_df(destroyed_query, dest_params)
        if not destroyed_df.empty:
            display_destroyed = destroyed_df.copy()
            if "İmha Tarihi" in display_destroyed.columns:
                display_destroyed["İmha Tarihi"] = display_destroyed["İmha Tarihi"].apply(format_db_date)
            st.dataframe(display_destroyed, width="stretch", hide_index=True)
            download_excel(
                f"{CURRENT_YEAR} İmha Edilen Belgeler Listesini İndir (Excel)",
                display_destroyed,
                f"Aygaz_Imha_Edilen_Belgeler_{CURRENT_YEAR}.xlsx",
                sheet_name="Imha_Listesi",
                user=active_user
            )
        else:
            st.info(f"{CURRENT_YEAR} yılı için yetki kapsamınızda imha edilmiş bir belge kaydı bulunmuyor.")

# =========================================================
# 13. MENÜ: GÜNLÜKLER (YÖNETİM RAPORLARI)
# =========================================================
elif menu == "Günlükler" and can_view_reports(active_row):
    header("Yönetim raporları", "Arşiv hacmini, iş yükünü ve saklama riskini tek bakışta değerlendir.")
    
    rep_unit_sql = " WHERE unit_code = ?" if active_unit != "ALL" else ""
    rep_unit_params: list[Any] = [CURRENT_YEAR]
    if active_unit != "ALL":
        rep_unit_params.append(active_unit)
    
    unit_report = read_df("""
        SELECT unit_code AS [Birim], COUNT(*) AS [Kayıt], 
               SUM(CASE WHEN status = 'Zimmette' THEN 1 ELSE 0 END) AS [Zimmette], 
               SUM(CASE WHEN retention_end_year <= ? AND (destruction_status IS NULL OR destruction_status != 'İMHA EDİLDİ') THEN 1 ELSE 0 END) AS [Süre riski] 
        FROM aygaz_main_archive """ + rep_unit_sql + """ GROUP BY unit_code ORDER BY [Kayıt] DESC
    """, tuple(rep_unit_params))
    
    rep_status_sql = " WHERE unit_code = ?" if active_unit != "ALL" else ""
    rep_status_params: list[Any] = [active_unit] if active_unit != "ALL" else []
    status_report = read_df("SELECT status AS [Durum], COUNT(*) AS [Kayıt] FROM aygaz_main_archive " + rep_status_sql + " GROUP BY status ORDER BY [Kayıt] DESC", tuple(rep_status_params))
    
    r1, r2 = st.columns(2)
    with r1:
        st.markdown("### Birim dağılımı")
        st.dataframe(unit_report, width="stretch", hide_index=True, height=300)
        if not unit_report.empty:
            st.bar_chart(unit_report.set_index("Birim")[["Kayıt", "Zimmette", "Süre riski"]])
    with r2:
        st.markdown("### Durum dağılımı")
        st.dataframe(status_report, width="stretch", hide_index=True, height=300)
        if not status_report.empty:
            st.bar_chart(status_report.set_index("Durum"))

    st.markdown("### Kayıt hareket raporları")
    report_tabs = st.tabs(["Günlük kayıtlar", "Aylık kayıtlar"])
    with report_tabs[0]:
        report_day = st.date_input("Gün", value=suanki_zaman().date())
        day_str_tr = report_day.strftime("%d/%m/%Y")
        day_str_iso = report_day.strftime("%Y-%m-%d")
        
        daily_scope_sql = " AND unit_code = ?" if active_unit != "ALL" else ""
        daily_scope_params: list[Any] = [day_str_tr, day_str_iso]
        if active_unit != "ALL":
            daily_scope_params.append(active_unit)
            
        daily_report = read_df("""
            SELECT first_doc_date AS [Kayıt Tarihi], 
                   unit_code AS [Birim], COUNT(*) AS [Kayıt Sayısı] 
            FROM aygaz_main_archive 
            WHERE (first_doc_date = ? OR first_doc_date LIKE ? || '%') """ + daily_scope_sql + """
            GROUP BY first_doc_date, unit_code ORDER BY [Kayıt Sayısı] DESC
        """, tuple(daily_scope_params))
        st.dataframe(daily_report, width="stretch", hide_index=True, height=220)
        download_excel("Günlük Excel indir", daily_report, "aygaz-gunluk-kayitlar.xlsx", "Günlük Kayıtlar", user=active_user)
        
    with report_tabs[1]:
        selected_month = st.selectbox("Ay Seçin", list(range(1, 13)), index=suanki_zaman().month - 1)
        selected_year = st.selectbox("Yıl Seçin", [CURRENT_YEAR - i for i in range(5)], index=0)
        month_pattern_tr = f"%/{selected_month:02d}/{selected_year}"
        month_pattern_iso = f"{selected_year}-{selected_month:02d}%"
        
        monthly_scope_sql = " AND unit_code = ?" if active_unit != "ALL" else ""
        monthly_scope_params: list[Any] = [month_pattern_tr, month_pattern_iso]
        if active_unit != "ALL":
            monthly_scope_params.append(active_unit)
            
        monthly_report = read_df("""
            SELECT unit_code AS [Birim], COUNT(*) AS [Kayıt Sayısı] 
            FROM aygaz_main_archive 
            WHERE (first_doc_date LIKE ? OR first_doc_date LIKE ?) """ + monthly_scope_sql + """
            GROUP BY unit_code ORDER BY [Kayıt Sayısı] DESC
        """, tuple(monthly_scope_params))
        st.dataframe(monthly_report, width="stretch", hide_index=True, height=220)
        download_excel("Aylık Excel indir", monthly_report, "aygaz-aylik-kayitlar.xlsx", "Aylık Kayıtlar", user=active_user)
        
    download_excel("Yönetim raporunu indir", unit_report, "aygaz-arsiv-yonetim-raporu.xlsx", "Birim Raporu", {"Durum Raporu": status_report}, user=active_user)

# =========================================================
# 14. MENÜ: DENETİM İZİ (AUDIT TRAIL)
# =========================================================
elif menu == "Denetim izi" and can_view_audit(active_row):
    header("Denetim izi", "Arşivde kim, ne zaman, hangi kararı verdi?")
    
    is_valid, verify_msg = verify_audit_hash_chain()
    if is_valid:
        st.markdown(f'<div class="hint"><b>Hash zinciri bütünlüğü: GEÇERLİ</b><br>{verify_msg}</div><br>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="risk"><b>Hash zinciri bütünlüğü: UYUŞMAZLIK TESPİT EDİLDİ</b><br>{verify_msg}</div><br>', unsafe_allow_html=True)

    audit_scope_sql = ""
    audit_scope_params: list[Any] = []
    if active_unit != "ALL" and not is_admin:
        audit_scope_sql = """
            WHERE (
                a.user = ? 
                OR a.object_id IN (SELECT doc_reg_no FROM aygaz_main_archive WHERE unit_code = ?)
                OR a.object_id IN (SELECT req_no FROM archive_requests WHERE unit_code = ?)
            )
        """
        audit_scope_params = [active_user, active_unit, active_unit]

    audit_df = read_df("""
        SELECT a.timestamp AS [Zaman], a.user AS [Kullanıcı], a.action_type AS [İşlem], 
               a.object_id AS [Kayıt No], a.details AS [Detay], a.result AS [Sonuç], 
               a.event_hash AS [SHA-256 İmzası] 
        FROM archive_audit a """ + audit_scope_sql + """ ORDER BY a.id DESC LIMIT 250
    """, tuple(audit_scope_params))
    
    st.dataframe(audit_df, width="stretch", hide_index=True, height=520)
    download_excel("Denetim İzi Excel İndir", audit_df, "aygaz-arsiv-denetim-izi.xlsx", "Denetim İzi", user=active_user)
