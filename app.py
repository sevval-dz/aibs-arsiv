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
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# =========================================================
# AYGAZ ARŞİV SİSTEMİ
# Enterprise-aligned single-file reference implementation
# =========================================================
# IMPORTANT:
# - This application is designed to be deployed behind Aygaz IAM/SSO,
#   reverse proxy/WAF, centralized logging/SIEM and enterprise DB/storage.
# - DEMO mode is intentionally available for presentation/testing.
# - PROD mode FAILS CLOSED when a trusted SSO identity header is missing.
# - Legal retention periods, KVKK inventory, classification policy and
#   internal Aygaz controls must be validated by the relevant Aygaz teams.
# =========================================================

APP_NAME = "Aygaz Arşiv Sistemi"
APP_VERSION = "2.0.0-enterprise-reference"
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("AIBS_DB_PATH", BASE_DIR / "aibs_database.db"))
DOCUMENT_ROOT = Path(os.getenv("AIBS_DOCUMENT_ROOT", BASE_DIR / "secure_documents"))
DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)

ENVIRONMENT = os.getenv("AIBS_ENV", "DEMO").upper()
SSO_HEADER = os.getenv("AIBS_SSO_HEADER", "X-Authenticated-User")
SSO_NAME_HEADER = os.getenv("AIBS_SSO_NAME_HEADER", "X-Authenticated-Name")
SIEM_WEBHOOK = os.getenv("AIBS_SIEM_WEBHOOK_URL", "").strip()
MAX_UPLOAD_MB = int(os.getenv("AIBS_MAX_UPLOAD_MB", "25"))
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "jpg", "jpeg", "png", "tif", "tiff"}
ALLOWED_MIME = {
    "application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv", "text/plain",
    "image/jpeg", "image/png", "image/tiff"
}

TR_TZ = timezone(timedelta(hours=3))
TR_MONTHS = {1:"Oca",2:"Şub",3:"Mar",4:"Nis",5:"May",6:"Haz",7:"Tem",8:"Ağu",9:"Eyl",10:"Eki",11:"Kas",12:"Ara"}
CURRENT_YEAR = datetime.now(TR_TZ).year


def now_tr() -> datetime:
    return datetime.now(TR_TZ)


def iso_now() -> str:
    return now_tr().isoformat(timespec="seconds")


def fmt_dt(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TR_TZ)
        return f"{dt.day:02d} {TR_MONTHS[dt.month]} {dt.year} · {dt:%H:%M}"
    except Exception:
        return str(value)


def clean(value: Any, max_len: int = 500) -> str:
    return str(value if value is not None else "").strip()[:max_len]


def normalize_codes(value: Any) -> set[str]:
    return {x.strip().upper() for x in str(value or "").split(",") if x.strip()}


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_column(conn: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    if name not in column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_database() -> None:
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS institutions (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE, active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS units (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE,
        inst_code TEXT, inst_name TEXT, active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS series (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, unit_code TEXT, unit_name TEXT,
        series_code TEXT NOT NULL UNIQUE, retention_year INTEGER, legal_basis TEXT,
        trigger_event TEXT DEFAULT 'Dosyanın kapanışı', disposition TEXT DEFAULT 'İMHA',
        confidentiality TEXT DEFAULT 'INTERNAL', active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL,
        unit_code TEXT NOT NULL DEFAULT 'ALL', role_code TEXT NOT NULL DEFAULT 'ARCHIVE_USER',
        active INTEGER DEFAULT 1, external_id TEXT, last_login_at TEXT
    );
    CREATE TABLE IF NOT EXISTS roles (
        role_code TEXT PRIMARY KEY, role_name TEXT NOT NULL, permissions TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS aygaz_main_archive (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_reg_no TEXT NOT NULL UNIQUE, doc_no TEXT, doc_name TEXT NOT NULL,
        series_code TEXT, unit_code TEXT, first_doc_date TEXT, last_doc_date TEXT,
        box_no TEXT, shelf_no TEXT, institution TEXT, status TEXT DEFAULT 'Depoda',
        destruction_status TEXT DEFAULT 'BEKLİYOR', destruction_date TEXT,
        retention_end_year INTEGER, classification TEXT DEFAULT 'INTERNAL',
        personal_data INTEGER DEFAULT 0, special_category_data INTEGER DEFAULT 0,
        retention_trigger TEXT, legal_basis TEXT, owner_unit TEXT, current_holder TEXT,
        physical_location TEXT, metadata_complete INTEGER DEFAULT 0, legal_hold_count INTEGER DEFAULT 0,
        created_at TEXT, updated_at TEXT, created_by TEXT, updated_by TEXT
    );
    CREATE TABLE IF NOT EXISTS archive_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT, archive_id INTEGER NOT NULL,
        original_name TEXT NOT NULL, stored_name TEXT NOT NULL UNIQUE, mime_type TEXT,
        size_bytes INTEGER, sha256 TEXT NOT NULL, uploaded_at TEXT NOT NULL, uploaded_by TEXT NOT NULL,
        version_no INTEGER DEFAULT 1, ocr_status TEXT DEFAULT 'BEKLEMEDE', ocr_text TEXT,
        signature_status TEXT DEFAULT 'YOK', integrity_status TEXT DEFAULT 'DOĞRULANMADI',
        FOREIGN KEY(archive_id) REFERENCES aygaz_main_archive(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS archive_access (
        id INTEGER PRIMARY KEY AUTOINCREMENT, archive_id INTEGER NOT NULL, username TEXT NOT NULL,
        action TEXT NOT NULL, result TEXT NOT NULL, reason TEXT, timestamp TEXT NOT NULL,
        correlation_id TEXT NOT NULL, ip_address TEXT, user_agent TEXT,
        FOREIGN KEY(archive_id) REFERENCES aygaz_main_archive(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS archive_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, req_no TEXT NOT NULL UNIQUE, requester TEXT NOT NULL,
        unit_code TEXT NOT NULL, doc_item TEXT NOT NULL, delivery_type TEXT NOT NULL,
        urgency TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'AÇIK', notes TEXT,
        created_at TEXT NOT NULL, due_at TEXT, closed_at TEXT, approved_by TEXT,
        delivered_at TEXT, returned_at TEXT
    );
    CREATE TABLE IF NOT EXISTS request_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, req_no TEXT NOT NULL, sender TEXT NOT NULL,
        message TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS custody_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, archive_id INTEGER NOT NULL, request_id INTEGER,
        event_type TEXT NOT NULL, from_status TEXT, to_status TEXT, actor TEXT NOT NULL,
        timestamp TEXT NOT NULL, due_at TEXT, note TEXT,
        FOREIGN KEY(archive_id) REFERENCES aygaz_main_archive(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS legal_holds (
        id INTEGER PRIMARY KEY AUTOINCREMENT, archive_id INTEGER NOT NULL, hold_ref TEXT NOT NULL UNIQUE,
        reason TEXT NOT NULL, authority TEXT, start_date TEXT NOT NULL, end_date TEXT,
        active INTEGER DEFAULT 1, created_by TEXT NOT NULL, created_at TEXT NOT NULL, released_by TEXT, released_at TEXT,
        FOREIGN KEY(archive_id) REFERENCES aygaz_main_archive(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS destruction_workflows (
        id INTEGER PRIMARY KEY AUTOINCREMENT, archive_id INTEGER NOT NULL, stage TEXT NOT NULL,
        requested_by TEXT NOT NULL, requested_at TEXT NOT NULL, reviewed_by TEXT, reviewed_at TEXT,
        approved_by TEXT, approved_at TEXT, executed_by TEXT, executed_at TEXT,
        certificate_no TEXT, method TEXT, notes TEXT, FOREIGN KEY(archive_id) REFERENCES aygaz_main_archive(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS retention_schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT, series_code TEXT NOT NULL UNIQUE, document_type TEXT NOT NULL,
        retention_years INTEGER, trigger_event TEXT NOT NULL, legal_basis TEXT,
        disposition TEXT NOT NULL DEFAULT 'İMHA', confidentiality TEXT NOT NULL DEFAULT 'INTERNAL',
        kvkk_category TEXT, active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, timestamp TEXT NOT NULL,
        username TEXT NOT NULL, action_type TEXT NOT NULL, object_type TEXT, object_id TEXT,
        result TEXT NOT NULL, reason TEXT, old_value TEXT, new_value TEXT, ip_address TEXT,
        user_agent TEXT, correlation_id TEXT NOT NULL, previous_hash TEXT, event_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS security_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, username TEXT,
        event_type TEXT NOT NULL, severity TEXT NOT NULL, details TEXT, resolved INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_archive_unit_series ON aygaz_main_archive(unit_code, series_code);
    CREATE INDEX IF NOT EXISTS idx_archive_retention ON aygaz_main_archive(retention_end_year, destruction_status);
    CREATE INDEX IF NOT EXISTS idx_archive_classification ON aygaz_main_archive(classification);
    CREATE INDEX IF NOT EXISTS idx_requests_status ON archive_requests(status, unit_code);
    CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp);
    CREATE INDEX IF NOT EXISTS idx_access_time ON archive_access(timestamp);
    """)

    # Backward-compatible migration from the original demo schema.
    ensure_column(conn, "aygaz_main_archive", "classification", "TEXT DEFAULT 'INTERNAL'")
    ensure_column(conn, "aygaz_main_archive", "personal_data", "INTEGER DEFAULT 0")
    ensure_column(conn, "aygaz_main_archive", "special_category_data", "INTEGER DEFAULT 0")
    ensure_column(conn, "aygaz_main_archive", "retention_trigger", "TEXT")
    ensure_column(conn, "aygaz_main_archive", "legal_basis", "TEXT")
    ensure_column(conn, "aygaz_main_archive", "owner_unit", "TEXT")
    ensure_column(conn, "aygaz_main_archive", "current_holder", "TEXT")
    ensure_column(conn, "aygaz_main_archive", "physical_location", "TEXT")
    ensure_column(conn, "aygaz_main_archive", "metadata_complete", "INTEGER DEFAULT 0")
    ensure_column(conn, "aygaz_main_archive", "legal_hold_count", "INTEGER DEFAULT 0")
    ensure_column(conn, "aygaz_main_archive", "created_at", "TEXT")
    ensure_column(conn, "aygaz_main_archive", "updated_at", "TEXT")
    ensure_column(conn, "aygaz_main_archive", "created_by", "TEXT")
    ensure_column(conn, "aygaz_main_archive", "updated_by", "TEXT")

    conn.executemany("INSERT OR IGNORE INTO institutions(id,name,code) VALUES(?,?,?)", [
        (1,"AYGAZ A.Ş.","10"),(11,"ZİNERJİ A.Ş.","40"),(12,"ANADOLU HİSARI TANKERCİLİK","30"),
        (13,"AYGAZ DOĞALGAZ","20"),(15,"AKPA A.Ş.","50"),(17,"GAZAL A.Ş.","60")])
    conn.executemany("INSERT OR IGNORE INTO units(id,name,code,inst_code,inst_name) VALUES(?,?,?,?,?)", [
        (1,"TANIMSIZ","0","10","AYGAZ A.Ş."),(2,"BİLGİ SİSTEM MÜDÜRLÜĞÜ","1001","10","AYGAZ A.Ş."),
        (3,"BÜTÇE PLANLAMA VE KONTROL MÜDÜRLÜĞÜ","1002","10","AYGAZ A.Ş."),(4,"FİNANSMAN MÜDÜRLÜĞÜ","1003","10","AYGAZ A.Ş."),
        (5,"MUHASEBE MÜDÜRLÜĞÜ","1004","10","AYGAZ A.Ş."),(6,"BAYİ GELİŞTİRME MÜDÜRLÜĞÜ","1005","10","AYGAZ A.Ş."),
        (7,"İNSAN KAYNAKLARI MÜDÜRLÜĞÜ","1006","10","AYGAZ A.Ş."),(8,"GEMİ İŞLETME MÜDÜRLÜĞÜ","1007","10","AYGAZ A.Ş."),
        (9,"İŞLETME MÜHENDİSLİK YATIRIMLAR MÜDÜRLÜĞÜ","1008","10","AYGAZ A.Ş.")])
    conn.executemany("INSERT OR IGNORE INTO series(id,name,unit_code,unit_name,series_code,retention_year,legal_basis,trigger_event,disposition,confidentiality) VALUES(?,?,?,?,?,?,?,?,?,?)", [
        (1,"PERSONEL ÖZLÜK DOSYALARI","1006","İNSAN KAYNAKLARI MÜDÜRLÜĞÜ","1",10,"İş Kanunu Md. 75","İş ilişkisinin sona ermesi / kurum politikasıyla doğrulanacak süre","İMHA","RESTRICTED"),
        (3,"MAKBUZ VE TAHSİLAT BELGELERİ","1004","MUHASEBE MÜDÜRLÜĞÜ","3",10,"VUK Md. 253","Belgenin düzenlenmesi / yasal sürenin başlangıcı doğrulanmalı","İMHA","CONFIDENTIAL"),
        (4,"MAHSUP VE YEVMİYE FİŞLERİ","1004","MUHASEBE MÜDÜRLÜĞÜ","4",10,"TTK Md. 82","İlgili hesap döneminin kapanışı","İMHA","CONFIDENTIAL"),
        (9,"TİCARİ BAYİLİK VE MÜLKİYET SÖZLEŞMELERİ","1004","MUHASEBE MÜDÜRLÜĞÜ","9",100,"Kurum hukuk politikasıyla doğrulanmalı","Sözleşmenin sona ermesi / uyuşmazlık yokluğu","İMHA","CONFIDENTIAL"),
        (11,"İŞ SAĞLIĞI VE AMBARLI TEFTİŞ RAPORLARI","1008","İŞLETME MÜHENDİSLİK YATIRIMLAR MÜDÜRLÜĞÜ","11",15,"6331 sayılı mevzuatla birlikte Aygaz Hukuk/İSG politikası doğrulanmalı","Raporun kapanışı","İMHA","CONFIDENTIAL")])
    conn.executemany("INSERT OR IGNORE INTO roles(role_code,role_name,permissions) VALUES(?,?,?)", [
        ("ARCHIVE_ADMIN","Arşiv Yöneticisi","ARCHIVE_READ,ARCHIVE_CREATE,ARCHIVE_EDIT,REQUEST_MANAGE,DESTRUCTION_REQUEST,DESTRUCTION_REVIEW,DESTRUCTION_APPROVE,DESTRUCTION_EXECUTE,LEGAL_HOLD,AUDIT_VIEW,USER_ADMIN,EXPORT"),
        ("ARCHIVE_OFFICER","Arşiv Görevlisi","ARCHIVE_READ,ARCHIVE_CREATE,ARCHIVE_EDIT,REQUEST_MANAGE,DESTRUCTION_REQUEST,LEGAL_HOLD,EXPORT"),
        ("ARCHIVE_AUDITOR","Denetim","ARCHIVE_READ,AUDIT_VIEW,EXPORT"),
        ("ARCHIVE_USER","Birim Kullanıcısı","ARCHIVE_READ,REQUEST_CREATE,REQUEST_VIEW"),
        ("DESTRUCTION_REVIEWER","İmha İnceleme","ARCHIVE_READ,DESTRUCTION_REQUEST,DESTRUCTION_REVIEW,LEGAL_HOLD,AUDIT_VIEW"),
        ("DESTRUCTION_EXECUTOR","İmha Uygulama","ARCHIVE_READ,DESTRUCTION_EXECUTE,AUDIT_VIEW")])

    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute("INSERT INTO users(username,full_name,unit_code,role_code,active) VALUES(?,?,?,?,1)", ("local\\admin","Arşiv Yöneticisi","ALL","ARCHIVE_ADMIN"))
    if conn.execute("SELECT COUNT(*) FROM aygaz_main_archive").fetchone()[0] == 0:
        seed = [
            ("90101","1411-23-201","Bayi faaliyet raporları","6","1004","01/08/2023","31/08/2023","23050","H11.211","AYGAZ","Depoda","BEKLİYOR",None,2028,"INTERNAL",0,0,"Dosyanın kapanışı","Kurum politikasıyla doğrulanmalı","1004","", "H11 / 211",0,0,iso_now(),iso_now(),"local\\admin","local\\admin"),
            ("90102","1411-23-202","Ticari bayilik sözleşmeleri","9","1004","01/08/2023","31/08/2023","23051","H11.212","AYGAZ","Zimmette","BEKLİYOR",None,2123,"CONFIDENTIAL",0,0,"Sözleşmenin sona ermesi","Kurum hukuk politikasıyla doğrulanmalı","1004","Kullanıcı", "H11 / 212",0,0,iso_now(),iso_now(),"local\\admin","local\\admin"),
            ("90085","1205-22-040","İSG saha denetim raporları","11","1008","10/05/2022","15/05/2022","22910","H10.014","AYGAZ","Depoda","BEKLİYOR",None,2037,"CONFIDENTIAL",1,0,"Raporun kapanışı","6331 + kurum politikası doğrulanmalı","1008","", "H10 / 014",0,0,iso_now(),iso_now(),"local\\admin","local\\admin")]
        conn.executemany("""INSERT INTO aygaz_main_archive(doc_reg_no,doc_no,doc_name,series_code,unit_code,first_doc_date,last_doc_date,box_no,shelf_no,institution,status,destruction_status,destruction_date,retention_end_year,classification,personal_data,special_category_data,retention_trigger,legal_basis,owner_unit,current_holder,physical_location,metadata_complete,legal_hold_count,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", seed)

    # Synchronize retention schedule from series without overriding administrator edits.
    for row in conn.execute("SELECT series_code,name,retention_year,trigger_event,legal_basis,disposition,confidentiality FROM series").fetchall():
        conn.execute("INSERT OR IGNORE INTO retention_schedule(series_code,document_type,retention_years,trigger_event,legal_basis,disposition,confidentiality) VALUES(?,?,?,?,?,?,?)", tuple(row))

    conn.commit(); conn.close()


def query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = get_db()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


def scalar(sql: str, params: tuple = ()) -> Any:
    conn = get_db()
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def hash_event(payload: str, previous: str) -> str:
    return hashlib.sha256((previous + payload).encode("utf-8")).hexdigest()


def audit(username: str, action: str, result: str = "SUCCESS", object_type: str = "SYSTEM", object_id: str = "", reason: str = "", old: Any = "", new: Any = "", ip: str = "", ua: str = "") -> str:
    event_id = str(uuid.uuid4())
    correlation = str(uuid.uuid4())
    timestamp = iso_now()
    old_s = json.dumps(old, ensure_ascii=False, default=str) if not isinstance(old, str) else old
    new_s = json.dumps(new, ensure_ascii=False, default=str) if not isinstance(new, str) else new
    payload = json.dumps({"event_id":event_id,"timestamp":timestamp,"username":username,"action":action,"result":result,"object_type":object_type,"object_id":object_id,"reason":reason,"old":old_s,"new":new_s}, ensure_ascii=False, sort_keys=True)
    conn = get_db()
    try:
        prev = conn.execute("SELECT event_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        previous_hash = prev[0] if prev else "GENESIS"
        event_hash = hash_event(payload, previous_hash)
        conn.execute("INSERT INTO audit_log(event_id,timestamp,username,action_type,object_type,object_id,result,reason,old_value,new_value,ip_address,user_agent,correlation_id,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (event_id,timestamp,username,action,object_type,object_id,result,reason,old_s,new_s,ip,ua,correlation,previous_hash,event_hash))
        conn.commit()
    finally:
        conn.close()
    return event_id


def security_event(username: str | None, event_type: str, severity: str, details: str) -> None:
    conn = get_db(); conn.execute("INSERT INTO security_events(timestamp,username,event_type,severity,details) VALUES(?,?,?,?,?)", (iso_now(),username,event_type,severity,details)); conn.commit(); conn.close()


def current_identity() -> dict[str, Any] | None:
    # In production, identity MUST come from a trusted reverse proxy/IAM layer.
    if ENVIRONMENT == "PROD":
        try:
            headers = st.context.headers
            username = headers.get(SSO_HEADER)
            if not username:
                return None
            name = headers.get(SSO_NAME_HEADER) or username
            row = query_df("SELECT * FROM users WHERE username = ? AND active = 1", (username,))
            if row.empty:
                security_event(username, "UNKNOWN_IDENTITY", "HIGH", "SSO kimliği uygulama kullanıcı kataloğunda bulunamadı")
                return None
            return {**row.iloc[0].to_dict(), "full_name": name or row.iloc[0]["full_name"], "source":"SSO"}
        except Exception:
            return None
    return None


def permissions_for(user: dict[str, Any]) -> set[str]:
    row = query_df("SELECT permissions FROM roles WHERE role_code=?", (user["role_code"],))
    if row.empty: return set()
    return normalize_codes(row.iloc[0]["permissions"])


def has_perm(user: dict[str, Any], permission: str) -> bool:
    return permission.upper() in permissions_for(user)


def in_scope(user: dict[str, Any], unit_code: str) -> bool:
    return str(user.get("unit_code", "")).upper() == "ALL" or str(user.get("unit_code")) == str(unit_code)


def can_access_record(user: dict[str, Any], record: pd.Series | dict[str, Any]) -> bool:
    if not has_perm(user, "ARCHIVE_READ"):
        return False
    if not in_scope(user, record.get("unit_code", "")):
        return False
    classification = str(record.get("classification") or "INTERNAL").upper()
    role = str(user.get("role_code"))
    if classification == "RESTRICTED" and role not in {"ARCHIVE_ADMIN", "ARCHIVE_AUDITOR"} and record.get("owner_unit") != user.get("unit_code"):
        return False
    return True


def record_access(archive_id: int, user: dict[str, Any], action: str, result: str, reason: str = "") -> None:
    conn = get_db()
    conn.execute("INSERT INTO archive_access(archive_id,username,action,result,reason,timestamp,correlation_id) VALUES(?,?,?,?,?,?,?)", (archive_id,user["username"],action,result,reason,iso_now(),str(uuid.uuid4())))
    conn.commit(); conn.close()
    audit(user["username"], f"DOCUMENT_{action}", result, "ARCHIVE", str(archive_id), reason=reason)


def next_req_no() -> str:
    return f"TA-{now_tr():%Y%m%d}-{secrets.token_hex(3).upper()}"


def compute_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_uploaded_file(uploaded, archive_id: int, user: dict[str, Any]) -> tuple[bool, str]:
    if uploaded is None: return False, "Dosya seçilmedi."
    ext = Path(uploaded.name).suffix.lower().lstrip(".")
    mime = uploaded.type or "application/octet-stream"
    data = uploaded.getvalue()
    if ext not in ALLOWED_EXTENSIONS or mime not in ALLOWED_MIME:
        return False, "Dosya türü güvenlik politikası tarafından engellendi."
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        return False, f"Dosya boyutu {MAX_UPLOAD_MB} MB sınırını aşıyor."
    digest = compute_hash(data)
    stored = f"{uuid.uuid4().hex}.{ext}"
    target = DOCUMENT_ROOT / stored
    target.write_bytes(data)
    conn = get_db()
    version = conn.execute("SELECT COALESCE(MAX(version_no),0)+1 FROM archive_files WHERE archive_id=?", (archive_id,)).fetchone()[0]
    conn.execute("INSERT INTO archive_files(archive_id,original_name,stored_name,mime_type,size_bytes,sha256,uploaded_at,uploaded_by,version_no,integrity_status) VALUES(?,?,?,?,?,?,?,?,?,?)", (archive_id,clean(uploaded.name,255),stored,mime,len(data),digest,iso_now(),user["username"],version,"DOĞRULANDI"))
    conn.execute("UPDATE aygaz_main_archive SET updated_at=?,updated_by=? WHERE id=?", (iso_now(),user["username"],archive_id))
    conn.commit(); conn.close()
    audit(user["username"], "FILE_UPLOAD", "SUCCESS", "ARCHIVE", str(archive_id), new={"filename":uploaded.name,"sha256":digest,"size":len(data)})
    return True, digest


def legal_hold_active(archive_id: int) -> bool:
    return bool(scalar("SELECT COUNT(*) FROM legal_holds WHERE archive_id=? AND active=1", (archive_id,)))


def refresh_hold_count(conn: sqlite3.Connection, archive_id: int) -> None:
    count = conn.execute("SELECT COUNT(*) FROM legal_holds WHERE archive_id=? AND active=1", (archive_id,)).fetchone()[0]
    conn.execute("UPDATE aygaz_main_archive SET legal_hold_count=? WHERE id=?", (count,archive_id))


def request_destruction(archive_id: int, user: dict[str, Any], reason: str) -> tuple[bool,str]:
    if not has_perm(user,"DESTRUCTION_REQUEST"): return False,"Bu işlem için yetkiniz yok."
    rec = query_df("SELECT * FROM aygaz_main_archive WHERE id=?", (archive_id,))
    if rec.empty: return False,"Kayıt bulunamadı."
    r = rec.iloc[0]
    if not in_scope(user,r.unit_code): return False,"Kayıt birim kapsamınız dışında."
    if legal_hold_active(archive_id): return False,"Aktif hukuki/idari bekletme (legal hold) bulunduğu için imha talebi açılamaz."
    if str(r.destruction_status).upper() == "İMHA EDİLDİ": return False,"Kayıt zaten imha edilmiş."
    conn = get_db()
    conn.execute("INSERT INTO destruction_workflows(archive_id,stage,requested_by,requested_at,notes) VALUES(?,?,?,?,?)", (archive_id,"TALEP",user["username"],iso_now(),reason))
    conn.execute("UPDATE aygaz_main_archive SET destruction_status='TALEP AÇILDI',updated_at=?,updated_by=? WHERE id=?", (iso_now(),user["username"],archive_id))
    conn.commit(); conn.close()
    audit(user["username"],"DESTRUCTION_REQUEST","SUCCESS","ARCHIVE",str(archive_id),reason=reason)
    return True,"İmha talebi oluşturuldu."


def review_destruction(workflow_id: int, user: dict[str, Any], approve: bool, note: str) -> tuple[bool,str]:
    if not has_perm(user,"DESTRUCTION_REVIEW"): return False,"İmha inceleme yetkiniz yok."
    wf = query_df("SELECT * FROM destruction_workflows WHERE id=?", (workflow_id,))
    if wf.empty: return False,"İmha iş akışı bulunamadı."
    row = wf.iloc[0]
    if row.requested_by == user["username"]: return False,"Ayrılık görevleri ilkesi gereği talebi açan kişi aynı talebi inceleyemez."
    if legal_hold_active(int(row.archive_id)): return False,"Aktif legal hold bulunduğu için inceleme tamamlanamaz."
    stage = "ONAY" if approve else "RED"
    conn = get_db(); conn.execute("UPDATE destruction_workflows SET stage=?,reviewed_by=?,reviewed_at=?,notes=COALESCE(notes,'') || ? WHERE id=?", (stage,user["username"],iso_now(),"\n"+note,workflow_id)); conn.execute("UPDATE aygaz_main_archive SET destruction_status=?,updated_at=?,updated_by=? WHERE id=?", ("İNCELEME ONAYI" if approve else "İMHA RED",iso_now(),user["username"],int(row.archive_id))); conn.commit(); conn.close()
    audit(user["username"],"DESTRUCTION_REVIEW","SUCCESS","DESTRUCTION_WORKFLOW",str(workflow_id),new={"stage":stage,"note":note})
    return True,"İmha incelemesi kaydedildi."


def execute_destruction(workflow_id: int, user: dict[str, Any], method: str, certificate: str) -> tuple[bool,str]:
    if not has_perm(user,"DESTRUCTION_EXECUTE"): return False,"İmha uygulama yetkiniz yok."
    wf = query_df("SELECT * FROM destruction_workflows WHERE id=?", (workflow_id,))
    if wf.empty: return False,"İmha iş akışı bulunamadı."
    row = wf.iloc[0]
    if row.stage != "ONAY": return False,"Bu kayıt onay aşamasında değil."
    if row.requested_by == user["username"] or row.reviewed_by == user["username"]: return False,"Ayrılık görevleri ilkesi gereği talep/inceleme yapan kişi uygulayıcı olamaz."
    if legal_hold_active(int(row.archive_id)): return False,"Aktif legal hold bulunduğu için imha yapılamaz."
    if not certificate.strip(): return False,"İmha tutanak/sertifika numarası zorunludur."
    conn = get_db(); today=iso_now(); conn.execute("UPDATE destruction_workflows SET stage='TAMAMLANDI',executed_by=?,executed_at=?,certificate_no=?,method=? WHERE id=?", (user["username"],today,certificate.strip(),method,workflow_id)); conn.execute("UPDATE aygaz_main_archive SET destruction_status='İMHA EDİLDİ',destruction_date=?,status='İMHA EDİLDİ',updated_at=?,updated_by=? WHERE id=?", (today,today,user["username"],int(row.archive_id))); conn.commit(); conn.close()
    audit(user["username"],"DESTRUCTION_EXECUTE","SUCCESS","DESTRUCTION_WORKFLOW",str(workflow_id),new={"certificate":certificate,"method":method})
    return True,"İmha işlemi ve tutanak kaydı tamamlandı."


def add_legal_hold(archive_id: int, user: dict[str, Any], reason: str, authority: str, end_date: str | None) -> tuple[bool,str]:
    if not has_perm(user,"LEGAL_HOLD"): return False,"Legal hold yetkiniz yok."
    if not reason.strip(): return False,"Gerekçe zorunludur."
    ref = f"LH-{now_tr():%Y%m%d}-{secrets.token_hex(3).upper()}"
    conn=get_db(); conn.execute("INSERT INTO legal_holds(archive_id,hold_ref,reason,authority,start_date,end_date,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",(archive_id,ref,reason,authority,iso_now(),end_date,user["username"],iso_now())); refresh_hold_count(conn,archive_id); conn.commit(); conn.close()
    audit(user["username"],"LEGAL_HOLD_CREATE","SUCCESS","ARCHIVE",str(archive_id),new={"hold_ref":ref,"reason":reason})
    return True,ref


def release_legal_hold(hold_id: int, user: dict[str, Any]) -> tuple[bool,str]:
    if not has_perm(user,"LEGAL_HOLD"): return False,"Legal hold yetkiniz yok."
    row=query_df("SELECT * FROM legal_holds WHERE id=? AND active=1",(hold_id,))
    if row.empty:return False,"Aktif hold bulunamadı."
    if row.iloc[0].created_by == user["username"] and user["role_code"] != "ARCHIVE_ADMIN": return False,"Aynı kişi tarafından açılan hold, yönetici onayı olmadan kaldırılamaz."
    conn=get_db(); conn.execute("UPDATE legal_holds SET active=0,released_by=?,released_at=? WHERE id=?",(user["username"],iso_now(),hold_id)); refresh_hold_count(conn,int(row.iloc[0].archive_id)); conn.commit(); conn.close()
    audit(user["username"],"LEGAL_HOLD_RELEASE","SUCCESS","LEGAL_HOLD",str(hold_id)); return True,"Legal hold kaldırıldı."


def export_excel(df: pd.DataFrame, filename: str, sheet: str = "Rapor") -> None:
    out=io.BytesIO()
    with pd.ExcelWriter(out,engine="openpyxl") as writer: df.to_excel(writer,index=False,sheet_name=sheet[:31])
    st.download_button("Excel indir",out.getvalue(),filename,"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def logo_uri() -> str:
    p=BASE_DIR/"Aygaz.png"
    if p.exists(): return "data:image/png;base64,"+base64.b64encode(p.read_bytes()).decode()
    return ""


def setup_css() -> None:
    st.markdown("""
    <style>
    :root{--aygaz:#0072bc;--aygaz-dark:#005b94;--ink:#143143;--muted:#687984;--line:#dce6eb;--bg:#f5f8fa}
    html,body,[class*="css"]{font-family:'DM Sans',Arial,sans-serif}
    .stApp{background:var(--bg)}
    [data-testid="stToolbar"],[data-testid="stHeaderActionElements"],#MainMenu,footer{display:none!important}
    [data-testid="stSidebar"]{background:var(--aygaz)!important}
    [data-testid="stSidebar"] *{color:#fff}
    [data-testid="stSidebar"] hr{border-color:#54a7d1}
    .topbar{background:#fff;border-bottom:1px solid var(--line);padding:13px 25px;margin:-1rem -1rem 25px;display:flex;justify-content:space-between;align-items:center}
    .brand{padding:8px 0 20px}.brand-name{font-size:21px;font-weight:700}.brand-meta{font-size:11px;color:#d9effb}
    .metric,.panel{background:#fff;border:1px solid var(--line);border-radius:9px;padding:17px}.metric{min-height:102px}.metric-label{font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:1px}.metric-value{font-size:27px;font-weight:700;color:var(--ink);margin:7px 0}.metric-note{font-size:11px;color:var(--muted)}
    .eyebrow{font-family:monospace;color:var(--aygaz);font-size:10px;letter-spacing:1.3px}.stamp{border:1px solid var(--line);background:#fff;border-radius:7px;padding:8px 11px;color:var(--muted);font-family:monospace;font-size:11px}
    .scope{background:#eaf4fa;border:1px solid #c9e2f2;border-radius:6px;padding:9px 12px;color:#075b91;font-size:12px;margin-bottom:16px}.warning{background:#fff5e8;border-left:3px solid #d88924;padding:11px 13px;color:#75451f;font-size:12px;border-radius:4px}.successbox{background:#edf8f2;border-left:3px solid #2d8a59;padding:11px 13px;color:#24544d;font-size:12px;border-radius:4px}
    .stButton button,.stDownloadButton button,.stFormSubmitButton button{background:var(--aygaz)!important;border:1px solid var(--aygaz)!important;color:#fff!important;border-radius:6px;font-weight:600}.stButton button:hover,.stDownloadButton button:hover{background:var(--aygaz-dark)!important}
    </style>
    """,unsafe_allow_html=True)


def resolve_user() -> dict[str,Any] | None:
    sso=current_identity()
    if ENVIRONMENT=="PROD": return sso
    users=query_df("SELECT * FROM users WHERE active=1 ORDER BY id")
    if users.empty:return None
    labels=[f"{r.full_name} · {r.username} · {r.role_code}" for r in users.itertuples()]
    configured=os.getenv("AIBS_USER","").casefold()
    default=next((i for i,r in enumerate(users.itertuples()) if str(r.username).casefold()==configured),0)
    selected=st.selectbox("DEMO kullanıcı profili",labels,index=default)
    return users.iloc[labels.index(selected)].to_dict()


def header(title:str,desc:str,menu:str,user:dict[str,Any]) -> None:
    logo=logo_uri(); img=f'<img src="{logo}" style="width:34px;height:34px;object-fit:contain">' if logo else '<b style="font-size:22px;color:#0072bc">A</b>'
    st.markdown(f'<div class="topbar"><div style="display:flex;gap:10px;align-items:center">{img}<b style="color:#005b94">AYGAZ ARŞİV SİSTEMİ</b></div><div style="font-size:12px;color:#143143"><b>{clean(user.get("full_name"),80)}</b> · {user.get("role_code")}</div></div>',unsafe_allow_html=True)
    st.markdown(f'<div class="scope"><b>{ENVIRONMENT}</b> · {menu} · Kapsam: {"Tüm birimler" if user.get("unit_code")=="ALL" else user.get("unit_code")}</div>',unsafe_allow_html=True)
    st.markdown(f'<div style="display:flex;justify-content:space-between;align-items:end;margin-bottom:18px"><div><div class="eyebrow">AYGAZ ARŞİV SİSTEMİ / {menu.upper()}</div><h1>{title}</h1><p>{desc}</p></div><div class="stamp">{fmt_dt(iso_now())}</div></div>',unsafe_allow_html=True)


st.set_page_config(page_title=APP_NAME,page_icon="Aygaz.png",layout="wide",initial_sidebar_state="expanded")
init_database()
setup_css()

# Production identity gate
with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-name">Aygaz Arşiv Sistemi</div><div class="brand-meta">KURUMSAL ARŞİV YÖNETİM PLATFORMU</div></div>',unsafe_allow_html=True)
    user=resolve_user()
    if not user:
        st.error("Kurumsal kimlik doğrulaması başarısız veya kullanıcı yetkili değil.")
        st.stop()
    perms=permissions_for(user)
    st.caption(f"{user['role_code']} · {user['unit_code']}")

    menu_items=["Ana Panel","Arşiv Kataloğu","Erişim Talepleri","Belge Yönetimi"]
    if has_perm(user,"DESTRUCTION_REQUEST") or has_perm(user,"DESTRUCTION_REVIEW") or has_perm(user,"DESTRUCTION_EXECUTE"): menu_items.append("Saklama ve İmha")
    if has_perm(user,"LEGAL_HOLD"): menu_items.append("Legal Hold")
    if has_perm(user,"AUDIT_VIEW"): menu_items.extend(["Denetim İzi","Güvenlik Merkezi"])
    if user.get("role_code")=="ARCHIVE_ADMIN": menu_items.append("Tanımlar ve Yönetim")
    menu=st.radio("Çalışma alanı",menu_items,label_visibility="visible")
    st.markdown("---")
    st.caption(f"Sürüm {APP_VERSION}")
    st.caption(f"Veritabanı: {'SQLite / DEMO' if ENVIRONMENT!='PROD' else 'Enterprise adapter için hazır'}")

# ========================= MAIN DASHBOARD =========================
if menu=="Ana Panel":
    header("Arşiv kontrol merkezi","Kayıt, güvenlik, saklama ve iş akışlarını tek ekranda izleyin.",menu,user)
    scope_sql="" if user.get("unit_code")=="ALL" else " AND unit_code=?"; scope_params=() if user.get("unit_code")=="ALL" else (user["unit_code"],)
    total=scalar("SELECT COUNT(*) FROM aygaz_main_archive WHERE 1=1"+scope_sql,scope_params)
    custody=scalar("SELECT COUNT(*) FROM aygaz_main_archive WHERE status='Zimmette'"+scope_sql,scope_params)
    overdue=scalar("SELECT COUNT(*) FROM aygaz_main_archive WHERE retention_end_year<=? AND destruction_status!='İMHA EDİLDİ' AND legal_hold_count=0"+(" AND unit_code=?" if user.get("unit_code")!="ALL" else ""),(CURRENT_YEAR,)+scope_params)
    holds=scalar("SELECT COUNT(*) FROM legal_holds WHERE active=1") if user.get("unit_code")=="ALL" else scalar("SELECT COUNT(*) FROM legal_holds h JOIN aygaz_main_archive a ON a.id=h.archive_id WHERE h.active=1 AND a.unit_code=?",(user["unit_code"],))
    open_req=scalar("SELECT COUNT(*) FROM archive_requests WHERE status NOT IN ('TAMAMLANDI','İPTAL')"+(" AND unit_code=?" if user.get("unit_code")!="ALL" else ""),scope_params)
    c=st.columns(5)
    for col,label,val,note in zip(c,["Kayıt","Zimmette","Saklama Riski","Legal Hold","Açık Talep"],[total,custody,overdue,holds,open_req],["kapsam","fiziksel hareket","hold hariç","aktif bekletme","iş kuyruğu"]):
        with col: st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{val:,}</div><div class="metric-note">{note}</div></div>',unsafe_allow_html=True)
    st.markdown("### Operasyon durumu")
    a,b=st.columns(2)
    with a:
        status=query_df("SELECT status AS Durum,COUNT(*) AS Adet FROM aygaz_main_archive GROUP BY status ORDER BY Adet DESC")
        st.dataframe(status,use_container_width=True,hide_index=True)
    with b:
        sec=query_df("SELECT severity AS Seviye,COUNT(*) AS Adet FROM security_events WHERE resolved=0 GROUP BY severity ORDER BY Adet DESC")
        st.dataframe(sec,use_container_width=True,hide_index=True)
    st.markdown('<div class="successbox"><b>Kontrol ilkesi:</b> Erişim, değişiklik, indirme, legal hold ve imha kararları denetim izine bağlanır. İmha, tek adımlı silme yerine talep → inceleme → onay → uygulama zinciriyle yürütülür.</div>',unsafe_allow_html=True)

# ========================= CATALOG =========================
elif menu=="Arşiv Kataloğu":
    header("Arşiv kataloğu","Belgeyi metadata, saklama planı, fiziksel konum ve güvenlik sınıfıyla bulun.",menu,user)
    search=st.text_input("Katalogda ara",placeholder="Kayıt no, belge adı, seri, kutu, raf, OCR metni...")
    f1,f2,f3,f4=st.columns(4)
    with f1: status=st.selectbox("Durum",["Tümü","Depoda","Zimmette","İMHA EDİLDİ","TALEP AÇILDI"])
    with f2: classification=st.selectbox("Sınıflandırma",["Tümü","GENERAL","INTERNAL","CONFIDENTIAL","RESTRICTED"])
    with f3: series=st.text_input("Seri kodu")
    with f4: limit=st.selectbox("Kayıt",[25,50,100,250])
    sql="""SELECT a.id AS ID,a.doc_reg_no AS [Kayıt No],a.doc_no AS [Dosya No],a.doc_name AS [Belge],a.series_code AS [Seri],a.unit_code AS [Birim],a.classification AS [Sınıf],a.status AS [Durum],a.box_no AS [Kutu],a.shelf_no AS [Yer],a.physical_location AS [Fiziksel Konum],a.retention_end_year AS [Saklama Sonu],a.legal_hold_count AS [Legal Hold],a.destruction_status AS [İmha],a.metadata_complete AS [Metadata] FROM aygaz_main_archive a WHERE 1=1"""
    params=[]
    if user.get("unit_code")!="ALL": sql+=" AND a.unit_code=?"; params.append(user["unit_code"])
    if search.strip(): sql+=" AND (a.doc_reg_no LIKE ? OR a.doc_no LIKE ? OR a.doc_name LIKE ? OR a.series_code LIKE ? OR a.box_no LIKE ? OR a.shelf_no LIKE ? OR EXISTS(SELECT 1 FROM archive_files f WHERE f.archive_id=a.id AND f.ocr_text LIKE ?))"; params += [f"%{search.strip()}%"]*7
    if status!="Tümü": sql+=" AND a.status=?"; params.append(status)
    if classification!="Tümü": sql+=" AND a.classification=?"; params.append(classification)
    if series.strip(): sql+=" AND a.series_code LIKE ?"; params.append(f"%{series.strip()}%")
    sql+=" ORDER BY a.id DESC LIMIT ?"; params.append(limit)
    df=query_df(sql,tuple(params)); st.dataframe(df.drop(columns=["ID"],errors="ignore"),use_container_width=True,hide_index=True,height=440); export_excel(df.drop(columns=["ID"],errors="ignore"),"aygaz-arsiv-katalog.xlsx","Arşiv Kataloğu")
    if not df.empty:
        selected_id=st.selectbox("Kayıt detayı",df["ID"].tolist())
        rec=query_df("SELECT * FROM aygaz_main_archive WHERE id=?",(int(selected_id),))
        if not rec.empty:
            r=rec.iloc[0]
            if not can_access_record(user,r): st.warning("Bu kaydın metadata görünümü yetki kapsamınız dışında.")
            else:
                record_access(int(selected_id),user,"VIEW","SUCCESS")
                tabs=st.tabs(["Detay","Dosyalar","Erişim Geçmişi"])
                with tabs[0]:
                    d1,d2,d3=st.columns(3)
                    with d1: st.write("**Belge:**",r.doc_name); st.write("**Kayıt No:**",r.doc_reg_no); st.write("**Seri:**",r.series_code); st.write("**Birim:**",r.unit_code)
                    with d2: st.write("**Sınıf:**",r.classification); st.write("**Saklama Sonu:**",r.retention_end_year); st.write("**Legal Hold:**",r.legal_hold_count); st.write("**Kişisel Veri:**","Evet" if r.personal_data else "Hayır")
                    with d3: st.write("**Kutu:**",r.box_no); st.write("**Yer:**",r.shelf_no); st.write("**Fiziksel Konum:**",r.physical_location); st.write("**Durum:**",r.status)
                    if has_perm(user,"EXPORT"):
                        st.caption("İndirme/çıktı işlemleri ayrıca erişim günlüğüne yazılır.")
                with tabs[1]:
                    files=query_df("SELECT id,original_name,mime_type,size_bytes,sha256,version_no,ocr_status,signature_status,integrity_status,uploaded_at,uploaded_by FROM archive_files WHERE archive_id=? ORDER BY version_no DESC",(int(selected_id),)); st.dataframe(files,use_container_width=True,hide_index=True)
                    if has_perm(user,"ARCHIVE_EDIT"):
                        uploaded=st.file_uploader("Yeni belge sürümü yükle",type=sorted(ALLOWED_EXTENSIONS))
                        if uploaded and st.button("Güvenli şekilde kaydet",type="primary"):
                            ok,msg=save_uploaded_file(uploaded,int(selected_id),user); st.success(msg) if ok else st.error(msg)
                with tabs[2]:
                    acc=query_df("SELECT timestamp AS Zaman,username AS Kullanıcı,action AS İşlem,result AS Sonuç,reason AS Gerekçe FROM archive_access WHERE archive_id=? ORDER BY id DESC LIMIT 100",(int(selected_id),)); st.dataframe(acc,use_container_width=True,hide_index=True)
    if has_perm(user,"ARCHIVE_CREATE"):
        with st.expander("Yeni arşiv kaydı oluştur"):
            with st.form("new_record"):
                a,b,c=st.columns(3)
                with a: reg=st.text_input("Kayıt No *"); doc=st.text_input("Dosya No"); name=st.text_input("Belge Adı *"); unit=st.text_input("Birim Kodu *")
                with b: ser=st.text_input("Seri Kodu"); cls=st.selectbox("Sınıflandırma",["GENERAL","INTERNAL","CONFIDENTIAL","RESTRICTED"]); ret=st.number_input("Saklama Sonu",min_value=0,max_value=2500,value=CURRENT_YEAR+10)
                with c: box=st.text_input("Kutu No"); shelf=st.text_input("Yer / Raf"); loc=st.text_input("Fiziksel Konum")
                pdflag=st.checkbox("Kişisel veri içeriyor"); special=st.checkbox("Özel nitelikli kişisel veri içeriyor")
                if st.form_submit_button("Kaydı oluştur",type="primary"):
                    if not reg.strip() or not name.strip() or not unit.strip(): st.error("Zorunlu alanları doldurun.")
                    elif not in_scope(user,unit.strip()): st.error("Birim kapsamınız dışında kayıt oluşturamazsınız.")
                    else:
                        conn=get_db(); now=iso_now(); conn.execute("INSERT INTO aygaz_main_archive(doc_reg_no,doc_no,doc_name,series_code,unit_code,box_no,shelf_no,physical_location,institution,status,destruction_status,retention_end_year,classification,personal_data,special_category_data,owner_unit,metadata_complete,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(reg.strip(),doc.strip(),name.strip(),ser.strip(),unit.strip(),box.strip(),shelf.strip(),loc.strip(),"AYGAZ A.Ş.","Depoda","BEKLİYOR",int(ret),cls,int(pdflag),int(special),unit.strip(),1,now,now,user["username"],user["username"])); new_id=conn.execute("SELECT last_insert_rowid()").fetchone()[0]; conn.commit(); conn.close(); audit(user["username"],"ARCHIVE_CREATE","SUCCESS","ARCHIVE",str(new_id)); st.success("Kayıt oluşturuldu."); st.rerun()

# ========================= REQUESTS =========================
elif menu=="Erişim Talepleri":
    header("Erişim ve zimmet talepleri","Fiziksel belge hareketini talep → teslim → iade zinciriyle izleyin.",menu,user)
    t1,t2=st.tabs(["Yeni Talep","Taleplerim / Kuyruk"])
    with t1:
        if has_perm(user,"REQUEST_CREATE"):
            with st.form("request_form"):
                doc_item=st.text_input("Kayıt No / Belge")
                c1,c2,c3=st.columns(3)
                with c1: delivery=st.selectbox("Teslim tipi",["Fiziksel teslim","Dijital erişim","Okuma salonu"])
                with c2: urgency=st.selectbox("Öncelik",["Normal","Acil","Kritik"])
                with c3: due=st.date_input("İade hedef tarihi",value=date.today()+timedelta(days=7))
                notes=st.text_area("Gerekçe")
                if st.form_submit_button("Talep oluştur",type="primary"):
                    req=next_req_no(); conn=get_db(); conn.execute("INSERT INTO archive_requests(req_no,requester,unit_code,doc_item,delivery_type,urgency,status,notes,created_at,due_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(req,user["username"],user["unit_code"],doc_item,delivery,urgency,"AÇIK",notes,iso_now(),due.isoformat())); conn.commit(); conn.close(); audit(user["username"],"REQUEST_CREATE","SUCCESS","REQUEST",req); st.success(f"Talep oluşturuldu: {req}")
    with t2:
        if has_perm(user,"REQUEST_MANAGE"):
            q="SELECT id,req_no AS [Talep],requester AS [Talep Sahibi],unit_code AS [Birim],doc_item AS [Belge],delivery_type AS [Teslim],urgency AS [Öncelik],status AS [Durum],created_at AS [Oluşturulma],due_at AS [İade Hedefi] FROM archive_requests WHERE 1=1"; p=[]
            if user.get("unit_code")!="ALL": q+=" AND unit_code=?"; p.append(user["unit_code"])
        else:
            q="SELECT id,req_no AS [Talep],requester AS [Talep Sahibi],unit_code AS [Birim],doc_item AS [Belge],delivery_type AS [Teslim],urgency AS [Öncelik],status AS [Durum],created_at AS [Oluşturulma],due_at AS [İade Hedefi] FROM archive_requests WHERE requester=?"; p=[user["username"]]
        q+=" ORDER BY id DESC"; reqdf=query_df(q,tuple(p)); st.dataframe(reqdf.drop(columns=["id"],errors="ignore"),use_container_width=True,hide_index=True)
        if has_perm(user,"REQUEST_MANAGE") and not reqdf.empty:
            rid=st.selectbox("Talep seç",reqdf["id"].tolist()); new_status=st.selectbox("Yeni durum",["AÇIK","ONAYLANDI","TESLİM EDİLDİ","İADE BEKLENİYOR","TAMAMLANDI","İPTAL"]); note=st.text_input("İşlem notu")
            if st.button("Talebi güncelle",type="primary"):
                conn=get_db(); conn.execute("UPDATE archive_requests SET status=?,approved_by=CASE WHEN ?='ONAYLANDI' THEN ? ELSE approved_by END,delivered_at=CASE WHEN ?='TESLİM EDİLDİ' THEN ? ELSE delivered_at END,returned_at=CASE WHEN ?='TAMAMLANDI' THEN ? ELSE returned_at END,closed_at=CASE WHEN ? IN ('TAMAMLANDI','İPTAL') THEN ? ELSE closed_at END WHERE id=?",(new_status,new_status,user["username"],new_status,iso_now(),new_status,iso_now(),new_status,iso_now(),int(rid))); conn.commit(); conn.close(); audit(user["username"],"REQUEST_UPDATE","SUCCESS","REQUEST",str(rid),new={"status":new_status,"note":note}); st.success("Talep güncellendi."); st.rerun()

# ========================= DOCUMENT MANAGEMENT =========================
elif menu=="Belge Yönetimi":
    header("Belge ve bütünlük yönetimi","Dosya sürümü, SHA-256 bütünlüğü, OCR alanı, e-imza durumu ve erişim kayıtlarını yönetin.",menu,user)
    files=query_df("SELECT f.id,f.original_name AS [Dosya],a.doc_reg_no AS [Kayıt],f.mime_type AS [Tür],f.size_bytes AS [Boyut],f.sha256 AS [SHA-256],f.version_no AS [Sürüm],f.ocr_status AS [OCR],f.signature_status AS [İmza],f.integrity_status AS [Bütünlük],f.uploaded_at AS [Yükleyen Tarih],f.uploaded_by AS [Yükleyen] FROM archive_files f JOIN aygaz_main_archive a ON a.id=f.archive_id WHERE 1=1"+(" AND a.unit_code=?" if user.get("unit_code")!="ALL" else "")+" ORDER BY f.id DESC LIMIT 500",(() if user.get("unit_code")=="ALL" else (user["unit_code"],)))
    st.dataframe(files,use_container_width=True,hide_index=True,height=520)
    st.markdown('<div class="warning"><b>Üretim notu:</b> Gerçek üretimde dosya binary verileri kurumsal nesne depolama/DMS üzerinde tutulmalı; uygulama veritabanında yalnızca metadata, hash, sürüm ve erişim referansı tutulmalıdır.</div>',unsafe_allow_html=True)

# ========================= DESTRUCTION =========================
elif menu=="Saklama ve İmha":
    header("Saklama ve imha yönetimi","Saklama planı, legal hold ve görevler ayrılığı kontrolleriyle imha yönetin.",menu,user)
    t1,t2,t3=st.tabs(["Adaylar","İş Akışı","Tamamlanan İmhâlar"])
    with t1:
        cand=query_df("SELECT a.id AS ID,a.doc_reg_no AS [Kayıt],a.doc_name AS [Belge],a.unit_code AS [Birim],a.retention_end_year AS [Saklama Sonu],a.classification AS [Sınıf],a.legal_hold_count AS [Hold],a.destruction_status AS [Durum] FROM aygaz_main_archive a WHERE a.retention_end_year<=? AND a.destruction_status!='İMHA EDİLDİ' AND a.legal_hold_count=0"+(" AND a.unit_code=?" if user.get("unit_code")!="ALL" else ""),(CURRENT_YEAR,) if user.get("unit_code")=="ALL" else (CURRENT_YEAR,user["unit_code"]))
        st.dataframe(cand.drop(columns=["ID"],errors="ignore"),use_container_width=True,hide_index=True)
        if has_perm(user,"DESTRUCTION_REQUEST") and not cand.empty:
            rid=st.selectbox("İmha talebi açılacak kayıt",cand["ID"].tolist()); reason=st.text_area("İmha gerekçesi / dayanak",placeholder="Saklama süresi doldu, legal hold kontrolü yapıldı...")
            if st.button("İmha talebi oluştur",type="primary"):
                ok,msg=request_destruction(int(rid),user,reason); st.success(msg) if ok else st.error(msg)
    with t2:
        wf=query_df("SELECT w.id AS ID,w.archive_id AS [Kayıt ID],a.doc_reg_no AS [Kayıt],a.doc_name AS [Belge],w.stage AS [Aşama],w.requested_by AS [Talep],w.reviewed_by AS [İnceleyen],w.approved_by AS [Onaylayan],w.executed_by AS [Uygulayan],w.requested_at AS [Talep Tarihi],w.certificate_no AS [Tutanak] FROM destruction_workflows w JOIN aygaz_main_archive a ON a.id=w.archive_id WHERE w.stage NOT IN ('TAMAMLANDI','RED') ORDER BY w.id DESC")
        st.dataframe(wf.drop(columns=["ID"],errors="ignore"),use_container_width=True,hide_index=True)
        if not wf.empty:
            wid=st.selectbox("İş akışı",wf["ID"].tolist()); selected=wf[wf.ID==wid].iloc[0]; note=st.text_input("İnceleme notu")
            if selected.Aşama=="TALEP" and has_perm(user,"DESTRUCTION_REVIEW"):
                x,y=st.columns(2)
                with x:
                    if st.button("İmha incelemesini onayla",type="primary"):
                        ok,msg=review_destruction(int(wid),user,True,note); st.success(msg) if ok else st.error(msg); st.rerun()
                with y:
                    if st.button("İmha talebini reddet"):
                        ok,msg=review_destruction(int(wid),user,False,note); st.success(msg) if ok else st.error(msg); st.rerun()
            if selected.Aşama=="ONAY" and has_perm(user,"DESTRUCTION_EXECUTE"):
                method=st.selectbox("İmha yöntemi",["Güvenli fiziksel imha","Kurumsal DMS güvenli silme","Yetkili veri imha hizmeti"]); cert=st.text_input("İmha tutanak / sertifika no")
                if st.button("İmhayı tamamla",type="primary"):
                    ok,msg=execute_destruction(int(wid),user,method,cert); st.success(msg) if ok else st.error(msg); st.rerun()
    with t3:
        done=query_df("SELECT a.doc_reg_no AS [Kayıt],a.doc_name AS [Belge],a.destruction_date AS [İmha Zamanı],w.certificate_no AS [Tutanak],w.method AS [Yöntem],w.executed_by AS [Uygulayan] FROM destruction_workflows w JOIN aygaz_main_archive a ON a.id=w.archive_id WHERE w.stage='TAMAMLANDI' ORDER BY w.id DESC")
        st.dataframe(done,use_container_width=True,hide_index=True); export_excel(done,"aygaz-imha-tutanaklari.xlsx","İmha Tutanakları")

# ========================= LEGAL HOLD =========================
elif menu=="Legal Hold":
    header("Legal Hold","Dava, inceleme, soruşturma, denetim veya başka bir koruma gerektiren kayıtları imha sürecinden çıkarın.",menu,user)
    active=query_df("SELECT h.id AS ID,h.hold_ref AS [Hold],a.doc_reg_no AS [Kayıt],a.doc_name AS [Belge],h.reason AS [Gerekçe],h.authority AS [Makam],h.start_date AS [Başlangıç],h.end_date AS [Bitiş],h.created_by AS [Oluşturan] FROM legal_holds h JOIN aygaz_main_archive a ON a.id=h.archive_id WHERE h.active=1 ORDER BY h.id DESC")
    st.dataframe(active.drop(columns=["ID"],errors="ignore"),use_container_width=True,hide_index=True)
    if has_perm(user,"LEGAL_HOLD"):
        with st.expander("Yeni legal hold"):
            rid=st.number_input("Arşiv kayıt ID",min_value=1,step=1); reason=st.text_area("Gerekçe"); authority=st.text_input("Yetkili makam / dosya referansı"); end=st.date_input("Planlanan bitiş",value=date.today()+timedelta(days=365))
            if st.button("Legal hold başlat",type="primary"):
                ok,msg=add_legal_hold(int(rid),user,reason,authority,end.isoformat()); st.success(msg) if ok else st.error(msg)
        if not active.empty:
            hid=st.selectbox("Kaldırılacak hold",active.ID.tolist())
            if st.button("Legal hold kaldır"):
                ok,msg=release_legal_hold(int(hid),user); st.success(msg) if ok else st.error(msg); st.rerun()

# ========================= AUDIT =========================
elif menu=="Denetim İzi":
    header("Denetim izi","Kullanıcı ve sistem işlemlerinin değiştirilemez zincirlenmiş olay kaydı.",menu,user)
    df=query_df("SELECT event_id AS [Olay ID],timestamp AS [Zaman],username AS [Kullanıcı],action_type AS [İşlem],object_type AS [Nesne],object_id AS [Nesne ID],result AS [Sonuç],reason AS [Gerekçe],event_hash AS [Hash] FROM audit_log ORDER BY id DESC LIMIT 1000")
    st.dataframe(df,use_container_width=True,hide_index=True,height=560); export_excel(df,"aygaz-denetim-izi.xlsx","Denetim İzi")
    st.markdown('<div class="successbox">Audit olayları bir önceki olayın hash değeriyle zincirlenir. Bu, uygulama seviyesinde bütünlük kontrolü sağlar; gerçek üretimde ayrıca merkezi log/SIEM ve değiştirilemez log depolama kullanılmalıdır.</div>',unsafe_allow_html=True)

# ========================= SECURITY CENTER =========================
elif menu=="Güvenlik Merkezi":
    header("Güvenlik merkezi","Kimlik, erişim, loglama, veri koruma ve altyapı kontrollerini izleyin.",menu,user)
    c=st.columns(4)
    checks=[
        ("SSO", "AKTİF" if ENVIRONMENT=="PROD" else "DEMO MODU"),
        ("Audit zinciri", "AKTİF"),
        ("Dosya hash", "SHA-256"),
        ("SIEM", "BAĞLI" if SIEM_WEBHOOK else "YAPILANDIRILMADI")]
    for col,(label,val) in zip(c,checks):
        with col: st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value" style="font-size:18px">{val}</div><div class="metric-note">altyapı kontrolü</div></div>',unsafe_allow_html=True)
    st.markdown("### Açık güvenlik olayları")
    sec=query_df("SELECT timestamp AS Zaman,username AS Kullanıcı,event_type AS Olay,severity AS Seviye,details AS Detay FROM security_events WHERE resolved=0 ORDER BY id DESC LIMIT 200")
    st.dataframe(sec,use_container_width=True,hide_index=True)
    st.markdown("### Konfigürasyon kontrol listesi")
    checks_df=pd.DataFrame([
        ["Kurumsal SSO / MFA",ENVIRONMENT=="PROD","Reverse proxy/IAM üzerinde doğrulanmalı"],
        ["Enterprise DB",ENVIRONMENT=="PROD" and not str(DB_PATH).endswith(".db"),"PostgreSQL/SQL Server kurumsal mimariye göre"],
        ["WAF / TLS",ENVIRONMENT=="PROD","Uygulama önünde zorunlu"],
        ["Merkezi SIEM",bool(SIEM_WEBHOOK),"Aygaz SIEM entegrasyonu yapılandırılmalı"],
        ["Yedekleme / DR",False,"RPO/RTO ve geri dönüş testi altyapı tarafından işletilmeli"],
        ["Immutable object storage",False,"Dosya deposu kurumsal DMS/object storage olmalı"],
        ["KVKK envanteri",False,"Veri işleme envanteri ve saklama politikasıyla eşleştirilmeli"],
        ["Penetrasyon testi",False,"Canlıya geçiş öncesi bağımsız test"],
    ],columns=["Kontrol","Uygulama Durumu","Not"])
    st.dataframe(checks_df,use_container_width=True,hide_index=True)

# ========================= ADMIN =========================
elif menu=="Tanımlar ve Yönetim":
    header("Tanımlar ve yönetim","Roller, kullanıcılar, dosya planı ve saklama planı için merkezi yönetim ekranı.",menu,user)
    tabs=st.tabs(["Kullanıcılar","Roller","Saklama Planı","Birimler / Seriler"])
    with tabs[0]:
        udf=query_df("SELECT username AS Kullanıcı,full_name AS [Ad Soyad],unit_code AS Birim,role_code AS Rol,active AS Aktif,last_login_at AS [Son Giriş] FROM users ORDER BY id"); st.dataframe(udf,use_container_width=True,hide_index=True)
        with st.expander("Kullanıcı ekle"):
            with st.form("add_user"):
                a,b,c=st.columns(3)
                with a: un=st.text_input("Kullanıcı adı"); fn=st.text_input("Ad Soyad")
                with b: uc=st.text_input("Birim"); rc=st.selectbox("Rol",query_df("SELECT role_code FROM roles ORDER BY role_code")["role_code"].tolist())
                with c: active=st.checkbox("Aktif",value=True)
                if st.form_submit_button("Kaydet"):
                    conn=get_db(); conn.execute("INSERT INTO users(username,full_name,unit_code,role_code,active) VALUES(?,?,?,?,?)",(un.strip(),fn.strip(),uc.strip() or "ALL",rc,int(active))); conn.commit(); conn.close(); audit(user["username"],"USER_CREATE","SUCCESS","USER",un.strip()); st.rerun()
    with tabs[1]:
        rdf=query_df("SELECT role_code AS Rol,role_name AS [Rol Adı],permissions AS Yetkiler FROM roles ORDER BY role_code"); st.dataframe(rdf,use_container_width=True,hide_index=True)
    with tabs[2]:
        sdf=query_df("SELECT series_code AS [Seri],document_type AS [Belge Türü],retention_years AS [Yıl],trigger_event AS [Başlatıcı Olay],legal_basis AS [Hukuki Dayanak],disposition AS [Tasfiye],confidentiality AS [Sınıf] FROM retention_schedule ORDER BY series_code"); st.dataframe(sdf,use_container_width=True,hide_index=True); st.warning("Saklama süreleri örnek/demo değerler içerir. Canlı kullanım öncesinde Aygaz Hukuk, KVKK, ilgili iş birimi ve arşiv politikasıyla doğrulanmalıdır.")
    with tabs[3]:
        units=query_df("SELECT code AS Kod,name AS Birim,inst_name AS Şirket,active AS Aktif FROM units ORDER BY code"); series=query_df("SELECT series_code AS [Seri],name AS [Seri Adı],unit_code AS Birim,retention_year AS [Yıl],legal_basis AS [Dayanak] FROM series ORDER BY series_code"); st.dataframe(units,use_container_width=True,hide_index=True); st.dataframe(series,use_container_width=True,hide_index=True)

# Global no-op footer
st.markdown(f'<div style="text-align:center;color:#94a3b8;font-size:10px;margin:35px 0 10px">{APP_NAME} · {APP_VERSION} · {ENVIRONMENT}</div>',unsafe_allow_html=True)
