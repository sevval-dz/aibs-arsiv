from __future__ import annotations
from datetime import datetime, timezone, timedelta
import base64
import hashlib
import io
import logging
import os
from pathlib import Path
import sqlite3
import uuid

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# =========================================================
# LOGGING & HATA YÖNETİMİ
# =========================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AIBS")

# =========================================================
# SAYFA VE ALTYAPI YAPILANDIRMASI
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
# SIDEBAR BUTONU VE ARAYÜZ (CSS & JS BİREBİR KORUNDU)
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
</style>
""", unsafe_allow_html=True)

# =========================================================
# VERİTABANI BAĞLANTISI VE MIGRATION MOTORU
# =========================================================
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}

def ensure_column_exists(conn: sqlite3.Connection, table_name: str, col_name: str, col_type: str) -> None:
    cols = get_table_columns(conn, table_name)
    if col_name not in cols:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
        logger.info(f"Migration: {table_name}.{col_name} kolonu başarıyla eklendi.")

def init_database() -> None:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS institutions (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS units (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT NOT NULL UNIQUE,
                inst_code TEXT,
                inst_name TEXT
            );

            CREATE TABLE IF NOT EXISTS series (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                unit_code TEXT,
                unit_name TEXT,
                series_code TEXT NOT NULL UNIQUE,
                retention_year INTEGER,
                legal_basis TEXT
            );

            CREATE TABLE IF NOT EXISTS user_permissions (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                unit_code TEXT NOT NULL DEFAULT 'ALL',
                auth_codes TEXT,
                role_desc TEXT,
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
                result TEXT DEFAULT 'SUCCESS',
                previous_hash TEXT,
                event_hash TEXT NOT NULL
            );
        """)

        # Migration 1: series tablosu eksik kolonları
        ensure_column_exists(conn, "series", "trigger_event", "TEXT DEFAULT 'Dosyanın Kapanışı'")
        ensure_column_exists(conn, "series", "disposition", "TEXT DEFAULT 'İMHA'")
        ensure_column_exists(conn, "series", "confidentiality", "TEXT DEFAULT 'INTERNAL'")

        # Migration 2: user_permissions tablosu eksik kolonları
        ensure_column_exists(conn, "user_permissions", "active", "INTEGER DEFAULT 1")

        # Migration 3: aygaz_main_archive tablosu eksik kolonları
        ensure_column_exists(conn, "aygaz_main_archive", "destruction_date", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "destruction_status", "TEXT DEFAULT 'BEKLİYOR'")
        ensure_column_exists(conn, "aygaz_main_archive", "retention_end_year", "INTEGER")
        ensure_column_exists(conn, "aygaz_main_archive", "classification", "TEXT DEFAULT 'INTERNAL'")
        ensure_column_exists(conn, "aygaz_main_archive", "legal_hold", "INTEGER DEFAULT 0")
        ensure_column_exists(conn, "aygaz_main_archive", "legal_hold_reason", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "destruction_requested_by", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "created_by", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "created_at", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "updated_by", "TEXT")
        ensure_column_exists(conn, "aygaz_main_archive", "updated_at", "TEXT")

        # Migration 4: archive_requests tablosu geriye dönük uyumluluk
        ensure_column_exists(conn, "archive_requests", "unit_code", "TEXT")
        ensure_column_exists(conn, "archive_requests", "notes", "TEXT")

        # Migration 5: archive_audit tablosu hash zinciri ve alanları
        ensure_column_exists(conn, "archive_audit", "object_id", "TEXT")
        ensure_column_exists(conn, "archive_audit", "result", "TEXT DEFAULT 'SUCCESS'")
        ensure_column_exists(conn, "archive_audit", "previous_hash", "TEXT")
        ensure_column_exists(conn, "archive_audit", "event_hash", "TEXT")

        # Veri Standardizasyonu: Edilmedi/BEKLİYOR uyumluluğu
        cursor.execute("""
            UPDATE aygaz_main_archive 
            SET destruction_status = 'BEKLİYOR' 
            WHERE destruction_status IS NULL 
               OR UPPER(destruction_status) IN ('EDILMEDI', 'EDİLMEDİ', 'BEKLEMEDE')
        """)

        # Migration sonrası güvenli index oluşturma
        cursor.executescript("""
            CREATE INDEX IF NOT EXISTS idx_archive_search ON aygaz_main_archive (unit_code, series_code, status);
            CREATE INDEX IF NOT EXISTS idx_archive_retention ON aygaz_main_archive (retention_end_year, destruction_status);
            CREATE INDEX IF NOT EXISTS idx_request_queue ON archive_requests (unit_code, status, created_at);
            CREATE INDEX IF NOT EXISTS idx_audit_time ON archive_audit (timestamp);
        """)

        # Tohum Verileri (Seed Data)
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

        cursor.executemany("INSERT OR IGNORE INTO series (id, name, unit_code, unit_name, series_code, retention_year, legal_basis, trigger_event) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            (1, "PERSONEL ÖZLÜK DOSYALARI", "1006", "İNSAN KAYNAKLARI MÜDÜRLÜĞÜ", "1", 10, "İş Kanunu Md. 75", "İş İlişkisinin Sona Ermesi"),
            (3, "MAKBUZ VE TAHSİLAT BELGELERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "3", 10, "VUK Md. 253", "Belgenin Düzenlenmesi"),
            (4, "MAHSUP VE YEVMİYE FİŞLERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "4", 10, "TTK Md. 82", "Hesap Döneminin Kapanışı"),
            (9, "TİCARİ BAYİLİK VE MÜLKİYET SÖZLEŞMELERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "9", 100, "Süresiz Saklama", "Sözleşmenin Sona Ermesi"),
            (11, "İŞ SAĞLIĞI VE AMBARLI TEFTİŞ RAPORLARI", "1008", "İŞLETME MÜHENDİSLİK YATIRIMLAR MÜDÜRLÜĞÜ", "11", 15, "6331 Sayılı İSGK", "Rapor Tarihi"),
        ])

        if cursor.execute("SELECT COUNT(*) FROM user_permissions").fetchone()[0] == 0:
            cursor.execute("INSERT INTO user_permissions (id, username, full_name, unit_code, auth_codes, role_desc, active) VALUES (?, ?, ?, ?, ?, ?, 1)", 
                           (1, "local\\admin", "Arşiv Yöneticisi", "ALL", "ADMIN,TALEP_YONETIM,IMHA,DENETIM,LEGAL_HOLD", "Yönetici"))

        if cursor.execute("SELECT COUNT(*) FROM aygaz_main_archive").fetchone()[0] == 0:
            cursor.executemany("""
                INSERT INTO aygaz_main_archive 
                (doc_reg_no, doc_no, doc_name, series_code, unit_code, first_doc_date, last_doc_date, box_no, shelf_no, institution, status, destruction_status, retention_end_year, classification, legal_hold)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                ("90101", "1411-23-201", "Bayi faaliyet raporları", "6", "1004", "01/08/2023", "31/08/2023", "23050", "H11.211", "AYGAZ", "Depoda", "BEKLİYOR", 2028, "INTERNAL", 0),
                ("90102", "1411-23-202", "Ticari bayilik sözleşmeleri", "9", "1004", "01/08/2023", "31/08/2023", "23051", "H11.212", "AYGAZ", "Zimmette", "BEKLİYOR", 2123, "CONFIDENTIAL", 0),
                ("90085", "1205-22-040", "İSG saha denetim raporları", "11", "1008", "10/05/2022", "15/05/2022", "22910", "H10.014", "AYGAZ", "Depoda", "BEKLİYOR", 2037, "INTERNAL", 0),
            ])

        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Veritabanı başlatma/migration hatası: {e}")
        st.error(f"Sistem veri tabanı başlatılırken bir hata oluştu: {e}")
    finally:
        conn.close()

init_database()

# =========================================================
# GÜÇLENDİRİLMİŞ AUDIT LOG (SHA-256 HASH ZİNCİRİ)
# =========================================================
def audit(user: str, action: str, details: str, object_id: str = "", result: str = "SUCCESS") -> None:
    conn = get_db()
    cursor = conn.cursor()
    try:
        now_str = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
        last_row = cursor.execute("SELECT event_hash FROM archive_audit ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = last_row[0] if (last_row and last_row[0]) else "0" * 64
        
        raw_payload = f"{now_str}|{user}|{action}|{details}|{object_id}|{result}|{prev_hash}"
        event_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
        
        cursor.execute("""
            INSERT INTO archive_audit (timestamp, user, action_type, details, object_id, result, previous_hash, event_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (now_str, user, action, details, object_id, result, prev_hash, event_hash))
        conn.commit()
    except Exception as e:
        logger.error(f"Audit log yazılamadı: {e}")
    finally:
        conn.close()

# =========================================================
# GÜVENLİ VERİ ERİŞİMİ VE YETKİLENDİRME (RBAC)
# =========================================================
def read_df(query: str, params: tuple | list = ()) -> pd.DataFrame:
    conn = get_db()
    try:
        return pd.read_sql_query(query, conn, params=params)
    except Exception as e:
        logger.error(f"Sorgu hatası [{query}]: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def normalize_auth_codes(auth_codes: Any) -> set[str]:
    if not auth_codes:
        return set()
    return {code.strip().upper() for code in str(auth_codes).split(",") if code.strip()}

def is_admin_user(user_row: pd.Series) -> bool:
    role = str(user_row["role_desc"] or "").strip().lower()
    unit = str(user_row["unit_code"] or "").strip().upper()
    auth_codes = normalize_auth_codes(user_row["auth_codes"])
    return (unit == "ALL" or "admin" in role or "yönetici" in role or "ADMIN" in auth_codes or "*" in auth_codes)

def has_permission(user_row: pd.Series, permission: str) -> bool:
    permission = permission.strip().upper()
    auth_codes = normalize_auth_codes(user_row["auth_codes"])
    if is_admin_user(user_row):
        return True
    return permission in auth_codes

def can_manage_requests(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "TALEP_YONETIM") or has_permission(user_row, "REQUEST_MANAGE")

def can_manage_destruction(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "IMHA") or has_permission(user_row, "DESTRUCTION")

def can_view_audit(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "DENETIM") or has_permission(user_row, "AUDIT")

def can_manage_legal_hold(user_row: pd.Series) -> bool:
    return is_admin_user(user_row) or has_permission(user_row, "LEGAL_HOLD")

# =========================================================
# EXCEL / CSV İŞLEMLERİ (AİBS UYUMLU)
# =========================================================
def convert_df_to_excel(sheets_dict: dict[str, pd.DataFrame]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in sheets_dict.items():
            df.to_excel(writer, index=False, sheet_name=str(sheet_name)[:31])
    return output.getvalue()

def download_excel(label: str, dataframe: pd.DataFrame, filename: str, sheet_name: str = "Arşiv Kataloğu", extra_sheets: dict | None = None, user: str = "local\\admin") -> None:
    sheets = {sheet_name: dataframe}
    if extra_sheets:
        sheets.update(extra_sheets)
    excel_data = convert_df_to_excel(sheets)
    audit(user, "Excel Dışa Aktarma", f"{filename} ({len(dataframe)} kayıt)", sheet_name)
    st.download_button(
        label=label,
        data=excel_data,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

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
# AKTİF KULLANICI VE YETKİ KAPSAMI YÖNETİMİ
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

    user_labels = [f"{row.full_name} · {row.unit_code}" for row in users_df.itertuples()]
    configured_user = os.getenv("AIBS_USER", "").casefold()
    default_index = next((index for index, row in enumerate(users_df.itertuples()) if str(row.username).casefold() == configured_user), 0)

    selected_user_label = st.selectbox("Kullanıcı", user_labels, index=default_index, label_visibility="visible")
    active_row = users_df.iloc[user_labels.index(selected_user_label)]
    active_name = active_row["full_name"]
    active_unit = active_row["unit_code"]
    active_user = active_row["username"]
    is_admin = is_admin_user(active_row)

    st.caption(f"{active_row['role_desc']} · {active_unit}")
    st.markdown("---")

    menu_options = ["Katalog", "Erişim Talepleri"]
    if is_admin:
        menu_options.extend(["Tanımlar", "Saklama ve imha", "Günlükler"])
    if can_view_audit(active_row):
        menu_options.append("Denetim izi")

    menu = st.radio("Çalışma alanı", menu_options, label_visibility="visible")
    st.markdown("---")
    st.caption("Sistem durumu")
    st.markdown('<div style="color:#ffffff;font-size:12px;font-weight:600;">Veritabanı bağlı</div>', unsafe_allow_html=True)
    st.caption(suanki_zaman().strftime("Son senkronizasyon  %d.%m.%Y · %H:%M"))

# =========================================================
# ÜST BİLGİ PANELİ (TOPBAR)
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

# Kapsam Metrikleri
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
# MENÜ: KATALOG
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
                   retention_end_year AS [Saklama Sonu], legal_hold AS [Hukuki Engel] 
            FROM aygaz_main_archive WHERE 1=1
        """
        params = []
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
        
        if is_admin:
            with st.expander("Yeni arşiv kaydı"):
                with st.form("new_archive_record"):
                    a1, a2, a3 = st.columns(3)
                    with a1:
                        new_reg = st.text_input("Kayıt no")
                        new_doc_no = st.text_input("Dosya no")
                        new_doc_name = st.text_input("Belge adı")
                    with a2:
                        new_series = st.text_input("Seri kodu")
                        new_unit = st.text_input("Birim kodu", value=active_unit if active_unit != "ALL" else "1004")
                        new_box = st.text_input("Kutu no")
                    with a3:
                        new_shelf = st.text_input("Raf / yer no")
                        new_first_date = st.text_input("İlk evrak tarihi", placeholder="GG/AA/YYYY")
                        new_last_date = st.text_input("Son evrak tarihi", placeholder="GG/AA/YYYY")
                    if st.form_submit_button("Arşiv kaydını oluştur", type="primary") and new_reg.strip() and new_doc_name.strip() and new_unit.strip():
                        if active_unit != "ALL" and new_unit.strip() != active_unit:
                            st.error(f"Yetki sınırınız gereği yalnızca {active_unit} birimine kayıt girebilirsiniz.")
                        else:
                            conn = get_db()
                            now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                            try:
                                conn.execute("""
                                    INSERT INTO aygaz_main_archive 
                                    (doc_reg_no, doc_no, doc_name, series_code, unit_code, first_doc_date, last_doc_date, box_no, shelf_no, institution, status, destruction_status, retention_end_year, created_by, created_at) 
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (new_reg.strip(), new_doc_no.strip(), new_doc_name.strip(), new_series.strip(), new_unit.strip(), new_first_date.strip(), new_last_date.strip(), new_box.strip(), new_shelf.strip(), "AYGAZ", "Depoda", "BEKLİYOR", CURRENT_YEAR + 10, active_user, now_stamp))
                                conn.commit()
                                audit(active_user, "Arşiv kaydı oluşturma", f"{new_reg} · {new_doc_name}", object_id=new_reg.strip())
                                st.success("Arşiv kaydı oluşturuldu.")
                                st.rerun()
                            except sqlite3.IntegrityError:
                                st.error("Bu kayıt numarası sistemde zaten mevcut.")
                            finally:
                                conn.close()

            with st.expander("📥 Toplu Arşiv Kaydı Yükle (Excel/CSV)"):
                uploaded_file = st.file_uploader("Eski sistemden dışa aktarılan Excel/CSV dosyasını seçin", type=["xlsx", "xls", "csv"])
                if uploaded_file:
                    try:
                        import_df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv") else pd.read_excel(uploaded_file)
                        st.write("Yüklenecek Veri Önizlemesi:", import_df.head(3))
                        if st.button("Veritabanına Aktarımı Başlat", type="primary"):
                            conn = get_db()
                            cursor = conn.cursor()
                            success_count = 0
                            now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                            try:
                                for _, row in import_df.iterrows():
                                    row_unit = str(row.get("Birim", "1004")).strip()
                                    if active_unit != "ALL" and row_unit != active_unit:
                                        continue
                                    cursor.execute("""
                                        INSERT OR REPLACE INTO aygaz_main_archive 
                                        (doc_reg_no, doc_no, doc_name, series_code, unit_code, first_doc_date, last_doc_date, box_no, shelf_no, institution, status, destruction_status, retention_end_year, created_by, created_at)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """, (
                                        str(row.get("Kayıt No", uuid.uuid4().hex[:8])),
                                        str(row.get("Dosya No", "")),
                                        str(row.get("Belge", row.get("Belge Adı", "İsimsiz Evrak"))),
                                        str(row.get("Seri", "1")),
                                        row_unit,
                                        str(row.get("İlk Evrak Tarihi", "")),
                                        str(row.get("Son Evrak Tarihi", "")),
                                        str(row.get("Kutu No", "")),
                                        str(row.get("Yer No", "")),
                                        str(row.get("Kurum", "AYGAZ A.Ş.")),
                                        str(row.get("Durum", "Depoda")),
                                        "BEKLİYOR",
                                        int(row.get("Saklama Sonu", CURRENT_YEAR + 10)),
                                        active_user,
                                        now_stamp
                                    ))
                                    success_count += 1
                                conn.commit()
                                audit(active_user, "Toplu Veri İçe Aktarma", f"{success_count} adet kayıt aktarıldı")
                                st.success(f"{success_count} adet arşiv kaydı başarıyla aktarıldı!")
                                st.rerun()
                            except Exception as import_err:
                                conn.rollback()
                                logger.error(f"İçe aktarma hatası: {import_err}")
                                st.error(f"İçe aktarım sırasında hata oluştu ve işlem geri alındı: {import_err}")
                            finally:
                                conn.close()
                    except Exception as e:
                        st.error(f"Dosya okuma hatası: {e}")

    with right:
        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">Kayıt Detayı</div></div>', unsafe_allow_html=True)
        if not catalog_df.empty:
            selected_reg = st.selectbox("İncelenecek kayıt", catalog_df["Kayıt No"].tolist(), label_visibility="collapsed")
            selected = catalog_df[catalog_df["Kayıt No"] == selected_reg].iloc[0]
            
            hold_txt = "AKTİF KİLİT" if selected.get("Hukuki Engel", 0) == 1 else "KİLİT YOK"
            hold_color = "#d47d36" if selected.get("Hukuki Engel", 0) == 1 else "#148b80"
            
            st.markdown(f'<div class="eyebrow">KAYIT / {selected["Kayıt No"]}</div><h3>{selected["Belge"]}</h3><p><b>Fiziksel konum</b><br><span class="mono">KUTU {selected["Kutu No"]} · RAF {selected["Yer No"]}</span></p><p><b>Birim</b> {selected["Birim"]}<br><b>Seri</b> {selected["Seri"]}<br><b>Hukuki Durum:</b> <span style="color:{hold_color};font-weight:700">{hold_txt}</span></p><div style="color:#1472bc;font-weight:700">● {selected["Durum"]}</div>', unsafe_allow_html=True)
            audit(active_user, "Kayıt Görüntüleme", f"Kayıt No: {selected['Kayıt No']} incelendi", object_id=str(selected["Kayıt No"]))

            if can_manage_legal_hold(active_row):
                is_currently_held = int(selected.get("Hukuki Engel", 0)) == 1
                hold_btn_label = "Hukuki Kilidi Kaldır" if is_currently_held else "Hukuki Kilit Koy (Hold)"
                if st.button(hold_btn_label, width="stretch"):
                    conn = get_db()
                    new_hold_state = 0 if is_currently_held else 1
                    conn.execute("UPDATE aygaz_main_archive SET legal_hold = ? WHERE doc_reg_no = ?", (new_hold_state, selected['Kayıt No']))
                    conn.commit()
                    conn.close()
                    audit(active_user, "Hukuki Kilit Değişimi", f"Kayıt {selected['Kayıt No']} kilit durumu: {new_hold_state}", object_id=str(selected['Kayıt No']))
                    st.rerun()

            if st.button("Bu kayıt için talep aç", type="primary", width="stretch"): 
                st.session_state["request_doc"] = f"#{selected['Kayıt No']} · {selected['Belge']}"
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
                request_doc = st.text_input("Kayıt", value=st.session_state.get("request_doc", ""), disabled=True)
                request_type = st.selectbox("Erişim biçimi", ["Fiziksel zimmet", "Dijital tarama (PDF)"])
            with c2: 
                request_urgency = st.selectbox("Öncelik", ["Normal", "Acil", "Kritik"])
                request_note = st.text_area("Gerekçe", placeholder="İnceleme amacı veya teslim notu...")
            if st.form_submit_button("Talebi kuyruğa al", type="primary"):
                request_no = f"TR-{uuid.uuid4().hex[:8].upper()}"
                conn = get_db()
                now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("""
                    INSERT INTO archive_requests (req_no, requester, unit_code, doc_item, delivery_type, urgency, status, notes, created_at) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (request_no, active_name, active_unit, request_doc, request_type, request_urgency, "Onay Bekliyor", request_note, now_stamp))
                conn.commit()
                conn.close()
                audit(active_user, "Erişim Talebi Oluşturma", f"{request_no} · {request_doc}", object_id=request_no)
                st.session_state["request_open"] = False
                st.success(f"{request_no} numaralı talep kuyruğa alındı.")
                st.rerun()

# =========================================================
# MENÜ: TANIMLAR (ADMIN)
# =========================================================
elif menu == "Tanımlar" and is_admin:
    header("Tanımlar", "Mevcut Aygaz arşiv sınıflandırmasını bozmadan kurum, birim ve seri kayıtlarını incele.")
    definition_tabs = st.tabs(["Birimler", "Seriler", "Kurumlar", "Kullanıcılar"])
    
    with definition_tabs[0]:
        unit_search = st.text_input("Birimlerde ara", placeholder="Birim adı veya kodu...")
        unit_query = "SELECT id AS [ID], name AS [Birim Adı], code AS [Birim Kodu], inst_code AS [Kurum Kodu], inst_name AS [Kurum Adı] FROM units WHERE 1=1"
        unit_params = []
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
                    conn = get_db()
                    try:
                        conn.execute("INSERT INTO units (name, code, inst_code, inst_name) VALUES (?, ?, ?, ?)", (new_unit_name.strip(), new_unit_code.strip(), new_unit_inst.strip(), "AYGAZ A.Ş."))
                        conn.commit()
                        audit(active_user, "Birim Tanımı", f"{new_unit_code} · {new_unit_name}", object_id=new_unit_code.strip())
                        st.success("Birim kaydedildi.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Bu birim kodu zaten kayıtlı.")
                    finally:
                        conn.close()

    with definition_tabs[1]:
        series_search = st.text_input("Serilerde ara", placeholder="Seri adı, kodu veya mevzuat...")
        series_query = "SELECT id AS [ID], name AS [Seri Adı], unit_code AS [Birim Kodu], unit_name AS [Birim], series_code AS [Seri Kodu], retention_year AS [Saklama (Yıl)], legal_basis AS [Mevzuat Dayanağı], trigger_event AS [Süreç Tetikleyicisi] FROM series WHERE 1=1"
        series_params = []
        if series_search.strip():
            series_query += " AND (name LIKE ? OR series_code LIKE ? OR legal_basis LIKE ?)"
            series_params.extend([f"%{series_search.strip()}%"] * 3)
        st.dataframe(read_df(series_query + " ORDER BY id", series_params), width="stretch", hide_index=True, height=400)
        with st.expander("Yeni seri kaydı"):
            with st.form("new_series"):
                new_series_name = st.text_input("Seri adı")
                new_series_code = st.text_input("Seri kodu")
                new_series_unit = st.text_input("Birim kodu")
                new_series_retention = st.number_input("Süre (yıl)", min_value=0, value=10)
                new_series_basis = st.text_input("Mevzuat dayanağı")
                new_series_trigger = st.text_input("Süreç tetikleyicisi", value="Dosyanın Kapanışı")
                if st.form_submit_button("Seriyi kaydet", type="primary") and new_series_name.strip() and new_series_code.strip():
                    conn = get_db()
                    try:
                        conn.execute("INSERT INTO series (name, unit_code, unit_name, series_code, retention_year, legal_basis, trigger_event) VALUES (?, ?, ?, ?, ?, ?, ?)", (new_series_name.strip(), new_series_unit.strip(), "", new_series_code.strip(), new_series_retention, new_series_basis.strip(), new_series_trigger.strip()))
                        conn.commit()
                        audit(active_user, "Seri Tanımı", f"{new_series_code} · {new_series_name}", object_id=new_series_code.strip())
                        st.success("Seri kaydedildi.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Bu seri kodu zaten kayıtlı.")
                    finally:
                        conn.close()

    with definition_tabs[2]:
        institution_search = st.text_input("Kurumlarda ara", placeholder="Kurum adı veya kodu...")
        institution_query = "SELECT id AS [ID], name AS [Kurum Adı], code AS [Kurum Kodu] FROM institutions WHERE 1=1"
        institution_params = []
        if institution_search.strip():
            institution_query += " AND (name LIKE ? OR code LIKE ?)"
            institution_params.extend([f"%{institution_search.strip()}%"] * 2)
        st.dataframe(read_df(institution_query + " ORDER BY id", institution_params), width="stretch", hide_index=True, height=400)
        with st.expander("Yeni kurum kaydı"):
            with st.form("new_institution"):
                new_institution_name = st.text_input("Kurum adı")
                new_institution_code = st.text_input("Kurum kodu")
                if st.form_submit_button("Kurumu kaydet", type="primary") and new_institution_name.strip() and new_institution_code.strip():
                    conn = get_db()
                    try:
                        conn.execute("INSERT INTO institutions (name, code) VALUES (?, ?)", (new_institution_name.strip(), new_institution_code.strip()))
                        conn.commit()
                        audit(active_user, "Kurum Tanımı", f"{new_institution_code} · {new_institution_name}", object_id=new_institution_code.strip())
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
        with st.expander("👤 Yeni Kullanıcı ve Yetki Tanımla"):
            with st.form("new_user_form"):
                u_name = st.text_input("Kullanıcı Adı / Sicil No")
                u_fullname = st.text_input("Ad Soyad")
                u_unit = st.text_input("Birim Kodu (Tümü için ALL)")
                u_role = st.selectbox("Rol Tanımı", ["Arşiv Sorumlusu", "Birim Kullanıcısı", "Yönetici"])
                u_auth = st.multiselect("Yetki Kodları", ["ADMIN", "TALEP_YONETIM", "IMHA", "DENETIM", "LEGAL_HOLD"], default=["TALEP_YONETIM"])
                if st.form_submit_button("Kullanıcıyı Kaydet", type="primary") and u_name.strip() and u_fullname.strip():
                    conn = get_db()
                    try:
                        conn.execute("INSERT INTO user_permissions (username, full_name, unit_code, auth_codes, role_desc, active) VALUES (?, ?, ?, ?, ?, 1)", (u_name.strip(), u_fullname.strip(), u_unit.strip(), ",".join(u_auth), u_role))
                        conn.commit()
                        audit(active_user, "Kullanıcı Tanımlama", f"{u_name} · {u_fullname}", object_id=u_name.strip())
                        st.success("Kullanıcı başarıyla kaydedildi.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Bu kullanıcı adı zaten mevcut.")
                    finally:
                        conn.close()

# =========================================================
# MENÜ: ERİŞİM TALEPLERİ
# =========================================================
elif menu == "Erişim Talepleri":
    header("Erişim talepleri", "Arşiv belgelerine yönelik erişim taleplerini takip et ve yönet.")
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
    q1.metric("Toplam talep", len(queue_df))
    q2.metric("Onay bekleyen", int((queue_df["Durum"] == "Onay Bekliyor").sum()) if not queue_df.empty and "Durum" in queue_df else 0)
    q3.metric("Acil işler", int(queue_df["Öncelik"].isin(["Acil", "Kritik"]).sum()) if not queue_df.empty and "Öncelik" in queue_df else 0)
    st.markdown("<br>", unsafe_allow_html=True)

    if queue_df.empty or "Talep" not in queue_df.columns:
        st.info("Görüntülenecek talep bulunmamaktadır.")
    else:
        st.dataframe(queue_df.drop(columns=["id"], errors="ignore"), width="stretch", hide_index=True, height=350)
        st.markdown("### Talep işlemleri")
        u1, u2, u3 = st.columns([2, 2, 1])
        with u1:
            selected_request = st.selectbox("Talep", queue_df["Talep"].tolist())
        with u2:
            new_status = st.selectbox("Yeni durum", ["Onay Bekliyor", "Hazırlanıyor", "Kuryede", "Teslim Edildi", "Tamamlandı / İade", "İptal / Red"])
        with u3:
            if can_manage:
                if st.button("Güncelle", type="primary", width="stretch"):
                    conn = get_db()
                    conn.execute("UPDATE archive_requests SET status = ? WHERE req_no = ?", (new_status, selected_request))
                    conn.commit()
                    conn.close()
                    audit(active_user, "Talep Durumu Güncelleme", f"{selected_request} → {new_status}", object_id=selected_request)
                    st.success("Talep durumu güncellendi.")
                    st.rerun()
            else:
                st.caption("Talep durumunu yalnızca yetkili kullanıcılar güncelleyebilir.")

        st.markdown("### Talep içi mesajlaşma")
        message_df = read_df("SELECT sender AS [Gönderen], message AS [Mesaj], created_at AS [Tarih] FROM request_messages WHERE req_no = ? ORDER BY id ASC", params=[selected_request])
        if not message_df.empty:
            st.dataframe(message_df, width="stretch", hide_index=True)

        with st.form("request_message_form"):
            message = st.text_input("Mesaj", placeholder="Konum, teslimat veya inceleme notu...")
            if st.form_submit_button("Mesajı kaydet") and message.strip():
                conn = get_db()
                now_stamp = suanki_zaman().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("INSERT INTO request_messages (req_no, sender, message, created_at) VALUES (?, ?, ?, ?)", (selected_request, active_name, message.strip(), now_stamp))
                conn.commit()
                conn.close()
                audit(active_user, "Talep Mesajı Ekleme", f"{selected_request} talebine mesaj eklendi", object_id=selected_request)
                st.success("Mesaj kaydedildi.")
                st.rerun()

# =========================================================
# MENÜ: SAKLAMA VE İMHA (KONTROLLÜ İŞ AKIŞI)
# =========================================================
elif menu == "Saklama ve imha" and can_manage_destruction(active_row):
    st.markdown("### Saklama ve İmha Yönetimi")
    tab1, tab2 = st.tabs(["Süresi Dolanlar (İmha Bekleyenler)", "İmha Edilen Belgeler Arşivi"])

    with tab1:
        st.markdown("#### İmha Edilecek Belgeler Listesi")
        scope_dest_sql = " AND unit_code = ?" if active_unit != "ALL" else ""
        scope_dest_params = (CURRENT_YEAR, active_unit) if active_unit != "ALL" else (CURRENT_YEAR,)
        
        pending_df = read_df(f"""
            SELECT doc_reg_no AS 'Kayıt No', doc_no AS 'Dosya No', doc_name AS 'Belge Adı', 
                   unit_code AS 'Birim', retention_end_year AS 'İmha Yılı', 
                   destruction_status AS 'Durum', legal_hold AS 'Hukuki Engel',
                   destruction_requested_by AS 'İmha Talep Eden'
            FROM aygaz_main_archive 
            WHERE (destruction_status IS NULL OR destruction_status != 'İMHA EDİLDİ') 
              AND CAST(retention_end_year AS INTEGER) <= ? {scope_dest_sql}
        """, scope_dest_params)

        if not pending_df.empty and "Kayıt No" in pending_df.columns:
            st.dataframe(pending_df, width="stretch", hide_index=True)
            st.markdown("---")
            st.markdown("**Kontrollü İmha İş Akışı (Onay Zinciri)**")
            
            col_sel, col_act1, col_act2 = st.columns([2, 1, 1])
            with col_sel:
                selected_record_no = st.selectbox("İşlem yapılacak belgeyi seçin:", pending_df["Kayıt No"].tolist())
                selected_item = pending_df[pending_df["Kayıt No"] == selected_record_no].iloc[0]
            
            cur_status = selected_item["Durum"]
            is_held = selected_item["Hukuki Engel"] == 1
            requester = selected_item.get("İmha Talep Eden", "")

            with col_act1:
                st.write("")
                st.write("")
                if cur_status == "BEKLİYOR":
                    if st.button("İmha Talebi Oluştur", type="primary", use_container_width=True):
                        conn = get_db()
                        conn.execute("UPDATE aygaz_main_archive SET destruction_status = 'ONAY BEKLİYOR', destruction_requested_by = ? WHERE doc_reg_no = ?", (active_user, str(selected_record_no)))
                        conn.commit()
                        conn.close()
                        audit(active_user, "İmha Talebi Açma", f"Kayıt No {selected_record_no} için imha talebi açıldı.", object_id=str(selected_record_no))
                        st.success("İmha talebi oluşturuldu, onay bekleniyor.")
                        st.rerun()

            with col_act2:
                st.write("")
                st.write("")
                if cur_status == "ONAY BEKLİYOR":
                    if st.button("İmha İşlemini Onayla", type="primary", use_container_width=True):
                        if is_held:
                            st.error("Bu kayıt üzerinde aktif bir HUKUKİ ENGEL bulunmaktadır. Kaldırılmadan imha edilemez!")
                        elif requester == active_user and not is_admin_user(active_row):
                            st.error("Görevler ayrılığı kuralı: Kendi talep ettiğiniz imha işlemini kendiniz onaylayamazsınız.")
                        else:
                            today_str = suanki_zaman().strftime("%d.%m.%Y")
                            conn = get_db()
                            conn.execute("""
                                UPDATE aygaz_main_archive 
                                SET destruction_status = 'İMHA EDİLDİ', destruction_date = ? 
                                WHERE doc_reg_no = ?
                            """, (today_str, str(selected_record_no)))
                            conn.commit()
                            conn.close()
                            audit(active_user, "Belge İmhası Onaylama", f"Kayıt No {selected_record_no} resmi olarak imha edildi.", object_id=str(selected_record_no))
                            st.success(f"Kayıt No {selected_record_no} başarıyla imha edildi olarak işlendi.")
                            st.rerun()
        else:
            st.info("İmha süresi dolmuş bekleyen belge bulunmamaktadır.")

    with tab2:
        st.markdown(f"#### {CURRENT_YEAR} Yılı İmha Tutanağı ve Arşivi")
        destroyed_query = """
            SELECT doc_reg_no AS 'Kayıt No', doc_no AS 'Dosya No', doc_name AS 'Belge Adı', 
                   unit_code AS 'Birim', retention_end_year AS 'İmha Yılı', 
                   destruction_date AS 'İmha Tarihi', destruction_status AS 'Durum' 
            FROM aygaz_main_archive 
            WHERE destruction_status = 'İMHA EDİLDİ'
        """
        dest_params = []
        if active_unit != "ALL":
            destroyed_query += " AND unit_code = ?"
            dest_params.append(active_unit)
        destroyed_query += f" AND (destruction_date LIKE '%{CURRENT_YEAR}%' OR retention_end_year = '{CURRENT_YEAR}')"

        destroyed_df = read_df(destroyed_query, dest_params)
        if not destroyed_df.empty:
            st.dataframe(destroyed_df, width="stretch", hide_index=True)
            download_excel(
                f"{CURRENT_YEAR} İmha Edilen Belgeler Listesini İndir (Excel)",
                destroyed_df,
                f"Aygaz_Imha_Edilen_Belgeler_{CURRENT_YEAR}.xlsx",
                sheet_name="Imha_Listesi",
                user=active_user
            )
        else:
            st.info(f"{CURRENT_YEAR} yılı için yetki kapsamınızda imha edilmiş bir belge kaydı bulunmuyor.")

# =========================================================
# MENÜ: GÜNLÜKLER (YÖNETİM RAPORLARI)
# =========================================================
elif menu == "Günlükler" and is_admin:
    header("Yönetim raporları", "Arşiv hacmini, iş yükünü ve saklama riskini tek bakışta değerlendir.")
    
    rep_unit_sql = " WHERE unit_code = ?" if active_unit != "ALL" else ""
    rep_unit_params = (CURRENT_YEAR, active_unit) if active_unit != "ALL" else (CURRENT_YEAR,)
    
    unit_report = read_df(f"""
        SELECT unit_code AS [Birim], COUNT(*) AS [Kayıt], 
               SUM(CASE WHEN status = 'Zimmette' THEN 1 ELSE 0 END) AS [Zimmette], 
               SUM(CASE WHEN retention_end_year <= ? AND (destruction_status IS NULL OR destruction_status != 'İMHA EDİLDİ') THEN 1 ELSE 0 END) AS [Süre riski] 
        FROM aygaz_main_archive {rep_unit_sql} GROUP BY unit_code ORDER BY [Kayıt] DESC
    """, rep_unit_params)
    
    rep_status_sql = " WHERE unit_code = ?" if active_unit != "ALL" else ""
    rep_status_params = (active_unit,) if active_unit != "ALL" else ()
    status_report = read_df(f"SELECT status AS [Durum], COUNT(*) AS [Kayıt] FROM aygaz_main_archive {rep_status_sql} GROUP BY status ORDER BY [Kayıt] DESC", rep_status_params)
    
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
        daily_scope_sql = " AND unit_code = ?" if active_unit != "ALL" else ""
        daily_scope_params = (active_unit,) if active_unit != "ALL" else ()
        daily_report = read_df(f"""
            SELECT substr(first_doc_date, 7, 4) || '-' || substr(first_doc_date, 4, 2) || '-' || substr(first_doc_date, 1, 2) AS [Kayıt Tarihi], 
                   unit_code AS [Birim], COUNT(*) AS [Kayıt Sayısı] 
            FROM aygaz_main_archive WHERE first_doc_date IS NOT NULL {daily_scope_sql}
            GROUP BY [Kayıt Tarihi], unit_code ORDER BY [Kayıt Tarihi] DESC
        """, daily_scope_params)
        st.dataframe(daily_report, width="stretch", hide_index=True, height=220)
        download_excel("Günlük Excel indir", daily_report, "aygaz-gunluk-kayitlar.xlsx", "Günlük Kayıtlar", user=active_user)
        
    with report_tabs[1]:
        monthly_scope_sql = " AND unit_code = ?" if active_unit != "ALL" else ""
        monthly_scope_params = (active_unit,) if active_unit != "ALL" else ()
        monthly_report = read_df(f"""
            SELECT substr(first_doc_date, 7, 4) || '-' || substr(first_doc_date, 4, 2) AS [Ay], 
                   unit_code AS [Birim], COUNT(*) AS [Kayıt Sayısı] 
            FROM aygaz_main_archive WHERE first_doc_date IS NOT NULL {monthly_scope_sql}
            GROUP BY [Ay], unit_code ORDER BY [Ay] DESC
        """, monthly_scope_params)
        st.dataframe(monthly_report, width="stretch", hide_index=True, height=220)
        download_excel("Aylık Excel indir", monthly_report, "aygaz-aylik-kayitlar.xlsx", "Aylık Kayıtlar", user=active_user)
        
    download_excel("Yönetim raporunu indir", unit_report, "aygaz-arsiv-yonetim-raporu.xlsx", "Birim Raporu", {"Durum Raporu": status_report}, user=active_user)

# =========================================================
# MENÜ: DENETİM İZİ (AUDIT TRAIL)
# =========================================================
elif menu == "Denetim izi" and can_view_audit(active_row):
    header("Denetim izi", "Arşivde kim, ne zaman, hangi kararı verdi?")
    audit_df = read_df("""
        SELECT timestamp AS [Zaman], user AS [Kullanıcı], action_type AS [İşlem], 
               object_id AS [Kayıt No], details AS [Detay], result AS [Sonuç], 
               event_hash AS [SHA-256 İmzası] 
        FROM archive_audit ORDER BY id DESC LIMIT 250
    """)
    st.markdown('<div class="hint">Bu akış kullanıcı ve veri işlemlerini kriptografik hash zinciriyle tutar. Kayıtlar geriye dönük değiştirilemez.</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    st.dataframe(audit_df, width="stretch", hide_index=True, height=520)
    download_excel("Denetim İzi Excel İndir", audit_df, "aygaz-arsiv-denetim-izi.xlsx", "Denetim İzi", user=active_user)
