from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

APP_NAME = "Aygaz Arşiv Sistemi"
APP_VERSION = "2.1.0-enterprise-demo"
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("AIBS_DB_PATH", str(BASE_DIR / "aibs_database.db")))
DOCUMENT_ROOT = Path(os.getenv("AIBS_DOCUMENT_ROOT", str(BASE_DIR / "secure_documents")))
DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)
ENVIRONMENT = os.getenv("AIBS_ENV", "DEMO").upper()
SSO_HEADER = os.getenv("AIBS_SSO_HEADER", "X-Authenticated-User")
SSO_NAME_HEADER = os.getenv("AIBS_SSO_NAME_HEADER", "X-Authenticated-Name")
SIEM_WEBHOOK = os.getenv("AIBS_SIEM_WEBHOOK_URL", "").strip()
MAX_UPLOAD_MB = int(os.getenv("AIBS_MAX_UPLOAD_MB", "25"))
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "jpg", "jpeg", "png", "tif", "tiff"}
ALLOWED_MIME = {
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv", "text/plain", "image/jpeg", "image/png", "image/tiff",
}
TR_TZ = timezone(timedelta(hours=3))
TR_MONTHS = {1:"Oca",2:"Şub",3:"Mar",4:"Nis",5:"May",6:"Haz",7:"Tem",8:"Ağu",9:"Eyl",10:"Eki",11:"Kas",12:"Ara"}
PERMISSIONS = {
    "ARCHIVE_READ","ARCHIVE_CREATE","ARCHIVE_EDIT","REQUEST_CREATE","REQUEST_VIEW","REQUEST_MANAGE",
    "DESTRUCTION_REQUEST","DESTRUCTION_REVIEW","DESTRUCTION_APPROVE","DESTRUCTION_EXECUTE",
    "LEGAL_HOLD","AUDIT_VIEW","USER_ADMIN","EXPORT","SECURITY_VIEW"
}


def now_tr() -> datetime:
    return datetime.now(TR_TZ)


def iso_now() -> str:
    return now_tr().isoformat(timespec="seconds")


def fmt_dt(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(TR_TZ)
        return f"{dt.day:02d} {TR_MONTHS[dt.month]} {dt.year} · {dt:%H:%M}"
    except Exception:
        return str(value)


def clean(value: Any, max_len: int = 500) -> str:
    return str(value if value is not None else "").strip()[:max_len]


def normalize_codes(value: Any) -> set[str]:
    return {x.strip().upper() for x in str(value or "").split(",") if x.strip()}


def safe_filename(name: str) -> str:
    name = Path(str(name)).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name[:180] or "belge"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def ensure_column(conn: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    if name not in table_columns(conn, table):
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')


def init_database() -> None:
    conn = get_db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS institutions(id INTEGER PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS units(id INTEGER PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE, inst_code TEXT, inst_name TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS series(id INTEGER PRIMARY KEY, name TEXT NOT NULL, unit_code TEXT, unit_name TEXT, series_code TEXT NOT NULL UNIQUE, retention_year INTEGER, legal_basis TEXT, trigger_event TEXT DEFAULT 'Dosyanın kapanışı', disposition TEXT DEFAULT 'İMHA', confidentiality TEXT DEFAULT 'INTERNAL', active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS roles(role_code TEXT PRIMARY KEY, role_name TEXT NOT NULL, permissions TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL, unit_code TEXT NOT NULL DEFAULT 'ALL', role_code TEXT NOT NULL DEFAULT 'ARCHIVE_USER', active INTEGER DEFAULT 1, external_id TEXT, last_login_at TEXT);
        CREATE TABLE IF NOT EXISTS aygaz_main_archive(
            id INTEGER PRIMARY KEY AUTOINCREMENT, doc_reg_no TEXT NOT NULL UNIQUE, doc_no TEXT, doc_name TEXT NOT NULL,
            series_code TEXT, unit_code TEXT, first_doc_date TEXT, last_doc_date TEXT, box_no TEXT, shelf_no TEXT,
            institution TEXT, status TEXT DEFAULT 'Depoda', destruction_status TEXT DEFAULT 'BEKLİYOR', destruction_date TEXT,
            retention_end_year INTEGER, classification TEXT DEFAULT 'INTERNAL', personal_data INTEGER DEFAULT 0,
            special_category_data INTEGER DEFAULT 0, retention_trigger TEXT, legal_basis TEXT, owner_unit TEXT,
            current_holder TEXT, physical_location TEXT, metadata_complete INTEGER DEFAULT 0, legal_hold_count INTEGER DEFAULT 0,
            created_at TEXT, updated_at TEXT, created_by TEXT, updated_by TEXT
        );
        CREATE TABLE IF NOT EXISTS archive_files(
            id INTEGER PRIMARY KEY AUTOINCREMENT, archive_id INTEGER NOT NULL, original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL UNIQUE, mime_type TEXT, size_bytes INTEGER, sha256 TEXT NOT NULL,
            uploaded_at TEXT NOT NULL, uploaded_by TEXT NOT NULL, version_no INTEGER DEFAULT 1,
            ocr_status TEXT DEFAULT 'BEKLEMEDE', ocr_text TEXT, signature_status TEXT DEFAULT 'YOK',
            integrity_status TEXT DEFAULT 'DOĞRULANMADI', FOREIGN KEY(archive_id) REFERENCES aygaz_main_archive(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS archive_access(
            id INTEGER PRIMARY KEY AUTOINCREMENT, archive_id INTEGER NOT NULL, username TEXT NOT NULL, action TEXT NOT NULL,
            result TEXT NOT NULL, reason TEXT, timestamp TEXT NOT NULL, correlation_id TEXT NOT NULL, ip_address TEXT, user_agent TEXT,
            FOREIGN KEY(archive_id) REFERENCES aygaz_main_archive(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS archive_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT, req_no TEXT NOT NULL UNIQUE, requester TEXT NOT NULL, unit_code TEXT NOT NULL,
            doc_item TEXT NOT NULL, delivery_type TEXT NOT NULL, urgency TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'AÇIK',
            notes TEXT, created_at TEXT NOT NULL, due_at TEXT, closed_at TEXT, approved_by TEXT, delivered_at TEXT, returned_at TEXT
        );
        CREATE TABLE IF NOT EXISTS request_messages(id INTEGER PRIMARY KEY AUTOINCREMENT, req_no TEXT NOT NULL, sender TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS custody_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, archive_id INTEGER NOT NULL, request_id INTEGER, event_type TEXT NOT NULL,
            from_status TEXT, to_status TEXT, actor TEXT NOT NULL, timestamp TEXT NOT NULL, due_at TEXT, note TEXT,
            FOREIGN KEY(archive_id) REFERENCES aygaz_main_archive(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS legal_holds(
            id INTEGER PRIMARY KEY AUTOINCREMENT, archive_id INTEGER NOT NULL, hold_ref TEXT NOT NULL UNIQUE, reason TEXT NOT NULL,
            authority TEXT, start_date TEXT NOT NULL, end_date TEXT, active INTEGER DEFAULT 1, created_by TEXT NOT NULL,
            created_at TEXT NOT NULL, released_by TEXT, released_at TEXT,
            FOREIGN KEY(archive_id) REFERENCES aygaz_main_archive(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS destruction_workflows(
            id INTEGER PRIMARY KEY AUTOINCREMENT, archive_id INTEGER NOT NULL, stage TEXT NOT NULL, requested_by TEXT NOT NULL,
            requested_at TEXT NOT NULL, reviewed_by TEXT, reviewed_at TEXT, approved_by TEXT, approved_at TEXT,
            executed_by TEXT, executed_at TEXT, certificate_no TEXT, method TEXT, notes TEXT,
            FOREIGN KEY(archive_id) REFERENCES aygaz_main_archive(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS retention_schedule(
            id INTEGER PRIMARY KEY AUTOINCREMENT, series_code TEXT NOT NULL UNIQUE, document_type TEXT NOT NULL,
            retention_years INTEGER, trigger_event TEXT NOT NULL, legal_basis TEXT, disposition TEXT NOT NULL DEFAULT 'İMHA',
            confidentiality TEXT NOT NULL DEFAULT 'INTERNAL', kvkk_category TEXT, active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, timestamp TEXT NOT NULL, username TEXT NOT NULL,
            action_type TEXT NOT NULL, object_type TEXT, object_id TEXT, result TEXT NOT NULL, reason TEXT, old_value TEXT,
            new_value TEXT, ip_address TEXT, user_agent TEXT, correlation_id TEXT NOT NULL, previous_hash TEXT, event_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS security_events(id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, username TEXT, event_type TEXT NOT NULL, severity TEXT NOT NULL, details TEXT, resolved INTEGER DEFAULT 0);
        """)

        # Safe migration for older demo databases.
        # IMPORTANT: CREATE TABLE IF NOT EXISTS does NOT modify an existing
        # table. Therefore every column added in newer versions must also be
        # migrated explicitly before any INSERT/SELECT uses it.
        for name, definition in [
            ("trigger_event", "TEXT DEFAULT 'Dosyanın kapanışı'"),
            ("disposition", "TEXT DEFAULT 'İMHA'"),
            ("confidentiality", "TEXT DEFAULT 'INTERNAL'"),
            ("active", "INTEGER DEFAULT 1"),
        ]:
            ensure_column(conn, "series", name, definition)

        for name, definition in [
            ("kvkk_category", "TEXT"),
            ("active", "INTEGER DEFAULT 1"),
        ]:
            ensure_column(conn, "retention_schedule", name, definition)

        for name, definition in [
            ("classification", "TEXT DEFAULT 'INTERNAL'"), ("personal_data", "INTEGER DEFAULT 0"),
            ("special_category_data", "INTEGER DEFAULT 0"), ("retention_trigger", "TEXT"), ("legal_basis", "TEXT"),
            ("owner_unit", "TEXT"), ("current_holder", "TEXT"), ("physical_location", "TEXT"),
            ("metadata_complete", "INTEGER DEFAULT 0"), ("legal_hold_count", "INTEGER DEFAULT 0"),
            ("created_at", "TEXT"), ("updated_at", "TEXT"), ("created_by", "TEXT"), ("updated_by", "TEXT")]:
            ensure_column(conn, "aygaz_main_archive", name, definition)

        # Older demo databases used a simpler users table.  CREATE TABLE IF
        # NOT EXISTS does not alter an existing table, so migrate every field
        # used by the current RBAC query before any user is read.
        for name, definition in [
            ("full_name", "TEXT NOT NULL DEFAULT ''"),
            ("unit_code", "TEXT NOT NULL DEFAULT 'ALL'"),
            ("role_code", "TEXT NOT NULL DEFAULT 'ARCHIVE_USER'"),
            ("active", "INTEGER DEFAULT 1"),
            ("external_id", "TEXT"),
            ("last_login_at", "TEXT"),
        ]:
            ensure_column(conn, "users", name, definition)

        # Older databases may also contain a roles table with fewer fields.
        for name, definition in [
            ("role_name", "TEXT NOT NULL DEFAULT 'Birim Kullanıcısı'"),
            ("permissions", "TEXT NOT NULL DEFAULT 'ARCHIVE_READ,REQUEST_CREATE,REQUEST_VIEW'"),
        ]:
            ensure_column(conn, "roles", name, definition)

        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_archive_unit_series ON aygaz_main_archive(unit_code,series_code)",
            "CREATE INDEX IF NOT EXISTS idx_archive_retention ON aygaz_main_archive(retention_end_year,destruction_status)",
            "CREATE INDEX IF NOT EXISTS idx_archive_classification ON aygaz_main_archive(classification)",
            "CREATE INDEX IF NOT EXISTS idx_requests_status ON archive_requests(status,unit_code)",
            "CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_access_time ON archive_access(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_holds_archive ON legal_holds(archive_id,active)",
        ]:
            conn.execute(sql)

        conn.executemany("INSERT OR IGNORE INTO institutions(id,name,code) VALUES(?,?,?)", [
            (1,"AYGAZ A.Ş.","10"),(11,"ZİNERJİ A.Ş.","40"),(12,"ANADOLU HİSARI TANKERCİLİK","30"),
            (13,"AYGAZ DOĞALGAZ","20"),(15,"AKPA A.Ş.","50"),(17,"GAZAL A.Ş.","60")])
        conn.executemany("INSERT OR IGNORE INTO units(id,name,code,inst_code,inst_name) VALUES(?,?,?,?,?)", [
            (1,"TANIMSIZ","0","10","AYGAZ A.Ş."),(2,"BİLGİ SİSTEM MÜDÜRLÜĞÜ","1001","10","AYGAZ A.Ş."),
            (3,"BÜTÇE PLANLAMA VE KONTROL MÜDÜRLÜĞÜ","1002","10","AYGAZ A.Ş."),(4,"FİNANSMAN MÜDÜRLÜĞÜ","1003","10","AYGAZ A.Ş."),
            (5,"MUHASEBE MÜDÜRLÜĞÜ","1004","10","AYGAZ A.Ş."),(6,"BAYİ GELİŞTİRME MÜDÜRLÜĞÜ","1005","10","AYGAZ A.Ş."),
            (7,"İNSAN KAYNAKLARI MÜDÜRLÜĞÜ","1006","10","AYGAZ A.Ş."),(8,"GEMİ İŞLETME MÜDÜRLÜĞÜ","1007","10","AYGAZ A.Ş."),
            (9,"İŞLETME MÜHENDİSLİK YATIRIMLAR MÜDÜRLÜĞÜ","1008","10","AYGAZ A.Ş.")])
        series = [
            (1,"PERSONEL ÖZLÜK DOSYALARI","1006","İNSAN KAYNAKLARI MÜDÜRLÜĞÜ","1",10,"İş Kanunu Md. 75","İş ilişkisinin sona ermesi / kurum politikasıyla doğrulanacak süre","İMHA","RESTRICTED"),
            (3,"MAKBUZ VE TAHSİLAT BELGELERİ","1004","MUHASEBE MÜDÜRLÜĞÜ","3",10,"VUK Md. 253","Belgenin düzenlenmesi / yasal sürenin başlangıcı doğrulanmalı","İMHA","CONFIDENTIAL"),
            (4,"MAHSUP VE YEVMİYE FİŞLERİ","1004","MUHASEBE MÜDÜRLÜĞÜ","4",10,"TTK Md. 82","İlgili hesap döneminin kapanışı","İMHA","CONFIDENTIAL"),
            (9,"TİCARİ BAYİLİK VE MÜLKİYET SÖZLEŞMELERİ","1004","MUHASEBE MÜDÜRLÜĞÜ","9",100,"Kurum hukuk politikasıyla doğrulanmalı","Sözleşmenin sona ermesi / uyuşmazlık yokluğu","İMHA","CONFIDENTIAL"),
            (11,"İŞ SAĞLIĞI VE AMBARLI TEFTİŞ RAPORLARI","1008","İŞLETME MÜHENDİSLİK YATIRIMLAR MÜDÜRLÜĞÜ","11",15,"6331 sayılı mevzuatla birlikte Aygaz Hukuk/İSG politikası doğrulanmalı","Raporun kapanışı","İMHA","CONFIDENTIAL")]
        conn.executemany("INSERT OR IGNORE INTO series(id,name,unit_code,unit_name,series_code,retention_year,legal_basis,trigger_event,disposition,confidentiality) VALUES(?,?,?,?,?,?,?,?,?,?)", series)
        roles = [
            ("ARCHIVE_ADMIN","Arşiv Yöneticisi",",".join(sorted(PERMISSIONS))),
            ("ARCHIVE_OFFICER","Arşiv Görevlisi","ARCHIVE_READ,ARCHIVE_CREATE,ARCHIVE_EDIT,REQUEST_MANAGE,DESTRUCTION_REQUEST,LEGAL_HOLD,EXPORT"),
            ("ARCHIVE_AUDITOR","Denetim","ARCHIVE_READ,AUDIT_VIEW,EXPORT"),
            ("ARCHIVE_USER","Birim Kullanıcısı","ARCHIVE_READ,REQUEST_CREATE,REQUEST_VIEW"),
            ("DESTRUCTION_REVIEWER","İmha İnceleme","ARCHIVE_READ,DESTRUCTION_REQUEST,DESTRUCTION_REVIEW,LEGAL_HOLD,AUDIT_VIEW"),
            ("DESTRUCTION_EXECUTOR","İmha Uygulama","ARCHIVE_READ,DESTRUCTION_EXECUTE,AUDIT_VIEW")]
        conn.executemany("INSERT OR IGNORE INTO roles(role_code,role_name,permissions) VALUES(?,?,?)", roles)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            conn.execute("INSERT INTO users(username,full_name,unit_code,role_code,active) VALUES(?,?,?,?,1)", ("local\\admin","Arşiv Yöneticisi","ALL","ARCHIVE_ADMIN"))

        if conn.execute("SELECT COUNT(*) FROM retention_schedule").fetchone()[0] == 0:
            for s in series:
                conn.execute("INSERT OR IGNORE INTO retention_schedule(series_code,document_type,retention_years,trigger_event,legal_basis,disposition,confidentiality,kvkk_category) VALUES(?,?,?,?,?,?,?,?)",
                             (s[4],s[1],s[5],s[7],s[6],s[8],s[9],"Özlük" if s[4]=="1" else None))

        if conn.execute("SELECT COUNT(*) FROM aygaz_main_archive").fetchone()[0] == 0:
            seeds = [
                ("90101","1411-23-201","Bayi faaliyet raporları","6","1004","01/08/2023","31/08/2023","23050","H11.211","AYGAZ","Depoda","BEKLİYOR",None,2028,"INTERNAL",0,0,"Dosyanın kapanışı","Kurum politikasıyla doğrulanmalı","1004","","H11 / 211",0,0),
                ("90102","1411-23-202","Ticari bayilik sözleşmeleri","9","1004","01/08/2023","31/08/2023","23051","H11.212","AYGAZ","Zimmette","BEKLİYOR",None,2123,"CONFIDENTIAL",0,0,"Sözleşmenin sona ermesi","Kurum hukuk politikasıyla doğrulanmalı","1004","Kullanıcı","H11 / 212",0,0),
                ("90085","1205-22-085","İSG saha denetim raporları","11","1008","01/05/2022","31/05/2022","22085","G03.014","AYGAZ","Depoda","BEKLİYOR",None,2037,"CONFIDENTIAL",0,0,"Raporun kapanışı","6331 sayılı mevzuatla birlikte Aygaz Hukuk/İSG politikası doğrulanmalı","1008","","G03 / 014",0,0)]
            for s in seeds:
                conn.execute("""INSERT INTO aygaz_main_archive(doc_reg_no,doc_no,doc_name,series_code,unit_code,first_doc_date,last_doc_date,box_no,shelf_no,institution,status,destruction_status,destruction_date,retention_end_year,classification,personal_data,special_category_data,retention_trigger,legal_basis,owner_unit,current_holder,physical_location,metadata_complete,legal_hold_count,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (*s,iso_now(),iso_now(),"local\\admin","local\\admin"))
        conn.commit()
    finally:
        conn.close()


def query(sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    conn = get_db()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def execute(sql: str, params: tuple[Any, ...] = ()) -> int:
    conn = get_db()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def last_audit_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT event_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    return row[0] if row else "GENESIS"


def audit(action: str, username: str, result: str = "SUCCESS", object_type: str = "", object_id: str = "", reason: str = "", old_value: Any = None, new_value: Any = None, correlation_id: str | None = None) -> None:
    conn = get_db()
    try:
        ts = iso_now(); event_id = str(uuid.uuid4()); corr = correlation_id or str(uuid.uuid4()); previous = last_audit_hash(conn)
        payload = json.dumps({"event_id":event_id,"timestamp":ts,"username":username,"action":action,"object_type":object_type,"object_id":object_id,"result":result,"reason":reason,"old":old_value,"new":new_value,"previous_hash":previous}, ensure_ascii=False, sort_keys=True, default=str)
        event_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        conn.execute("INSERT INTO audit_log(event_id,timestamp,username,action_type,object_type,object_id,result,reason,old_value,new_value,ip_address,user_agent,correlation_id,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (event_id,ts,username,action,object_type,object_id,result,reason,json.dumps(old_value,ensure_ascii=False,default=str) if old_value is not None else None,json.dumps(new_value,ensure_ascii=False,default=str) if new_value is not None else None,"","",corr,previous,event_hash))
        conn.commit()
    finally:
        conn.close()


def security_event(event_type: str, severity: str, username: str = "", details: str = "") -> None:
    execute("INSERT INTO security_events(timestamp,username,event_type,severity,details) VALUES(?,?,?,?,?)", (iso_now(),username,event_type,severity,details[:1000]))


def get_users() -> list[sqlite3.Row]:
    return query("SELECT u.*,r.role_name,r.permissions FROM users u LEFT JOIN roles r ON r.role_code=u.role_code WHERE u.active=1 ORDER BY u.full_name")


def get_current_user() -> dict[str, Any]:
    users = get_users()
    if ENVIRONMENT == "PROD":
        header_user = clean(st.context.headers.get(SSO_HEADER, ""), 120)
        if not header_user:
            return {"username":"","full_name":"Kimlik doğrulanmadı","unit_code":"","role_code":"","permissions":set(),"authenticated":False}
        row = next((r for r in users if r["username"].lower() == header_user.lower()), None)
        if not row:
            security_event("UNKNOWN_SSO_USER","HIGH",header_user,"SSO kullanıcısı sistemde yetkili değil")
            return {"username":header_user,"full_name":"Yetkisiz kullanıcı","unit_code":"","role_code":"","permissions":set(),"authenticated":False}
        name = clean(st.context.headers.get(SSO_NAME_HEADER, ""), 200) or row["full_name"]
        return {"username":row["username"],"full_name":name,"unit_code":row["unit_code"],"role_code":row["role_code"],"permissions":normalize_codes(row["permissions"]),"authenticated":True}
    selected = st.session_state.get("demo_user", "local\\admin")
    row = next((r for r in users if r["username"] == selected), users[0] if users else None)
    if not row:
        return {"username":"","full_name":"Kullanıcı yok","unit_code":"","role_code":"","permissions":set(),"authenticated":False}
    return {"username":row["username"],"full_name":row["full_name"],"unit_code":row["unit_code"],"role_code":row["role_code"],"permissions":normalize_codes(row["permissions"]),"authenticated":True}


def has_perm(user: dict[str, Any], perm: str) -> bool:
    return perm in user.get("permissions", set())


def can_access_archive(user: dict[str, Any], row: sqlite3.Row | dict[str, Any]) -> bool:
    if not has_perm(user, "ARCHIVE_READ"):
        return False
    unit = str(row["unit_code"] or "")
    if user.get("unit_code") in ("ALL", "*") or user.get("role_code") == "ARCHIVE_ADMIN":
        return True
    return unit == user.get("unit_code")


def calculate_retention_end(last_date: str, years: int | None) -> int | None:
    if not last_date or years is None:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(last_date, fmt).year + int(years)
        except ValueError:
            pass
    return None


def archive_rows(user: dict[str, Any], search: str = "", unit: str = "Tümü", classification: str = "Tümü", status: str = "Tümü") -> list[sqlite3.Row]:
    sql = "SELECT * FROM aygaz_main_archive WHERE 1=1"; params: list[Any] = []
    if user.get("unit_code") not in ("ALL", "*"):
        sql += " AND unit_code=?"; params.append(user["unit_code"])
    if search:
        term = f"%{search}%"; sql += " AND (doc_reg_no LIKE ? OR doc_no LIKE ? OR doc_name LIKE ? OR box_no LIKE ? OR shelf_no LIKE ?)"; params += [term]*5
    if unit != "Tümü": sql += " AND unit_code=?"; params.append(unit)
    if classification != "Tümü": sql += " AND classification=?"; params.append(classification)
    if status != "Tümü": sql += " AND status=?"; params.append(status)
    sql += " ORDER BY id DESC"
    return query(sql, tuple(params))


def inject_css() -> None:
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');
    :root { --aygaz:#0072bc; --aygaz-dark:#005b94; }
    html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
    [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] { display:none !important; }
    header { visibility:hidden; height:0 !important; }
    [data-testid="stSidebar"] { background:#0072bc; }
    [data-testid="stSidebar"] * { color:white !important; }
    [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] { background:white; }
    [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] * { color:#222 !important; }
    .brand { font-size:1.35rem; font-weight:700; padding:0.2rem 0 1rem; }
    .subbrand { opacity:.8; font-size:.78rem; margin-top:-12px; margin-bottom:1rem; }
    .kpi { border:1px solid #e4e8ed; border-radius:12px; padding:16px; background:white; box-shadow:0 1px 3px rgba(0,0,0,.04); }
    .kpi-label { font-size:.78rem; color:#64748b; }
    .kpi-value { font-size:1.65rem; font-weight:700; color:#005696; margin-top:4px; }
    .section { font-weight:700; font-size:1.08rem; color:#005696; margin:1rem 0 .5rem; }
    .mono { font-family:'Space Mono',monospace; }
    .warning-box { padding:12px 14px; border-left:4px solid #d97706; background:#fff7ed; border-radius:6px; }
    </style>
    """, unsafe_allow_html=True)


def init_session() -> None:
    st.session_state.setdefault("demo_user", "local\\admin")
    st.session_state.setdefault("selected_archive_id", None)


def sidebar(user: dict[str, Any]) -> str:
    with st.sidebar:
        st.markdown(f'<div class="brand">{APP_NAME}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="subbrand">{APP_VERSION} · {ENVIRONMENT}</div>', unsafe_allow_html=True)
        if ENVIRONMENT != "PROD":
            users = get_users()
            labels = {f'{r["full_name"]} · {r["role_name"]}':r["username"] for r in users}
            current_label = next((k for k,v in labels.items() if v == st.session_state.demo_user), next(iter(labels), ""))
            chosen = st.selectbox("Kullanıcı", list(labels), index=list(labels).index(current_label) if current_label in labels else 0, key="demo_user_select") if labels else ""
            if chosen and labels.get(chosen) != st.session_state.demo_user:
                st.session_state.demo_user = labels[chosen]; st.rerun()
            st.caption("Demo kimlik seçimi. Üretimde kurumsal SSO kullanılmalıdır.")
        else:
            st.markdown(f"**{user.get('full_name','-')}**")
            st.caption(user.get("role_code", "-"))
        st.divider()
        pages = ["Genel Bakış","Arşiv Kataloğu","Erişim Talepleri"]
        if has_perm(user,"ARCHIVE_CREATE") or has_perm(user,"ARCHIVE_EDIT"): pages.append("Kayıt Yönetimi")
        if has_perm(user,"DESTRUCTION_REQUEST") or has_perm(user,"DESTRUCTION_REVIEW") or has_perm(user,"DESTRUCTION_EXECUTE"): pages.append("Saklama ve İmha")
        if has_perm(user,"LEGAL_HOLD"): pages.append("Legal Hold")
        if has_perm(user,"AUDIT_VIEW"): pages.append("Denetim ve Güvenlik")
        if has_perm(user,"USER_ADMIN"): pages.append("Kullanıcı Yönetimi")
        return st.radio("Menü", pages, label_visibility="collapsed")


def dashboard(user: dict[str, Any]) -> None:
    total = query("SELECT COUNT(*) c FROM aygaz_main_archive")[0]["c"]
    active = query("SELECT COUNT(*) c FROM aygaz_main_archive WHERE destruction_status='BEKLİYOR'")[0]["c"]
    holds = query("SELECT COUNT(*) c FROM legal_holds WHERE active=1")[0]["c"]
    requests = query("SELECT COUNT(*) c FROM archive_requests WHERE status NOT IN ('KAPANDI','İPTAL')")[0]["c"]
    cols = st.columns(4)
    for col, label, value in zip(cols,["Toplam kayıt","Aktif arşiv kaydı","Aktif legal hold","Açık talep"],[total,active,holds,requests]):
        with col: st.markdown(f'<div class="kpi"><div class="kpi-label">{label}</div><div class="kpi-value">{value:,}</div></div>',unsafe_allow_html=True)
    st.markdown('<div class="section">Saklama durumu</div>',unsafe_allow_html=True)
    current = datetime.now(TR_TZ).year
    due = query("SELECT COUNT(*) c FROM aygaz_main_archive WHERE retention_end_year IS NOT NULL AND retention_end_year<=? AND destruction_status='BEKLİYOR'",(current,))[0]["c"]
    future = query("SELECT COUNT(*) c FROM aygaz_main_archive WHERE retention_end_year>?",(current,))[0]["c"]
    a,b = st.columns(2)
    with a: st.metric("Saklama süresi dolan / yılı gelen",due)
    with b: st.metric("Saklama süresi devam eden",future)
    st.markdown('<div class="section">Son hareketler</div>',unsafe_allow_html=True)
    logs = query("SELECT timestamp,username,action_type,result,object_id FROM audit_log ORDER BY id DESC LIMIT 10")
    if logs: st.dataframe(pd.DataFrame([dict(x) for x in logs]), use_container_width=True, hide_index=True)


def archive_catalog(user: dict[str, Any]) -> None:
    st.markdown('<div class="section">Arşiv Kataloğu</div>',unsafe_allow_html=True)
    units = query("SELECT code,name FROM units WHERE active=1 ORDER BY name")
    ucodes = ["Tümü"] + [x["code"] for x in units]
    labels = {x["code"]:f'{x["code"]} · {x["name"]}' for x in units}
    c1,c2,c3 = st.columns([2,1,1])
    with c1: search = st.text_input("Ara", placeholder="Kayıt no, belge adı, belge no, kutu, raf...")
    with c2: unit = st.selectbox("Birim", ucodes, format_func=lambda x: "Tümü" if x=="Tümü" else labels[x])
    with c3: classification = st.selectbox("Gizlilik", ["Tümü","INTERNAL","CONFIDENTIAL","RESTRICTED","SECRET"])
    status = st.selectbox("Fiziksel durum", ["Tümü","Depoda","Zimmette","İade Bekleniyor","İmha Edildi"])
    rows = archive_rows(user,search,unit,classification,status)
    st.caption(f"{len(rows)} kayıt")
    if not rows: st.info("Kriterlere uygun kayıt bulunamadı."); return
    df = pd.DataFrame([dict(r) for r in rows])
    display_cols = ["doc_reg_no","doc_name","series_code","unit_code","box_no","shelf_no","status","classification","retention_end_year","destruction_status"]
    df = df[display_cols].rename(columns={"doc_reg_no":"Kayıt No","doc_name":"Belge Adı","series_code":"Seri","unit_code":"Birim","box_no":"Kutu","shelf_no":"Raf","status":"Durum","classification":"Gizlilik","retention_end_year":"Saklama Sonu","destruction_status":"İmha Durumu"})
    st.dataframe(df,use_container_width=True,hide_index=True)
    options = {f'{r["doc_reg_no"]} · {r["doc_name"]}':r["id"] for r in rows}
    selected = st.selectbox("Kayıt ayrıntısı", list(options), index=None, placeholder="Bir kayıt seçin")
    if selected:
        show_archive_detail(user, options[selected])


def show_archive_detail(user: dict[str, Any], archive_id: int) -> None:
    row_list = query("SELECT * FROM aygaz_main_archive WHERE id=?",(archive_id,))
    if not row_list: return
    row = row_list[0]
    if not can_access_archive(user,row): st.error("Bu kayda erişim yetkiniz yok."); return
    audit("ARCHIVE_VIEW",user["username"],object_type="ARCHIVE",object_id=str(archive_id))
    st.markdown(f"### {row['doc_name']}")
    c1,c2,c3 = st.columns(3)
    c1.write(f"**Kayıt No:** {row['doc_reg_no']}")
    c2.write(f"**Belge No:** {row['doc_no'] or '-'}")
    c3.write(f"**Seri:** {row['series_code'] or '-'}")
    c1.write(f"**Birim:** {row['unit_code'] or '-'}")
    c2.write(f"**Kutu / Raf:** {row['box_no'] or '-'} / {row['shelf_no'] or '-'}")
    c3.write(f"**Durum:** {row['status']}")
    c1.write(f"**Gizlilik:** {row['classification']}")
    c2.write(f"**Kişisel veri:** {'Evet' if row['personal_data'] else 'Hayır'}")
    c3.write(f"**Legal hold:** {row['legal_hold_count']}")
    if row["legal_hold_count"]: st.warning("Aktif legal hold bulunduğu için imha işlemi engellenmelidir.")
    files = query("SELECT * FROM archive_files WHERE archive_id=? ORDER BY version_no DESC",(archive_id,))
    if files:
        st.markdown("**Dijital belgeler**")
        for f in files:
            path = DOCUMENT_ROOT / f["stored_name"]
            st.write(f"{f['original_name']} · v{f['version_no']} · {f['size_bytes']} byte · SHA-256 `{f['sha256'][:16]}…`")
            if path.exists() and has_perm(user,"ARCHIVE_READ"):
                st.download_button("Belgeyi indir",path.read_bytes(),file_name=f["original_name"],mime=f["mime_type"] or "application/octet-stream",key=f"dl_{f['id']}")
                audit("DOCUMENT_DOWNLOAD",user["username"],object_type="ARCHIVE_FILE",object_id=str(f["id"]))
    st.markdown("**Erişim geçmişi**")
    acc = query("SELECT timestamp,username,action,result,reason FROM archive_access WHERE archive_id=? ORDER BY id DESC LIMIT 20",(archive_id,))
    if acc: st.dataframe(pd.DataFrame([dict(x) for x in acc]),use_container_width=True,hide_index=True)


def record_management(user: dict[str, Any]) -> None:
    if not (has_perm(user,"ARCHIVE_CREATE") or has_perm(user,"ARCHIVE_EDIT")): st.error("Yetkiniz yok."); return
    st.markdown('<div class="section">Kayıt Yönetimi</div>',unsafe_allow_html=True)
    tab1,tab2 = st.tabs(["Yeni kayıt","Dijital belge yükleme"])
    with tab1:
        units = query("SELECT code,name FROM units WHERE active=1 ORDER BY name")
        series = query("SELECT series_code,name,unit_code,retention_year,trigger_event,legal_basis,confidentiality FROM series WHERE active=1 ORDER BY series_code")
        with st.form("new_archive"):
            c1,c2 = st.columns(2)
            reg = c1.text_input("Kayıt no*",placeholder="90103")
            doc_no = c2.text_input("Belge no")
            name = c1.text_input("Belge adı*")
            unit = c2.selectbox("Birim*",[x["code"] for x in units],format_func=lambda x: next(y["name"] for y in units if y["code"]==x))
            ser = c1.selectbox("Seri*",[x["series_code"] for x in series],format_func=lambda x: next(f'{y["series_code"]} · {y["name"]}' for y in series if y["series_code"]==x))
            last_date = c2.text_input("Son belge tarihi",placeholder="31/12/2026")
            box = c1.text_input("Kutu no"); shelf = c2.text_input("Raf / yer")
            classification = c1.selectbox("Gizlilik",["INTERNAL","CONFIDENTIAL","RESTRICTED","SECRET"])
            personal = c2.checkbox("Kişisel veri içeriyor")
            special = c1.checkbox("Özel nitelikli veri içeriyor")
            submit = st.form_submit_button("Kaydı oluştur",type="primary")
        if submit:
            if not reg.strip() or not name.strip(): st.error("Kayıt no ve belge adı zorunludur."); return
            s = next(x for x in series if x["series_code"]==ser)
            end_year = calculate_retention_end(last_date,s["retention_year"])
            try:
                aid = execute("""INSERT INTO aygaz_main_archive(doc_reg_no,doc_no,doc_name,series_code,unit_code,last_doc_date,box_no,shelf_no,institution,status,destruction_status,retention_end_year,classification,personal_data,special_category_data,retention_trigger,legal_basis,owner_unit,physical_location,metadata_complete,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                              (reg.strip(),doc_no.strip(),name.strip(),ser,unit,last_date.strip(),box.strip(),shelf.strip(),"AYGAZ","Depoda","BEKLİYOR",end_year,classification,int(personal),int(special),s["trigger_event"],s["legal_basis"],unit,shelf.strip(),int(bool(reg and name and ser and unit)),iso_now(),iso_now(),user["username"],user["username"]))
                audit("ARCHIVE_CREATE",user["username"],object_type="ARCHIVE",object_id=str(aid),new_value={"doc_reg_no":reg,"doc_name":name})
                st.success(f"Kayıt oluşturuldu: {reg}")
            except sqlite3.IntegrityError: st.error("Bu kayıt numarası zaten mevcut.")
    with tab2:
        rows = query("SELECT id,doc_reg_no,doc_name FROM aygaz_main_archive ORDER BY id DESC")
        if not rows: st.info("Önce bir arşiv kaydı oluşturun."); return
        labels = {f'{r["doc_reg_no"]} · {r["doc_name"]}':r["id"] for r in rows}
        selected = st.selectbox("Arşiv kaydı",list(labels))
        uploaded = st.file_uploader("Belge",type=sorted(ALLOWED_EXTENSIONS))
        if uploaded and uploaded.size > MAX_UPLOAD_MB*1024*1024: st.error(f"Maksimum dosya boyutu {MAX_UPLOAD_MB} MB."); return
        if uploaded and st.button("Güvenli olarak kaydet",type="primary"):
            ext = Path(uploaded.name).suffix.lower().lstrip(".")
            if ext not in ALLOWED_EXTENSIONS: st.error("Dosya türüne izin verilmiyor."); return
            data = uploaded.getvalue(); digest = sha256_bytes(data); archive_id = labels[selected]
            existing = query("SELECT MAX(version_no) v FROM archive_files WHERE archive_id=?",(archive_id,))[0]["v"] or 0
            stored = f"{archive_id}_{uuid.uuid4().hex}{Path(uploaded.name).suffix.lower()}"
            path = DOCUMENT_ROOT / stored
            path.write_bytes(data)
            execute("INSERT INTO archive_files(archive_id,original_name,stored_name,mime_type,size_bytes,sha256,uploaded_at,uploaded_by,version_no,integrity_status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (archive_id,safe_filename(uploaded.name),stored,uploaded.type or "application/octet-stream",len(data),digest,iso_now(),user["username"],existing+1,"DOĞRULANDI"))
            execute("UPDATE aygaz_main_archive SET updated_at=?,updated_by=? WHERE id=?",(iso_now(),user["username"],archive_id))
            audit("DOCUMENT_UPLOAD",user["username"],object_type="ARCHIVE",object_id=str(archive_id),new_value={"name":uploaded.name,"sha256":digest})
            st.success("Belge güvenli depoya kaydedildi ve SHA-256 bütünlük özeti oluşturuldu.")


def requests_page(user: dict[str, Any]) -> None:
    st.markdown('<div class="section">Erişim Talepleri</div>',unsafe_allow_html=True)
    can_create = has_perm(user,"REQUEST_CREATE")
    tab1,tab2 = st.tabs(["Yeni talep","Talepler"])
    with tab1:
        if not can_create: st.info("Yeni talep oluşturma yetkiniz yok.")
        else:
            with st.form("request_form"):
                item=st.text_input("Belge / kayıt no*"); delivery=st.selectbox("Teslim türü",["Dijital görüntü","Fiziksel dosya","Kopya"]); urgency=st.selectbox("Öncelik",["Normal","Acil"]); notes=st.text_area("Not")
                submit=st.form_submit_button("Talep oluştur",type="primary")
            if submit and item.strip():
                req=f"TAL-{now_tr():%Y%m%d}-{secrets.token_hex(3).upper()}"
                rid=execute("INSERT INTO archive_requests(req_no,requester,unit_code,doc_item,delivery_type,urgency,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(req,user["username"],user["unit_code"],item.strip(),delivery,urgency,"AÇIK",notes.strip(),iso_now()))
                audit("REQUEST_CREATE",user["username"],object_type="REQUEST",object_id=str(rid),new_value={"req_no":req})
                st.success(f"Talep oluşturuldu: {req}")
    with tab2:
        if has_perm(user,"REQUEST_MANAGE") or user.get("unit_code") in ("ALL","*"):
            rows=query("SELECT * FROM archive_requests ORDER BY id DESC")
        else: rows=query("SELECT * FROM archive_requests WHERE requester=? OR unit_code=? ORDER BY id DESC",(user["username"],user["unit_code"]))
        if rows: st.dataframe(pd.DataFrame([dict(x) for x in rows]),use_container_width=True,hide_index=True)
        else: st.info("Talep bulunmuyor.")
        if has_perm(user,"REQUEST_MANAGE") and rows:
            labels={f'{r["req_no"]} · {r["status"]}':r["id"] for r in rows}; selected=st.selectbox("Talep işlemi",list(labels),index=None)
            if selected:
                rid=labels[selected]; new=st.selectbox("Yeni durum",["AÇIK","İNCELEMEDE","ONAYLANDI","TESLİM EDİLDİ","İADE BEKLENİYOR","KAPANDI","İPTAL"])
                if st.button("Durumu güncelle"):
                    old=query("SELECT status FROM archive_requests WHERE id=?",(rid,))[0]["status"]
                    execute("UPDATE archive_requests SET status=?,closed_at=? WHERE id=?",(new,iso_now() if new=="KAPANDI" else None,rid)); audit("REQUEST_STATUS_CHANGE",user["username"],object_type="REQUEST",object_id=str(rid),old_value=old,new_value=new); st.success("Talep güncellendi.")


def destruction_page(user: dict[str, Any]) -> None:
    st.markdown('<div class="section">Saklama ve İmha</div>',unsafe_allow_html=True)
    current=datetime.now(TR_TZ).year
    rows=query("SELECT a.*,COALESCE((SELECT COUNT(*) FROM legal_holds h WHERE h.archive_id=a.id AND h.active=1),0) hold_count FROM aygaz_main_archive a WHERE a.retention_end_year IS NOT NULL AND a.retention_end_year<=? AND a.destruction_status='BEKLİYOR' ORDER BY a.retention_end_year",(current,))
    st.caption(f"Saklama süresi yılı gelen adaylar: {len(rows)}")
    if rows: st.dataframe(pd.DataFrame([dict(x) for x in rows])[['doc_reg_no','doc_name','retention_end_year','hold_count','classification']],use_container_width=True,hide_index=True)
    if has_perm(user,"DESTRUCTION_REQUEST") and rows:
        labels={f'{r["doc_reg_no"]} · {r["doc_name"]}':r["id"] for r in rows}; sel=st.selectbox("İmha süreci başlat",list(labels),index=None)
        if sel and st.button("İmha incelemesi başlat"):
            aid=labels[sel]; hold=query("SELECT COUNT(*) c FROM legal_holds WHERE archive_id=? AND active=1",(aid,))[0]["c"]
            if hold: st.error("Aktif legal hold bulunduğu için süreç başlatılamaz."); security_event("DESTRUCTION_BLOCKED","HIGH",user["username"],f"archive_id={aid} legal_hold")
            else:
                execute("INSERT INTO destruction_workflows(archive_id,stage,requested_by,requested_at) VALUES(?,?,?,?)",(aid,"İNCELEME",user["username"],iso_now())); audit("DESTRUCTION_REQUEST",user["username"],object_type="ARCHIVE",object_id=str(aid)); st.success("İmha inceleme süreci başlatıldı.")
    wf=query("SELECT d.*,a.doc_reg_no,a.doc_name FROM destruction_workflows d JOIN aygaz_main_archive a ON a.id=d.archive_id ORDER BY d.id DESC")
    if wf: st.dataframe(pd.DataFrame([dict(x) for x in wf]),use_container_width=True,hide_index=True)
    if has_perm(user,"DESTRUCTION_REVIEW") and wf:
        labels={f'{r["doc_reg_no"]} · {r["doc_name"]} · {r["stage"]}':r["id"] for r in wf if r["stage"] in ("İNCELEME","ONAY")};
        if labels:
            sel=st.selectbox("İmha inceleme",list(labels),index=None)
            if sel and st.button("İncelemeyi tamamla"):
                wid=labels[sel]; execute("UPDATE destruction_workflows SET stage='ONAY',reviewed_by=?,reviewed_at=? WHERE id=?",(user["username"],iso_now(),wid)); audit("DESTRUCTION_REVIEW",user["username"],object_type="WORKFLOW",object_id=str(wid)); st.success("İnceleme tamamlandı; onay aşamasına geçti.")
    if has_perm(user,"DESTRUCTION_APPROVE") and wf:
        labels={f'{r["doc_reg_no"]} · {r["doc_name"]}':r["id"] for r in wf if r["stage"]=="ONAY"}
        if labels:
            sel=st.selectbox("İmha onayı",list(labels),index=None)
            if sel and st.button("İmhayı onayla"):
                wid=labels[sel]; execute("UPDATE destruction_workflows SET stage='ONAYLANDI',approved_by=?,approved_at=? WHERE id=?",(user["username"],iso_now(),wid)); audit("DESTRUCTION_APPROVE",user["username"],object_type="WORKFLOW",object_id=str(wid)); st.success("İmha onaylandı.")
    if has_perm(user,"DESTRUCTION_EXECUTE") and wf:
        labels={f'{r["doc_reg_no"]} · {r["doc_name"]}':r["id"] for r in wf if r["stage"]=="ONAYLANDI"};
        if labels:
            sel=st.selectbox("İmha uygulama",list(labels),index=None); method=st.selectbox("Yöntem",["Fiziksel imha","Güvenli dijital silme","Yetkili dış hizmet"])
            if sel and st.button("İmhayı gerçekleştir",type="primary"):
                wid=labels[sel]; wr=query("SELECT * FROM destruction_workflows WHERE id=?",(wid,))[0]; hold=query("SELECT COUNT(*) c FROM legal_holds WHERE archive_id=? AND active=1",(wr["archive_id"],))[0]["c"]
                if hold: st.error("Aktif legal hold bulunduğu için imha yapılamaz.")
                else:
                    cert=f"IMH-{now_tr():%Y%m%d}-{secrets.token_hex(4).upper()}"; ts=iso_now()
                    execute("UPDATE destruction_workflows SET stage='TAMAMLANDI',executed_by=?,executed_at=?,certificate_no=?,method=? WHERE id=?",(user["username"],ts,cert,method,wid))
                    execute("UPDATE aygaz_main_archive SET destruction_status='İMHA EDİLDİ',destruction_date=?,status='İmha Edildi',updated_at=?,updated_by=? WHERE id=?",(ts,ts,user["username"],wr["archive_id"]))
                    audit("DESTRUCTION_EXECUTE",user["username"],object_type="ARCHIVE",object_id=str(wr["archive_id"]),new_value={"certificate":cert,"method":method}); st.success(f"İmha tamamlandı. Tutanak no: {cert}")


def legal_hold_page(user: dict[str, Any]) -> None:
    st.markdown('<div class="section">Legal Hold</div>',unsafe_allow_html=True)
    rows=query("SELECT h.*,a.doc_reg_no,a.doc_name FROM legal_holds h JOIN aygaz_main_archive a ON a.id=h.archive_id ORDER BY h.id DESC")
    if rows: st.dataframe(pd.DataFrame([dict(x) for x in rows]),use_container_width=True,hide_index=True)
    if has_perm(user,"LEGAL_HOLD"):
        archives=query("SELECT id,doc_reg_no,doc_name FROM aygaz_main_archive WHERE destruction_status='BEKLİYOR' ORDER BY doc_reg_no")
        labels={f'{r["doc_reg_no"]} · {r["doc_name"]}':r["id"] for r in archives}
        with st.form("hold"):
            sel=st.selectbox("Belge",list(labels)); reason=st.text_area("Gerekçe*"); authority=st.text_input("Yetkili birim / referans"); submit=st.form_submit_button("Legal hold oluştur")
        if submit:
            if not reason.strip(): st.error("Gerekçe zorunludur.")
            else:
                aid=labels[sel]; ref=f"LH-{now_tr():%Y%m%d}-{secrets.token_hex(4).upper()}"; execute("INSERT INTO legal_holds(archive_id,hold_ref,reason,authority,start_date,active,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",(aid,ref,reason.strip(),authority.strip(),now_tr().date().isoformat(),1,user["username"],iso_now())); execute("UPDATE aygaz_main_archive SET legal_hold_count=legal_hold_count+1 WHERE id=?",(aid,)); audit("LEGAL_HOLD_CREATE",user["username"],object_type="ARCHIVE",object_id=str(aid),new_value={"hold_ref":ref}); st.success(f"Legal hold oluşturuldu: {ref}")
        active=[r for r in rows if r["active"]]
        if active:
            labels2={f'{r["hold_ref"]} · {r["doc_reg_no"]}':r["id"] for r in active}; hs=st.selectbox("Aktif hold kaldır",list(labels2),index=None)
            if hs and st.button("Hold'u kaldır"):
                hid=labels2[hs]; h=query("SELECT archive_id FROM legal_holds WHERE id=?",(hid,))[0]; execute("UPDATE legal_holds SET active=0,released_by=?,released_at=? WHERE id=?",(user["username"],iso_now(),hid)); execute("UPDATE aygaz_main_archive SET legal_hold_count=MAX(0,legal_hold_count-1) WHERE id=?",(h["archive_id"],)); audit("LEGAL_HOLD_RELEASE",user["username"],object_type="LEGAL_HOLD",object_id=str(hid)); st.success("Legal hold kaldırıldı.")


def audit_page(user: dict[str, Any]) -> None:
    st.markdown('<div class="section">Denetim ve Güvenlik</div>',unsafe_allow_html=True)
    if not has_perm(user,"AUDIT_VIEW"): st.error("Yetkiniz yok."); return
    a,b,c=st.columns(3)
    a.metric("Audit kayıtları",query("SELECT COUNT(*) c FROM audit_log")[0]["c"])
    b.metric("Güvenlik olayları",query("SELECT COUNT(*) c FROM security_events WHERE resolved=0")[0]["c"])
    c.metric("Aktif legal hold",query("SELECT COUNT(*) c FROM legal_holds WHERE active=1")[0]["c"])
    logs=query("SELECT timestamp,username,action_type,object_type,object_id,result,reason,event_hash FROM audit_log ORDER BY id DESC LIMIT 200")
    if logs: st.dataframe(pd.DataFrame([dict(x) for x in logs]),use_container_width=True,hide_index=True)
    sec=query("SELECT timestamp,username,event_type,severity,details,resolved FROM security_events ORDER BY id DESC LIMIT 100")
    if sec:
        st.markdown("**Güvenlik olayları**"); st.dataframe(pd.DataFrame([dict(x) for x in sec]),use_container_width=True,hide_index=True)
    if has_perm(user,"EXPORT"):
        data=query("SELECT * FROM audit_log ORDER BY id DESC")
        if data:
            buf=io.BytesIO(); pd.DataFrame([dict(x) for x in data]).to_excel(buf,index=False,engine="openpyxl"); buf.seek(0)
            st.download_button("Audit kayıtlarını Excel'e aktar",buf.getvalue(),"aygaz_audit_log.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def user_admin(user: dict[str, Any]) -> None:
    if not has_perm(user,"USER_ADMIN"): st.error("Yetkiniz yok."); return
    st.markdown('<div class="section">Kullanıcı Yönetimi</div>',unsafe_allow_html=True)
    roles=query("SELECT role_code,role_name FROM roles ORDER BY role_name"); units=query("SELECT code,name FROM units ORDER BY name")
    with st.form("user_create"):
        c1,c2=st.columns(2); username=c1.text_input("Kullanıcı adı / SSO ID*"); full=c2.text_input("Ad soyad*"); unit=c1.selectbox("Birim",["ALL"]+[x["code"] for x in units],format_func=lambda x:"Tüm birimler" if x=="ALL" else next(y["name"] for y in units if y["code"]==x)); role=c2.selectbox("Rol",[x["role_code"] for x in roles],format_func=lambda x:next(y["role_name"] for y in roles if y["role_code"]==x)); submit=st.form_submit_button("Kullanıcı ekle")
    if submit:
        try:
            execute("INSERT INTO users(username,full_name,unit_code,role_code,active) VALUES(?,?,?,?,1)",(username.strip(),full.strip(),unit,role)); audit("USER_CREATE",user["username"],object_type="USER",object_id=username.strip()); st.success("Kullanıcı oluşturuldu.")
        except sqlite3.IntegrityError: st.error("Bu kullanıcı zaten mevcut.")
    rows=query("SELECT username,full_name,unit_code,role_code,active,last_login_at FROM users ORDER BY full_name"); st.dataframe(pd.DataFrame([dict(x) for x in rows]),use_container_width=True,hide_index=True)


def export_catalog(user: dict[str, Any]) -> None:
    rows=archive_rows(user)
    if not rows or not has_perm(user,"EXPORT"): return
    buf=io.BytesIO(); pd.DataFrame([dict(x) for x in rows]).to_excel(buf,index=False,engine="openpyxl"); buf.seek(0)
    st.download_button("Kataloğu Excel'e aktar",buf.getvalue(),"aygaz_arsiv_katalog.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def main() -> None:
    st.set_page_config(page_title=APP_NAME,page_icon=None,layout="wide",initial_sidebar_state="expanded")
    inject_css(); init_session()
    try: init_database()
    except Exception as exc:
        st.error("Veritabanı başlatılamadı.")
        st.code(str(exc))
        st.stop()
    user=get_current_user()
    if not user["authenticated"]:
        st.error("Kurumsal kimlik doğrulaması bulunamadı veya kullanıcı yetkili değil.")
        if ENVIRONMENT != "PROD": st.info("Demo ortamında kullanıcı seçimi sol menüde görünmelidir.")
        st.stop()
    menu=sidebar(user)
    st.title(APP_NAME)
    st.caption(f"{APP_VERSION} · {ENVIRONMENT} · {user['full_name']}")
    if menu=="Genel Bakış": dashboard(user)
    elif menu=="Arşiv Kataloğu":
        archive_catalog(user); export_catalog(user)
    elif menu=="Kayıt Yönetimi": record_management(user)
    elif menu=="Erişim Talepleri": requests_page(user)
    elif menu=="Saklama ve İmha": destruction_page(user)
    elif menu=="Legal Hold": legal_hold_page(user)
    elif menu=="Denetim ve Güvenlik": audit_page(user)
    elif menu=="Kullanıcı Yönetimi": user_admin(user)
    st.divider(); st.caption("Demonstrasyon sürümüdür. Üretim ortamında Aygaz kurumsal SSO/IAM, merkezi veritabanı, güvenli belge deposu, SIEM, yedekleme ve kurum politika kontrolleri ayrıca uygulanmalıdır.")


if __name__ == "__main__":
    main()

                                
