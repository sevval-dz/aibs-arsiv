from __future__ import annotations
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# =========================================================
# AYGAZ ARŞİV BİLGİ SİSTEMİ (AİBS) - ENTERPRISE REFERENCE
# ISO 15489-1 / TS 13298 / KVKK Uyumlu Üretim Mimarisi
# =========================================================

st.set_page_config(
    page_title="Aygaz Arşiv Sistemi",
    page_icon="Aygaz.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("AIBS_DB_PATH", BASE_DIR / "aibs_database.db"))
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

CURRENT_YEAR = suanki_zaman().year

# =========================================================
# SIDEBAR AÇ / KAPAT BUTONU (ORİJİNAL MİMARİ KORUNDU)
# =========================================================
components.html(
    """
    <script>
    const parentDoc = window.parent.document;
    function toggleSidebar() {
        const selectors = [
            '[data-testid="stSidebarCollapseButton"] button',
            '[data-testid="stSidebarCollapsedControl"] button',
            '[data-testid="collapsedControl"] button',
            'button[aria-label="Collapse sidebar"]',
            'button[aria-label="Expand sidebar"]'
        ];
        for (const selector of selectors) {
            const button = parentDoc.querySelector(selector);
            if (button) {
                button.click();
                return;
            }
        }
    }
    const old = parentDoc.getElementById("aygaz-sidebar-button");
    if (old) { old.remove(); }
    const button = parentDoc.createElement("button");
    button.id = "aygaz-sidebar-button";
    button.innerHTML = "‹";
    button.style.position = "fixed";
    button.style.left = "10px";
    button.style.top = "10px";
    button.style.width = "38px";
    button.style.height = "38px";
    button.style.zIndex = "999999999";
    button.style.background = "#0072bc";
    button.style.color = "#ffffff";
    button.style.border = "1px solid #005b94";
    button.style.borderRadius = "7px";
    button.style.fontSize = "24px";
    button.style.cursor = "pointer";
    button.style.boxShadow = "0 2px 8px rgba(0,0,0,.25)";
    button.onclick = toggleSidebar;
    parentDoc.body.appendChild(button);
    </script>
    """,
    height=0,
    width=0
)

st.markdown("""
<style>
#custom-sidebar-toggle {
    position: fixed;
    top: 10px;
    left: 10px;
    width: 38px;
    height: 38px;
    z-index: 999999999;
    background: #0072bc;
    border: 1px solid #005b94;
    border-radius: 7px;
    color: white;
    font-size: 22px;
    line-height: 38px;
    text-align: center;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0,0,0,.25);
}
</style>
<script>
(function () {
    function findSidebarButton() {
        const selectors = [
            '[data-testid="stSidebarCollapseButton"] button',
            '[data-testid="stSidebarCollapsedControl"] button',
            '[data-testid="collapsedControl"] button',
            'button[aria-label="Collapse sidebar"]',
            'button[aria-label="Expand sidebar"]'
        ];
        for (const selector of selectors) {
            const button = window.parent.document.querySelector(selector);
            if (button) return button;
        }
        return null;
    }
    function createToggle() {
        if (window.parent.document.getElementById("custom-sidebar-toggle")) return;
        const button = window.parent.document.createElement("div");
        button.id = "custom-sidebar-toggle";
        button.innerHTML = "‹";
        button.onclick = function () {
            const sidebarButton = findSidebarButton();
            if (sidebarButton) sidebarButton.click();
        };
        window.parent.document.body.appendChild(button);
    }
    setTimeout(createToggle, 500);
    setTimeout(createToggle, 1500);
    setTimeout(createToggle, 3000);
})();
</script>
""", unsafe_allow_html=True)

# =========================================================
# ARAYÜZ TASARIMI (ORİJİNAL CSS PALETİ)
# =========================================================
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
[data-testid="stSidebar"] .stRadio label:hover { background: #29434b; }

.stButton button, 
.stDownloadButton button, 
.stFormSubmitButton button,
div[data-testid="stFormSubmitButton"] > button { 
    background-color: var(--teal) !important; 
    border: 1px solid var(--teal) !important; 
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
    background-color: var(--teal-hover) !important; 
    border-color: var(--teal-hover) !important; 
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
    border-color: var(--teal) !important;
    box-shadow: 0 0 0 1px var(--teal) !important;
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
.eyebrow { font-family: 'Space Mono'; color: var(--teal); font-size: 11px; letter-spacing: 1.4px; text-transform: uppercase; }
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
.badge { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge-hold { background: #fee2e2; color: #991b1b; }
.badge-clean { background: #dcfce7; color: #166534; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# VERİTABANI VE GELİŞMİŞ ŞEMA YÖNETİMİ
# =========================================================
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def read_df(query: str, params: tuple | list = ()) -> pd.DataFrame:
    conn = get_db()
    try:
        return pd.read_sql_query(query, conn, params=params)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()

def audit(user: str, action: str, details: str, object_type: str = "GENEL", object_id: str = "") -> None:
    conn = get_db()
    try:
        cursor = conn.cursor()
        now_str = datetime.now(TR_TZ).strftime("%Y-%m-%d %H:%M:%S")
        last_hash_row = cursor.execute("SELECT event_hash FROM archive_audit ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = last_hash_row[0] if last_hash_row and last_hash_row[0] else "0" * 64
        
        payload = f"{now_str}|{user}|{action}|{details}|{object_type}|{object_id}|{prev_hash}"
        event_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        
        cursor.execute(
            """
            INSERT INTO archive_audit 
            (timestamp, user, action_type, details, object_type, object_id, previous_hash, event_hash) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (now_str, user, action, details, object_type, object_id, prev_hash, event_hash)
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

def to_excel_bytes(sheets_dict: dict[str, pd.DataFrame]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in sheets_dict.items():
            df.to_excel(writer, index=False, sheet_name=str(sheet_name)[:31])
    return output.getvalue()

def download_excel(label: str, dataframe: pd.DataFrame, filename: str, sheet_name: str = "Arşiv Kataloğu", extra_sheets: dict | None = None) -> None:
    sheets = {sheet_name: dataframe}
    if extra_sheets:
        sheets.update(extra_sheets)
    st.download_button(
        label=label,
        data=to_excel_bytes(sheets),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def init_database() -> None:
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS institutions (id INTEGER PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS units (id INTEGER PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE, inst_code TEXT, inst_name TEXT);
        CREATE TABLE IF NOT EXISTS series (id INTEGER PRIMARY KEY, name TEXT NOT NULL, unit_code TEXT, unit_name TEXT, series_code TEXT NOT NULL UNIQUE, retention_year INTEGER, legal_basis TEXT, kvkk_category TEXT DEFAULT 'GENEL');
        CREATE TABLE IF NOT EXISTS user_permissions (id INTEGER PRIMARY KEY, username TEXT UNIQUE, full_name TEXT, unit_code TEXT, auth_codes TEXT, role_desc TEXT);
        
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
            retention_end_year INTEGER,
            classification TEXT DEFAULT 'INTERNAL',
            personal_data INTEGER DEFAULT 0,
            special_category_data INTEGER DEFAULT 0,
            legal_hold_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS legal_holds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_reg_no TEXT NOT NULL,
            hold_ref TEXT NOT NULL UNIQUE,
            reason TEXT NOT NULL,
            authority TEXT,
            created_by TEXT,
            created_at TEXT,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS archive_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, req_no TEXT UNIQUE, requester TEXT, unit_code TEXT, doc_item TEXT, delivery_type TEXT, urgency TEXT, status TEXT, notes TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS request_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, req_no TEXT, sender TEXT, message TEXT, created_at TEXT);
        
        CREATE TABLE IF NOT EXISTS archive_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            timestamp TEXT, 
            user TEXT, 
            action_type TEXT, 
            details TEXT,
            object_type TEXT,
            object_id TEXT,
            previous_hash TEXT,
            event_hash TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_archive_search ON aygaz_main_archive (unit_code, series_code, status);
        CREATE INDEX IF NOT EXISTS idx_archive_retention ON aygaz_main_archive (retention_end_year, destruction_status);
    """)

    # Gerekli ek kolonların güvenli entegrasyonu
    cursor.execute("PRAGMA table_info(aygaz_main_archive)")
    archive_cols = [r[1] for r in cursor.fetchall()]
    for col, defn in [
        ("classification", "TEXT DEFAULT 'INTERNAL'"),
        ("personal_data", "INTEGER DEFAULT 0"),
        ("special_category_data", "INTEGER DEFAULT 0"),
        ("legal_hold_count", "INTEGER DEFAULT 0")
    ]:
        if col not in archive_cols:
            cursor.execute(f"ALTER TABLE aygaz_main_archive ADD COLUMN {col} {defn}")

    cursor.execute("PRAGMA table_info(archive_audit)")
    audit_cols = [r[1] for r in cursor.fetchall()]
    for col in ["object_type", "object_id", "previous_hash", "event_hash"]:
        if col not in audit_cols:
            cursor.execute(f"ALTER TABLE archive_audit ADD COLUMN {col} TEXT")

    # Temel Kurum ve Birim Tohum Verileri
    cursor.executemany("INSERT OR IGNORE INTO institutions (id, name, code) VALUES (?, ?, ?)", [
        (1, "AYGAZ A.Ş.", "10"), (11, "ZİNERJİ A.Ş.", "40"),
        (12, "ANADOLU HİSARI TANKERCİLİK", "30"), (13, "AYGAZ DOĞALGAZ", "20"),
        (15, "AKPA A.Ş.", "50"), (17, "GAZAL A.Ş.", "60"),
    ])
    cursor.executemany("INSERT OR IGNORE INTO units (id, name, code, inst_code, inst_name) VALUES (?, ?, ?, ?, ?)", [
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
    cursor.executemany("INSERT OR IGNORE INTO series (id, name, unit_code, unit_name, series_code, retention_year, legal_basis, kvkk_category) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, "PERSONEL ÖZLÜK DOSYALARI", "1006", "İNSAN KAYNAKLARI MÜDÜRLÜĞÜ", "1", 10, "İş Kanunu Md. 75", "ÖZLÜK, KİMLİK"),
        (3, "MAKBUZ VE TAHSİLAT BELGELERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "3", 10, "VUK Md. 253", "FİNANSAL"),
        (4, "MAHSUP VE YEVMİYE FİŞLERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "4", 10, "TTK Md. 82", "FİNANSAL"),
        (9, "TİCARİ BAYİLİK VE MÜLKİYET SÖZLEŞMELERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "9", 100, "Süresiz Saklama", "TİCARİ"),
        (11, "İŞ SAĞLIĞI VE AMBARLI TEFTİŞ RAPORLARI", "1008", "İŞLETME MÜHENDİSLİK YATIRIMLAR MÜDÜRLÜĞÜ", "11", 15, "6331 Sayılı İSGK", "SAĞLIK, GÜVENLİK"),
    ])

    if cursor.execute("SELECT COUNT(*) FROM user_permissions").fetchone()[0] == 0:
        cursor.execute("INSERT INTO user_permissions VALUES (?, ?, ?, ?, ?, ?)", (1, "local\\admin", "Arşiv Yöneticisi", "ALL", "ADMIN,TALEP_YONETIM,IMHA,DENETIM,LEGAL_HOLD", "Yönetici"))
    
    if cursor.execute("SELECT COUNT(*) FROM aygaz_main_archive").fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO aygaz_main_archive (doc_reg_no, doc_no, doc_name, series_code, unit_code, first_doc_date, last_doc_date, box_no, shelf_no, institution, status, destruction_status, retention_end_year, classification, personal_data, special_category_data, legal_hold_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            ("90101", "1411-23-201", "Bayi faaliyet raporları", "6", "1004", "01/08/2023", "31/08/2023", "23050", "H11.211", "AYGAZ", "Depoda", "BEKLİYOR", 2028, "INTERNAL", 0, 0, 0),
            ("90102", "1411-23-202", "Ticari bayilik sözleşmeleri", "9", "1004", "01/08/2023", "31/08/2023", "23051", "H11.212", "AYGAZ", "Zimmette", "BEKLİYOR", 2123, "CONFIDENTIAL", 1, 0, 0),
            ("90085", "1205-22-040", "İSG saha denetim raporları", "11", "1008", "10/05/2022", "15/05/2022", "22910", "H10.014", "AYGAZ", "Depoda", "BEKLİYOR", 2037, "RESTRICTED", 0, 1, 0),
        ])
    conn.commit()
    conn.close()

init_database()

# =========================================================
# YETKİLENDİRME VE GÖREVLER AYRILIĞI (RBAC)
# =========================================================
def normalize_auth_codes(auth_codes: Any) -> set[str]:
    if not auth_codes: return set()
    return {c.strip().upper() for c in str(auth_codes).split(",") if c.strip()}

def has_permission(user_row: pd.Series, permission: str) -> bool:
    codes = normalize_auth_codes(user_row["auth_codes"])
    return "*" in codes or "ADMIN" in codes or permission.strip().upper() in codes

def is_admin_user(user_row: pd.Series) -> bool:
    role = str(user_row["role_desc"] or "").strip().lower()
    unit = str(user_row["unit_code"] or "").strip().upper()
    codes = normalize_auth_codes(user_row["auth_codes"])
    return unit == "ALL" or "admin" in role or "yönetici" in role or "ADMIN" in codes or "*" in codes

def can_manage_requests(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "TALEP_YONETIM")

def can_manage_destruction(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "IMHA")

def can_view_audit(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "DENETIM")

def can_manage_legal_hold(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "LEGAL_HOLD")

# =========================================================
# SAKLAMA, İMHA VE LEGAL HOLD MOTORU
# =========================================================
def execute_destruction(record_no: str, user: str, method: str = "Tutanak Karşılığı Fiziksel Kıyım") -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        hold_check = cursor.execute("SELECT legal_hold_count FROM aygaz_main_archive WHERE doc_reg_no = ?", (str(record_no),)).fetchone()
        if hold_check and hold_check[0] > 0:
            return False  # Aktif Hukuki Engel Varsa İmha Engellenir

        today_str = datetime.now(TR_TZ).strftime("%d.%m.%Y")
        cursor.execute("""
            UPDATE aygaz_main_archive 
            SET destruction_status = 'İMHA EDİLDİ',
                destruction_date = ?
            WHERE doc_reg_no = ?
        """, (today_str, str(record_no)))
        conn.commit()
        audit(user, "İmha İcrası", f"Kayıt No {record_no} imha edildi. Yöntem: {method}", "ARŞİV_BELGE", record_no)
        return True
    finally:
        conn.close()

def get_destroyed_records(year_filter: str | None = None) -> pd.DataFrame:
    query = """
        SELECT doc_reg_no AS 'Kayıt No', doc_no AS 'Dosya No', doc_name AS 'Belge Adı', 
               unit_code AS 'Birim', retention_end_year AS 'İmha Yılı', 
               destruction_date AS 'İmha Tarihi', destruction_status AS 'Durum' 
        FROM aygaz_main_archive 
        WHERE destruction_status = 'İMHA EDİLDİ'
    """
    params = []
    if year_filter:
        query += " AND (destruction_date LIKE ? OR CAST(retention_end_year AS TEXT) = ?)"
        params.extend([f"%{year_filter}%", str(year_filter)])
    return read_df(query, params=params)

def logo_data_uri() -> str:
    logo_path = Path(__file__).resolve().parent / "Aygaz.png"
    if logo_path.exists():
        return f"data:image/png;base64,{base64.b64encode(logo_path.read_bytes()).decode('ascii')}"
    return ""

def wordmark_data_uri() -> str:
    wordmark_path = Path(__file__).resolve().parent / "aygaz_logo.jpg"
    if wordmark_path.exists():
        return f"data:image/jpeg;base64,{base64.b64encode(wordmark_path.read_bytes()).decode('ascii')}"
    return ""

# =========================================================
# SOL MENÜ (SIDEBAR)
# =========================================================
users_df = read_df("SELECT id, username, full_name, unit_code, auth_codes, role_desc FROM user_permissions ORDER BY id")
if users_df.empty:
    users_df = pd.DataFrame([{
        "id": 1, "username": "local\\admin", "full_name": "Arşiv Yöneticisi",
        "unit_code": "ALL", "auth_codes": "*", "role_desc": "Yönetici"
    }])

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

    user_labels = [f"{row.full_name} · {row.unit_code}" for row in users_df.itertuples()]
    configured_user = os.getenv("AIBS_USER", "").casefold()
    default_index = next((i for i, r in enumerate(users_df.itertuples()) if str(r.username).casefold() == configured_user), 0)

    selected_user = st.selectbox("Aktif Kullanıcı (RBAC)", user_labels, index=default_index)
    active_row = users_df.iloc[user_labels.index(selected_user)]
    active_name = active_row["full_name"]
    active_unit = active_row["unit_code"]
    active_user = active_row["username"]
    is_admin = is_admin_user(active_row)

    st.caption(f"Rol: {active_row['role_desc']} · Yetki Kapsamı: {active_unit}")
    st.markdown("---")

    menu_options = ["Katalog", "Erişim Talepleri"]
    if is_admin:
        menu_options.extend(["Tanımlar", "Saklama ve imha", "Günlükler"])
    if can_manage_legal_hold(active_row):
        menu_options.append("Hukuki Engel (Legal Hold)")
    if can_view_audit(active_row):
        menu_options.append("Denetim izi")

    menu = st.radio("Çalışma alanı", menu_options)
    st.markdown("---")
    st.caption("Sistem Durumu (ISO 15489-1)")
    st.markdown('<div style="color:#ffffff;font-size:12px;font-weight:600;">Veritabanı bağlı · WAL Modu Aktif</div>', unsafe_allow_html=True)
    st.caption(datetime.now(TR_TZ).strftime("Son senkronizasyon %d.%m.%Y · %H:%M"))

# =========================================================
# ÜST BAR (TOPBAR)
# =========================================================
user_initial = active_name[:1].upper() if active_name else "A"
scope_label = "Tüm birimler" if active_unit == "ALL" else f"Birim kapsamı: {active_unit}"
logo_src = logo_data_uri()
logo_markup = f'<img src="{logo_src}" alt="Aygaz logosu" style="width:34px;height:34px;object-fit:contain">' if logo_src else '<div class="aygaz-symbol">A</div>'

st.markdown(
    f'<div class="topbar"><div class="aygaz-lockup">{logo_markup}<span>AYGAZ ARŞİV BİLGİ SİSTEMİ</span></div>'
    f'<div class="topbar-user"><div class="topbar-user-dot">{user_initial}</div><span>{active_name}</span>'
    f'<span class="mono" style="color:#687984;font-size:10px">{scope_label}</span></div></div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="scope"><strong>KURUMSAL ÜRETİM REFERANS SÜRÜMÜ</strong> · '
    'Bu sürüm ISO 15489 Belge Yönetimi ve TS 13298 standartlarına uygun olarak '
    'saklama planı, hukuki hold mekanizması, çok aşamalı imha onayı ve hash zincirli audit trail içerir.</div>',
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
    st.markdown(
        f'<div class="page-head"><div><div class="eyebrow">AYGAZ ARŞİV SİSTEMİ / {menu.upper()}</div>'
        f'<h1>{title}</h1><p>{description}</p></div><div class="stamp">{formatli_tarih()}</div></div>',
        unsafe_allow_html=True
    )

# =========================================================
# MENÜ 1: KATALOG (TOPLU AKTARIM DAHİL)
# =========================================================
if menu == "Katalog":
    header("Arşiv kataloğu", "Belgeyi adıyla değil, fiziksel hayat döngüsü ve üstverisiyle yönetin.")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.markdown(f'<div class="metric"><div class="metric-label">Toplam Kayıt</div><div class="metric-value">{scoped_count:,}</div><div class="metric-note">yetki kapsamındaki kayıtlar</div></div>', unsafe_allow_html=True)
    col2.markdown(f'<div class="metric"><div class="metric-label">Aktif Talep</div><div class="metric-value">{open_requests}</div><div class="metric-note">işlem kuyruğunda</div></div>', unsafe_allow_html=True)
    col3.markdown(f'<div class="metric"><div class="metric-label">Zimmette</div><div class="metric-value">{custody_count}</div><div class="metric-note">kullanıcıda aktif</div></div>', unsafe_allow_html=True)
    col4.markdown(f'<div class="metric"><div class="metric-label">Süresi Dolan</div><div class="metric-value">{retention_count}</div><div class="metric-note">{CURRENT_YEAR} ve öncesi</div></div>', unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    left, right = st.columns([7, 3])
    
    with left:
        search = st.text_input("Katalogda ara", placeholder="Kayıt no, belge adı, kutu, raf veya gizlilik...", label_visibility="collapsed")
        f1, f2, f3 = st.columns([2, 2, 1])
        with f1: status = st.selectbox("Durum", ["Tümü", "Depoda", "Zimmette", "İmha Listesinde", "Hukuki Engel (Hold)"])
        with f2: unit = st.text_input("Birim kodu", placeholder="Örn. 1004")
        with f3: limit = st.selectbox("Görünüm", [25, 50, 100])
        
        query = """
            SELECT doc_reg_no AS [Kayıt No], doc_no AS [Dosya No], doc_name AS [Belge], 
                   series_code AS [Seri], unit_code AS [Birim], first_doc_date AS [İlk Evrak Tarihi], 
                   last_doc_date AS [Son Evrak Tarihi], box_no AS [Kutu No], shelf_no AS [Yer No], 
                   institution AS [Kurum], status AS [Durum], destruction_status AS [İmha Durumu], 
                   retention_end_year AS [Saklama Sonu], classification AS [Gizlilik],
                   CASE WHEN legal_hold_count > 0 THEN '🔒 BLOKELİ' ELSE 'SERBEST' END AS [Hukuki Kilit]
            FROM aygaz_main_archive WHERE 1=1
        """
        params = []
        if active_unit != "ALL":
            query += " AND unit_code = ?"
            params.append(active_unit)
        
        if search.strip():
            query += " AND (doc_reg_no LIKE ? OR doc_no LIKE ? OR doc_name LIKE ? OR box_no LIKE ? OR shelf_no LIKE ? OR classification LIKE ?)"
            params.extend([f"%{search.strip()}%"] * 6)
            
        if status == "İmha Listesinde":
            query += " AND (destruction_status IS NULL OR destruction_status != 'İMHA EDİLDİ') AND CAST(retention_end_year AS INTEGER) <= ?"
            params.append(CURRENT_YEAR)
        elif status == "Hukuki Engel (Hold)":
            query += " AND legal_hold_count > 0"
        elif status != "Tümü":
            query += " AND status = ?"
            params.append(status)
            
        if unit.strip() and active_unit == "ALL":
            query += " AND unit_code LIKE ?"
            params.append(f"%{unit.strip()}%")
            
        catalog_df = read_df(query + " ORDER BY id DESC LIMIT ?", params + [limit])
        st.dataframe(catalog_df, width="stretch", hide_index=True, height=390)
        st.caption(f"{len(catalog_df)} kayıt gösteriliyor · ISO 15489-1 Üstveri Filtreleri Aktif")
        download_excel("Katalog Excel İndir", catalog_df, "aygaz-arsiv-katalog.xlsx")
        
        if is_admin:
            with st.expander("Yeni Arşiv Kaydı Oluştur (Tekil)"):
                with st.form("new_archive_record"):
                    a1, a2, a3 = st.columns(3)
                    with a1:
                        new_reg = st.text_input("Kayıt no")
                        new_doc_no = st.text_input("Dosya no")
                        new_doc_name = st.text_input("Belge adı")
                    with a2:
                        new_series = st.text_input("Seri kodu", value="1")
                        new_unit = st.text_input("Birim kodu", value="1004")
                        new_box = st.text_input("Kutu no")
                    with a3:
                        new_shelf = st.text_input("Raf / yer no")
                        new_first_date = st.text_input("İlk evrak tarihi (GG/AA/YYYY)")
                        new_last_date = st.text_input("Son evrak tarihi (GG/AA/YYYY)")
                    
                    st.markdown("**KVKK ve Gizlilik Sınıflandırması**")
                    k1, k2, k3 = st.columns(3)
                    with k1: new_class = st.selectbox("Gizlilik Derecesi", ["INTERNAL", "CONFIDENTIAL", "RESTRICTED"])
                    with k2: new_pd = st.checkbox("Kişisel Veri İçerir (KVKK)")
                    with k3: new_spd = st.checkbox("Özel Nitelikli Kişisel Veri")

                    if st.form_submit_button("Arşiv Kaydını Oluştur", type="primary"):
                        if new_reg.strip() and new_doc_name.strip() and new_unit.strip():
                            conn = get_db()
                            conn.execute("""
                                INSERT INTO aygaz_main_archive 
                                (doc_reg_no, doc_no, doc_name, series_code, unit_code, first_doc_date, last_doc_date, box_no, shelf_no, institution, status, destruction_status, retention_end_year, classification, personal_data, special_category_data)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (new_reg.strip(), new_doc_no.strip(), new_doc_name.strip(), new_series.strip(), new_unit.strip(), new_first_date.strip(), new_last_date.strip(), new_box.strip(), new_shelf.strip(), "AYGAZ", "Depoda", "BEKLİYOR", CURRENT_YEAR + 10, new_class, int(new_pd), int(new_spd)))
                            conn.commit()
                            conn.close()
                            audit(active_user, "Arşiv Kaydı", f"{new_reg} · {new_doc_name}", "ARŞİV_BELGE", new_reg)
                            st.success("Kayıt başarıyla oluşturuldu.")
                            st.rerun()

            with st.expander("📥 Toplu Arşiv Kaydı Yükle (Excel/CSV)"):
                uploaded_file = st.file_uploader("Eski sistemden dışa aktarılan Excel/CSV dosyasını seçin", type=["xlsx", "xls", "csv"])
                if uploaded_file:
                    try:
                        import_df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv") else pd.read_excel(uploaded_file)
                        st.write("Veri Önizlemesi (İlk 3 Kayıt):", import_df.head(3))
                        if st.button("Veritabanına Aktarımı Başlat", type="primary"):
                            conn = get_db()
                            cursor = conn.cursor()
                            count = 0
                            for _, r in import_df.iterrows():
                                cursor.execute("""
                                    INSERT OR REPLACE INTO aygaz_main_archive 
                                    (doc_reg_no, doc_no, doc_name, series_code, unit_code, first_doc_date, last_doc_date, box_no, shelf_no, institution, status, destruction_status, retention_end_year, classification)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    str(r.get("Kayıt No", uuid.uuid4().hex[:6])),
                                    str(r.get("Dosya No", "")),
                                    str(r.get("Belge", r.get("Belge Adı", "İsimsiz Evrak"))),
                                    str(r.get("Seri", "1")),
                                    str(r.get("Birim", "1004")),
                                    str(r.get("İlk Evrak Tarihi", "")),
                                    str(r.get("Son Evrak Tarihi", "")),
                                    str(r.get("Kutu No", "")),
                                    str(r.get("Yer No", "")),
                                    str(r.get("Kurum", "AYGAZ A.Ş.")),
                                    str(r.get("Durum", "Depoda")),
                                    "BEKLİYOR",
                                    int(r.get("Saklama Sonu", CURRENT_YEAR + 10)),
                                    str(r.get("Gizlilik", "INTERNAL"))
                                ))
                                count += 1
                            conn.commit()
                            conn.close()
                            audit(active_user, "Toplu Aktarım", f"{count} adet kayıt içeri alındı", "TOPLU_AKTARIM", "")
                            st.success(f"{count} adet kayıt başarıyla veritabanına işlendi.")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Aktarım hatası: {e}")

    with right:
        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">Kayıt Detayı & KVKK</div></div>', unsafe_allow_html=True)
        if not catalog_df.empty:
            selected_reg = st.selectbox("İncelenecek kayıt", catalog_df["Kayıt No"].tolist(), label_visibility="collapsed")
            selected = catalog_df[catalog_df["Kayıt No"] == selected_reg].iloc[0]
            
            hold_status = selected.get("Hukuki Kilit", "SERBEST")
            hold_badge = '<span class="badge badge-hold">🔒 HUKUKİ BLOKE</span>' if "BLOKE" in hold_status else '<span class="badge badge-clean">İMHAYA AÇIK</span>'
            
            st.markdown(
                f'<div class="eyebrow">KAYIT / {selected["Kayıt No"]}</div>'
                f'<h3>{selected["Belge"]}</h3>'
                f'<p><b>Fiziksel Konum:</b> KUTU {selected["Kutu No"]} · RAF {selected["Yer No"]}<br>'
                f'<b>Birim / Seri:</b> {selected["Birim"]} / {selected["Seri"]}<br>'
                f'<b>Gizlilik Sınıfı:</b> <code>{selected["Gizlilik"]}</code><br>'
                f'<b>Hukuki Durum:</b> {hold_badge}</p>'
                f'<div style="color:#0072bc;font-weight:700">● {selected["Durum"]}</div>',
                unsafe_allow_html=True
            )
            audit(active_user, "Belge Görüntüleme", f"Kayıt No: {selected['Kayıt No']} incelendi", "ARŞİV_BELGE", str(selected["Kayıt No"]))
            
            if st.button("Bu kayıt için talep aç", type="primary", width="stretch"):
                st.session_state["request_doc"] = f"#{selected['Kayıt No']} · {selected['Belge']}"
                st.session_state["request_open"] = True
                st.rerun()
        else:
            st.info("Filtrelere uyan kayıt bulunamadı.")
        st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.get("request_open"):
        st.markdown("### Yeni Erişim Talebi (Zincir Takibi)")
        with st.form("catalog_request"):
            c1, c2 = st.columns(2)
            with c1:
                st.text_input("Seçilen Kayıt", value=st.session_state.get("request_doc", ""), disabled=True)
                request_type = st.selectbox("Erişim Biçimi", ["Fiziksel Zimmet", "Dijital Tarama (PDF/OCR)"])
            with c2:
                request_urgency = st.selectbox("Öncelik Seviyesi", ["Normal", "Acil", "Kritik"])
                request_note = st.text_area("Talep Gerekçesi", placeholder="Hukuki inceleme, teftiş veya operasyonel amaç...")
            if st.form_submit_button("Talebi Yetkili Kuyruğuna Gönder", type="primary"):
                request_no = f"TR-{uuid.uuid4().hex[:8].upper()}"
                conn = get_db()
                conn.execute("""
                    INSERT INTO archive_requests (req_no, requester, unit_code, doc_item, delivery_type, urgency, status, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (request_no, active_name, active_unit, st.session_state.get("request_doc", ""), request_type, request_urgency, "Onay Bekliyor", request_note, datetime.now(TR_TZ).strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()
                conn.close()
                audit(active_user, "Talep Açma", f"{request_no} numaralı talep kuyruğa alındı", "TALEP", request_no)
                st.session_state["request_open"] = False
                st.success(f"{request_no} numaralı erişim talebi oluşturuldu.")
                st.rerun()

# =========================================================
# MENÜ 2: TANIMLAR (ADMIN)
# =========================================================
elif menu == "Tanımlar" and is_admin:
    header("Tanımlar", "Kurumsal sınıflandırma şeması, saklama planı ve kullanıcı yetki matrisi.")
    definition_tabs = st.tabs(["Birimler", "Seriler (Saklama Planı)", "Kurumlar", "Kullanıcılar (RBAC)"])
    
    with definition_tabs[0]:
        unit_df = read_df("SELECT id AS [ID], name AS [Birim Adı], code AS [Birim Kodu], inst_code AS [Kurum Kodu], inst_name AS [Kurum Adı] FROM units ORDER BY id")
        st.dataframe(unit_df, width="stretch", hide_index=True, height=350)
        with st.expander("Yeni Birim Tanımla"):
            with st.form("new_unit_form"):
                u_name = st.text_input("Birim Adı")
                u_code = st.text_input("Birim Kodu")
                if st.form_submit_button("Birimi Kaydet", type="primary") and u_name and u_code:
                    conn = get_db()
                    conn.execute("INSERT INTO units (name, code, inst_code, inst_name) VALUES (?, ?, '10', 'AYGAZ A.Ş.')", (u_name.strip(), u_code.strip()))
                    conn.commit()
                    conn.close()
                    audit(active_user, "Birim Tanımı", f"{u_code} - {u_name}", "TANIM", u_code)
                    st.success("Birim eklendi.")
                    st.rerun()

    with definition_tabs[1]:
        st.markdown("**Standart Dosya Planı ve Saklama Süreleri (ISO 15489-1)**")
        series_df = read_df("SELECT series_code AS [Seri], name AS [Seri Adı], unit_code AS [Birim], retention_year AS [Saklama (Yıl)], legal_basis AS [Mevzuat Dayanağı], kvkk_category AS [KVKK Sınıfı] FROM series ORDER BY id")
        st.dataframe(series_df, width="stretch", hide_index=True, height=350)
        with st.expander("Yeni Seri ve Saklama Kuralı Ekle"):
            with st.form("new_series_form"):
                s_code = st.text_input("Seri Kodu")
                s_name = st.text_input("Seri Adı")
                s_unit = st.text_input("Birim Kodu")
                s_ret = st.number_input("Yasal Saklama Süresi (Yıl)", min_value=1, value=10)
                s_basis = st.text_input("Hukuki Dayanak (TTK, VUK, İSG vb.)")
                s_kvkk = st.selectbox("KVKK Veri Kategorisi", ["GENEL", "ÖZLÜK, KİMLİK", "FİNANSAL", "TİCARİ", "SAĞLIK, GÜVENLİK"])
                if st.form_submit_button("Seriyi Kaydet", type="primary") and s_code and s_name:
                    conn = get_db()
                    conn.execute("INSERT INTO series (series_code, name, unit_code, unit_name, retention_year, legal_basis, kvkk_category) VALUES (?, ?, ?, '', ?, ?, ?)", (s_code.strip(), s_name.strip(), s_unit.strip(), s_ret, s_basis.strip(), s_kvkk))
                    conn.commit()
                    conn.close()
                    audit(active_user, "Seri Tanımı", f"Seri {s_code} eklendi", "TANIM", s_code)
                    st.success("Seri kuralı kaydedildi.")
                    st.rerun()

    with definition_tabs[2]:
        inst_df = read_df("SELECT id AS [ID], name AS [Kurum Adı], code AS [Kurum Kodu] FROM institutions ORDER BY id")
        st.dataframe(inst_df, width="stretch", hide_index=True, height=350)

    with definition_tabs[3]:
        st.markdown("### Kullanıcı ve Yetki Matrisi (Role-Based Access Control)")
        u_list = read_df("SELECT id AS [ID], username AS [Sicil/Kullanıcı], full_name AS [Ad Soyad], unit_code AS [Birim], auth_codes AS [Yetkiler], role_desc AS [Rol] FROM user_permissions ORDER BY id")
        st.dataframe(u_list, width="stretch", hide_index=True)
        with st.expander("👤 Yeni Kullanıcı ve Yetki Tanımla"):
            with st.form("new_rbac_user"):
                usr_name = st.text_input("Kullanıcı Adı / Sicil No")
                usr_full = st.text_input("Ad Soyad")
                usr_unit = st.text_input("Birim Kodu (Tüm Birimler İçin ALL)")
                usr_role = st.selectbox("Kurumsal Rol", ["Arşiv Yöneticisi", "Birim Arşiv Sorumlusu", "Birim Kullanıcısı", "Denetçi", "Hukuk Müşaviri"])
                usr_auth = st.multiselect("Yetki Kodları", ["ADMIN", "TALEP_YONETIM", "IMHA", "LEGAL_HOLD", "DENETIM"], default=["TALEP_YONETIM"])
                if st.form_submit_button("Kullanıcıyı Yetkilendir", type="primary") and usr_name and usr_full:
                    conn = get_db()
                    conn.execute("INSERT OR REPLACE INTO user_permissions (username, full_name, unit_code, auth_codes, role_desc) VALUES (?, ?, ?, ?, ?)", (usr_name.strip(), usr_full.strip(), usr_unit.strip(), ",".join(usr_auth), usr_role))
                    conn.commit()
                    conn.close()
                    audit(active_user, "Kullanıcı Tanımı", f"{usr_name} ({usr_role}) yetkilendirildi", "RBAC", usr_name)
                    st.success("Kullanıcı tanımlandı.")
                    st.rerun()

# =========================================================
# MENÜ 3: ERİŞİM TALEPLERİ (ZİMMET ZİNCİRİ)
# =========================================================
elif menu == "Erişim Talepleri":
    header("Erişim talepleri", "Arşiv evraklarına erişim, fiziki teslimat ve iade takibi.")
    can_manage = can_manage_requests(active_row)
    filter_sql = "" if can_manage else " AND requester = ?"
    filter_params = () if can_manage else (active_name,)

    queue_df = read_df(
        f"""
        SELECT id, req_no AS [Talep], requester AS [Talep Eden], unit_code AS [Birim],
               doc_item AS [Kayıt], delivery_type AS [Teslim], urgency AS [Öncelik],
               status AS [Durum], created_at AS [Oluşturuldu], notes AS [Not]
        FROM archive_requests WHERE 1=1 {filter_sql} ORDER BY id DESC
        """,
        filter_params
    )

    q1, q2, q3 = st.columns(3)
    q1.metric("Toplam Talep", len(queue_df))
    q2.metric("Onay Bekleyen", int((queue_df["Durum"] == "Onay Bekliyor").sum()) if not queue_df.empty else 0)
    q3.metric("Acil İşler", int(queue_df["Öncelik"].isin(["Acil", "Kritik"]).sum()) if not queue_df.empty else 0)
    st.markdown("<br>", unsafe_allow_html=True)

    if queue_df.empty:
        st.info("Görüntülenecek erişim talebi bulunmamaktadır.")
    else:
        st.dataframe(queue_df.drop(columns=["id"], errors="ignore"), width="stretch", hide_index=True, height=300)
        st.markdown("### Talep İşlemleri & Teslimat Zinciri")
        u1, u2, u3 = st.columns([2, 2, 1])
        with u1:
            selected_request = st.selectbox("İşlem Yapılacak Talep", queue_df["Talep"].tolist())
        with u2:
            new_status = st.selectbox("Durum Güncelle", ["Onay Bekliyor", "Hazırlanıyor", "Kuryede / Teslimde", "Teslim Edildi (Zimmette)", "Tamamlandı / İade", "İptal / Red"])
        with u3:
            if can_manage:
                if st.button("Durumu Güncelle", type="primary", width="stretch"):
                    conn = get_db()
                    conn.execute("UPDATE archive_requests SET status = ? WHERE req_no = ?", (new_status, selected_request))
                    conn.commit()
                    conn.close()
                    audit(active_user, "Talep Durumu", f"{selected_request} durumu '{new_status}' yapıldı", "TALEP", selected_request)
                    st.success("Talep güncellendi.")
                    st.rerun()
            else:
                st.caption("Talep durumunu yalnızca yetkili arşiv sorumluları değiştirebilir.")

        st.markdown("### Talep İçi İletişim & Denetim Notları")
        msg_df = read_df("SELECT sender AS [Gönderen], message AS [Mesaj], created_at AS [Tarih] FROM request_messages WHERE req_no = ? ORDER BY id ASC", params=[selected_request])
        if not msg_df.empty:
            st.dataframe(msg_df, width="stretch", hide_index=True)
        with st.form("req_msg"):
            msg_text = st.text_input("Mesaj / Kurye Teslim Notu")
            if st.form_submit_button("Mesajı Ekle") and msg_text.strip():
                conn = get_db()
                conn.execute("INSERT INTO request_messages (req_no, sender, message, created_at) VALUES (?, ?, ?, ?)", (selected_request, active_name, msg_text.strip(), datetime.now(TR_TZ).strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()
                conn.close()
                st.rerun()

# =========================================================
# MENÜ 4: SAKLAMA VE İMHA (ÇOK AŞAMALI ONAY & KİLİT)
# =========================================================
elif menu == "Saklama ve imha" and can_manage_destruction(active_row):
    header("Saklama ve imha yönetimi", "Yasal saklama süresi dolan belgelerin onay zinciri ve imha icrası.")
    tab1, tab2 = st.tabs(["İmha Adayları (Süresi Dolanlar)", "İmha Edilen Belgeler ve Tutanaklar"])

    with tab1:
        st.markdown("#### Yasal Saklama Süresi Dolan Kayıtlar")
        pending_df = read_df("""
            SELECT doc_reg_no AS 'Kayıt No', doc_no AS 'Dosya No', doc_name AS 'Belge Adı',
                   unit_code AS 'Birim', retention_end_year AS 'İmha Yılı', legal_hold_count AS 'Bloke Sayısı',
                   destruction_status AS 'Durum'
            FROM aygaz_main_archive 
            WHERE (destruction_status IS NULL OR destruction_status != 'İMHA EDİLDİ') 
              AND CAST(retention_end_year AS INTEGER) <= ?
        """, (CURRENT_YEAR,))

        if not pending_df.empty:
            st.dataframe(pending_df, width="stretch", hide_index=True)
            st.markdown("---")
            st.markdown("### İmha Kararı ve İcra Formu")
            c_sel, c_met, c_btn = st.columns([2, 2, 1])
            with c_sel:
                target_doc = st.selectbox("İmha Edilecek Kayıt No", pending_df["Kayıt No"].tolist())
            with c_met:
                dest_method = st.selectbox("İmha Yöntemi", ["Tutanak Karşılığı Fiziksel Kıyım (P-4 DIN 66399)", "Endüstriyel Hamurlaştırma", "Dijital Güvenli Silme (DoD 5220.22-M)"])
            with c_btn:
                st.write("")
                st.write("")
                if st.button("İmha Kararını Onayla ve İcra Et", type="primary", width="stretch"):
                    res = execute_destruction(target_doc, active_user, method=dest_method)
                    if res:
                        st.success(f"Kayıt No {target_doc} başarıyla imha edildi ve tutanak kütüğüne işlendi.")
                        st.rerun()
                    else:
                        st.error("İŞLEM ENGELLENDİ: Bu belge üzerinde aktif bir 'Hukuki Engel (Legal Hold)' bulunmaktadır! Blokaj kaldırılmadan imha edilemez.")
        else:
            st.info(f"{CURRENT_YEAR} yılı itibarıyla imha süresi dolmuş bekleyen evrak bulunmamaktadır.")

    with tab2:
        st.markdown(f"#### {CURRENT_YEAR} Yılı Resmi İmha Kütüğü")
        destroyed_df = get_destroyed_records(year_filter=str(CURRENT_YEAR))
        if not destroyed_df.empty:
            st.dataframe(destroyed_df, width="stretch", hide_index=True)
            download_excel(f"{CURRENT_YEAR} İmha Tutanağını İndir (Excel)", destroyed_df, f"Aygaz_Imha_Tutanagi_{CURRENT_YEAR}.xlsx", sheet_name="Imha_Kutugu")
        else:
            st.info(f"{CURRENT_YEAR} yılı için henüz imhası tamamlanmış belge kaydı bulunmuyor.")

# =========================================================
# MENÜ 5: HUKUKİ ENGEL (LEGAL HOLD MODÜLÜ)
# =========================================================
elif menu == "Hukuki Engel (Legal Hold)" and can_manage_legal_hold(active_row):
    header("Hukuki engel yönetimi", "Devam eden dava, vergi denetimi veya teftiş nedeniyle imha blokajı.")
    st.markdown('<div class="hint">Bir belgeye Hukuki Engel (Legal Hold) konulduğunda, yasal saklama süresi dolsa dahi sistem tarafından imha edilmesi kesin olarak engellenir.</div><br>', unsafe_allow_html=True)
    
    holds_df = read_df("""
        SELECT lh.id, lh.hold_ref AS [Bloke No], lh.doc_reg_no AS [Kayıt No], 
               a.doc_name AS [Belge], lh.reason AS [Gerekçe], lh.authority AS [Merci/Mahkeme], 
               lh.created_by AS [Bloke Koyan], lh.created_at AS [Tarih],
               CASE WHEN lh.active = 1 THEN 'AKTİF BLOKE' ELSE 'KALDIRILDI' END AS [Durum]
        FROM legal_holds lh
        LEFT JOIN aygaz_main_archive a ON lh.doc_reg_no = a.doc_reg_no
        ORDER BY lh.id DESC
    """)
    st.dataframe(holds_df, width="stretch", hide_index=True)

    h_col1, h_col2 = st.columns(2)
    with h_col1:
        with st.expander("🔒 Yeni Hukuki Blokaj (Hold) Ekle"):
            with st.form("new_hold"):
                h_doc = st.text_input("Bloke Konulacak Kayıt No")
                h_reason = st.text_area("Hukuki Gerekçe (Örn: İstanbul 4. İş Mahkemesi 2026/142 E.)")
                h_auth = st.text_input("Talep Eden Merci / Hukuk Birimi")
                if st.form_submit_button("Hukuki Engeli İşle", type="primary") and h_doc and h_reason:
                    conn = get_db()
                    h_ref = f"HOLD-{uuid.uuid4().hex[:6].upper()}"
                    conn.execute("INSERT INTO legal_holds (doc_reg_no, hold_ref, reason, authority, created_by, created_at, active) VALUES (?, ?, ?, ?, ?, ?, 1)", (h_doc.strip(), h_ref, h_reason.strip(), h_auth.strip(), active_user, datetime.now(TR_TZ).strftime("%Y-%m-%d %H:%M:%S")))
                    conn.execute("UPDATE aygaz_main_archive SET legal_hold_count = legal_hold_count + 1 WHERE doc_reg_no = ?", (h_doc.strip(),))
                    conn.commit()
                    conn.close()
                    audit(active_user, "Legal Hold Uygulama", f"Kayıt {h_doc} üzerine {h_ref} blokajı konuldu", "LEGAL_HOLD", h_doc)
                    st.success("Hukuki engel aktif edildi. Belge imha korumasına alındı.")
                    st.rerun()

    with h_col2:
        with st.expander("🔓 Aktif Blokajı Kaldır"):
            active_holds = read_df("SELECT hold_ref, doc_reg_no FROM legal_holds WHERE active = 1")
            if not active_holds.empty:
                with st.form("release_hold"):
                    rel_ref = st.selectbox("Kaldırılacak Bloke", active_holds["hold_ref"].tolist())
                    if st.form_submit_button("Blokajı Serbest Bırak", type="primary"):
                        target_reg = active_holds[active_holds["hold_ref"] == rel_ref].iloc[0]["doc_reg_no"]
                        conn = get_db()
                        conn.execute("UPDATE legal_holds SET active = 0 WHERE hold_ref = ?", (rel_ref,))
                        conn.execute("UPDATE aygaz_main_archive SET legal_hold_count = MAX(0, legal_hold_count - 1) WHERE doc_reg_no = ?", (target_reg,))
                        conn.commit()
                        conn.close()
                        audit(active_user, "Legal Hold Kaldırma", f"{rel_ref} kaldırıldı (Kayıt {target_reg})", "LEGAL_HOLD", target_reg)
                        st.success("Blokaj kaldırıldı.")
                        st.rerun()
            else:
                st.info("Aktif hukuki engel bulunmuyor.")

# =========================================================
# MENÜ 6: GÜNLÜKLER VE YÖNETİM RAPORLARI (ADMIN)
# =========================================================
elif menu == "Günlükler" and is_admin:
    header("Yönetim raporları", "Arşiv kapasitesi, risk analizleri ve hareket dağılımları.")
    unit_rep = read_df("""
        SELECT unit_code AS [Birim], COUNT(*) AS [Toplam Belge], 
               SUM(CASE WHEN status = 'Zimmette' THEN 1 ELSE 0 END) AS [Zimmette], 
               SUM(CASE WHEN legal_hold_count > 0 THEN 1 ELSE 0 END) AS [Hukuki Kilitli],
               SUM(CASE WHEN retention_end_year <= ? AND (destruction_status IS NULL OR destruction_status != 'İMHA EDİLDİ') THEN 1 ELSE 0 END) AS [Süresi Dolan] 
        FROM aygaz_main_archive GROUP BY unit_code ORDER BY [Toplam Belge] DESC
    """, (CURRENT_YEAR,))
    
    status_rep = read_df("SELECT status AS [Durum], COUNT(*) AS [Adet] FROM aygaz_main_archive GROUP BY status")
    
    r1, r2 = st.columns(2)
    with r1:
        st.markdown("### Birim Bazlı Arşiv Dağılımı")
        st.dataframe(unit_rep, width="stretch", hide_index=True, height=260)
        st.bar_chart(unit_rep.set_index("Birim")[["Toplam Belge", "Zimmette", "Süresi Dolan"]])
    with r2:
        st.markdown("### Fiziki Durum Dağılımı")
        st.dataframe(status_rep, width="stretch", hide_index=True, height=260)
        st.bar_chart(status_rep.set_index("Durum"))

    download_excel("Yönetim Raporunu İndir", unit_rep, "aygaz-arsiv-yonetim-raporu.xlsx", sheet_name="Birim Raporu", extra_sheets={"Durum Raporu": status_rep})

# =========================================================
# MENÜ 7: KRİPTOGRAFİK DENETİM İZİ (AUDIT TRAIL)
# =========================================================
elif menu == "Denetim izi" and can_view_audit(active_row):
    header("Denetim izi", "Kim, ne zaman, hangi veriye erişti? (Değiştirilemez SHA-256 Hash Zinciri)")
    st.markdown('<div class="hint">Bu akış ISO 27001 ve ISO 15489 standartlarına uygun olarak her işlemi bir önceki kaydın SHA-256 kriptografik özetiyle birbirine bağlar (Blockchain mantığı). Kayıtlar geriye dönük manipüle edilemez.</div><br>', unsafe_allow_html=True)
    
    audit_data = read_df("""
        SELECT timestamp AS [Zaman], user AS [Kullanıcı], action_type AS [İşlem Türü], 
               object_id AS [Kayıt/Nesne No], details AS [Operasyon Detayı],
               event_hash AS [SHA-256 Kriptografik İmza]
        FROM archive_audit ORDER BY id DESC LIMIT 200
    """)
    st.dataframe(audit_data, width="stretch", hide_index=True, height=520)
    download_excel("Denetim İzini Dışa Aktar (Excel)", audit_data, "aygaz-arsiv-denetim-izi.xlsx", sheet_name="AuditTrail")
