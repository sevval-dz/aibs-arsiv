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

APP_NAME = "Aygaz Arşiv Sistemi"
APP_VERSION = "2.0.0-enterprise-reference"

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = Path(
    os.getenv(
        "AIBS_DB_PATH",
        BASE_DIR / "aibs_database.db"
    )
)

DOCUMENT_ROOT = Path(
    os.getenv(
        "AIBS_DOCUMENT_ROOT",
        BASE_DIR / "secure_documents"
    )
)

DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)

ENVIRONMENT = os.getenv("AIBS_ENV", "DEMO").upper()

SSO_HEADER = os.getenv(
    "AIBS_SSO_HEADER",
    "X-Authenticated-User"
)

SSO_NAME_HEADER = os.getenv(
    "AIBS_SSO_NAME_HEADER",
    "X-Authenticated-Name"
)

SIEM_WEBHOOK = os.getenv(
    "AIBS_SIEM_WEBHOOK_URL",
    ""
).strip()

MAX_UPLOAD_MB = int(
    os.getenv(
        "AIBS_MAX_UPLOAD_MB",
        "25"
    )
)

ALLOWED_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "csv",
    "txt",
    "jpg",
    "jpeg",
    "png",
    "tif",
    "tiff",
}

ALLOWED_MIME = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "text/plain",
    "image/jpeg",
    "image/png",
    "image/tiff",
}

TR_TZ = timezone(timedelta(hours=3))

TR_MONTHS = {
    1: "Oca",
    2: "Şub",
    3: "Mar",
    4: "Nis",
    5: "May",
    6: "Haz",
    7: "Tem",
    8: "Ağu",
    9: "Eyl",
    10: "Eki",
    11: "Kas",
    12: "Ara",
}

CURRENT_YEAR = datetime.now(TR_TZ).year


def now_tr() -> datetime:
    return datetime.now(TR_TZ)


def iso_now() -> str:
    return now_tr().isoformat(timespec="seconds")


def fmt_dt(value: str | None) -> str:
    if not value:
        return "-"

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).astimezone(TR_TZ)

        return (
            f"{dt.day:02d} "
            f"{TR_MONTHS[dt.month]} "
            f"{dt.year} · "
            f"{dt:%H:%M}"
        )

    except Exception:
        return str(value)


def clean(value: Any, max_len: int = 500) -> str:
    return str(
        value if value is not None else ""
    ).strip()[:max_len]


def normalize_codes(value: Any) -> set[str]:
    return {
        x.strip().upper()
        for x in str(value or "").split(",")
        if x.strip()
    }


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    conn.execute(
        "PRAGMA journal_mode = WAL"
    )

    conn.execute(
        "PRAGMA synchronous = NORMAL"
    )

    return conn


def column_names(
    conn: sqlite3.Connection,
    table: str
) -> set[str]:

    return {
        row[1]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def ensure_column(
    conn: sqlite3.Connection,
    table: str,
    name: str,
    definition: str
) -> None:

    if name not in column_names(conn, table):
        conn.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN {name} {definition}"
        )


def init_database() -> None:

    conn = get_db()

    try:

        # =====================================================
        # TABLES
        # =====================================================

        conn.executescript(
            """
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
                trigger_event TEXT DEFAULT 'Dosyanın kapanışı',
                disposition TEXT DEFAULT 'İMHA',
                confidentiality TEXT DEFAULT 'INTERNAL',
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                unit_code TEXT NOT NULL DEFAULT 'ALL',
                role_code TEXT NOT NULL DEFAULT 'ARCHIVE_USER',
                active INTEGER DEFAULT 1,
                external_id TEXT,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS roles (
                role_code TEXT PRIMARY KEY,
                role_name TEXT NOT NULL,
                permissions TEXT NOT NULL
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
                retention_end_year INTEGER,
                classification TEXT DEFAULT 'INTERNAL',
                personal_data INTEGER DEFAULT 0,
                special_category_data INTEGER DEFAULT 0,
                retention_trigger TEXT,
                legal_basis TEXT,
                owner_unit TEXT,
                current_holder TEXT,
                physical_location TEXT,
                metadata_complete INTEGER DEFAULT 0,
                legal_hold_count INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                created_by TEXT,
                updated_by TEXT
            );

            CREATE TABLE IF NOT EXISTS archive_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archive_id INTEGER NOT NULL,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL UNIQUE,
                mime_type TEXT,
                size_bytes INTEGER,
                sha256 TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                uploaded_by TEXT NOT NULL,
                version_no INTEGER DEFAULT 1,
                ocr_status TEXT DEFAULT 'BEKLEMEDE',
                ocr_text TEXT,
                signature_status TEXT DEFAULT 'YOK',
                integrity_status TEXT DEFAULT 'DOĞRULANMADI',
                FOREIGN KEY(archive_id)
                    REFERENCES aygaz_main_archive(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS archive_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archive_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                action TEXT NOT NULL,
                result TEXT NOT NULL,
                reason TEXT,
                timestamp TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY(archive_id)
                    REFERENCES aygaz_main_archive(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS archive_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                req_no TEXT NOT NULL UNIQUE,
                requester TEXT NOT NULL,
                unit_code TEXT NOT NULL,
                doc_item TEXT NOT NULL,
                delivery_type TEXT NOT NULL,
                urgency TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'AÇIK',
                notes TEXT,
                created_at TEXT NOT NULL,
                due_at TEXT,
                closed_at TEXT,
                approved_by TEXT,
                delivered_at TEXT,
                returned_at TEXT
            );

            CREATE TABLE IF NOT EXISTS request_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                req_no TEXT NOT NULL,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS custody_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archive_id INTEGER NOT NULL,
                request_id INTEGER,
                event_type TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                actor TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                due_at TEXT,
                note TEXT,
                FOREIGN KEY(archive_id)
                    REFERENCES aygaz_main_archive(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS legal_holds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archive_id INTEGER NOT NULL,
                hold_ref TEXT NOT NULL UNIQUE,
                reason TEXT NOT NULL,
                authority TEXT,
                start_date TEXT NOT NULL,
                end_date TEXT,
                active INTEGER DEFAULT 1,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                released_by TEXT,
                released_at TEXT,
                FOREIGN KEY(archive_id)
                    REFERENCES aygaz_main_archive(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS destruction_workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archive_id INTEGER NOT NULL,
                stage TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                reviewed_by TEXT,
                reviewed_at TEXT,
                approved_by TEXT,
                approved_at TEXT,
                executed_by TEXT,
                executed_at TEXT,
                certificate_no TEXT,
                method TEXT,
                notes TEXT,
                FOREIGN KEY(archive_id)
                    REFERENCES aygaz_main_archive(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS retention_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_code TEXT NOT NULL UNIQUE,
                document_type TEXT NOT NULL,
                retention_years INTEGER,
                trigger_event TEXT NOT NULL,
                legal_basis TEXT,
                disposition TEXT NOT NULL DEFAULT 'İMHA',
                confidentiality TEXT NOT NULL DEFAULT 'INTERNAL',
                kvkk_category TEXT,
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                timestamp TEXT NOT NULL,
                username TEXT NOT NULL,
                action_type TEXT NOT NULL,
                object_type TEXT,
                object_id TEXT,
                result TEXT NOT NULL,
                reason TEXT,
                old_value TEXT,
                new_value TEXT,
                ip_address TEXT,
                user_agent TEXT,
                correlation_id TEXT NOT NULL,
                previous_hash TEXT,
                event_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                username TEXT,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                details TEXT,
                resolved INTEGER DEFAULT 0
            );
            """
        )

        # =====================================================
        # BACKWARD COMPATIBILITY / MIGRATION
        # =====================================================

        ensure_column(
            conn,
            "aygaz_main_archive",
            "classification",
            "TEXT DEFAULT 'INTERNAL'"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "personal_data",
            "INTEGER DEFAULT 0"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "special_category_data",
            "INTEGER DEFAULT 0"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "retention_trigger",
            "TEXT"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "legal_basis",
            "TEXT"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "owner_unit",
            "TEXT"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "current_holder",
            "TEXT"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "physical_location",
            "TEXT"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "metadata_complete",
            "INTEGER DEFAULT 0"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "legal_hold_count",
            "INTEGER DEFAULT 0"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "created_at",
            "TEXT"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "updated_at",
            "TEXT"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "created_by",
            "TEXT"
        )

        ensure_column(
            conn,
            "aygaz_main_archive",
            "updated_by",
            "TEXT"
        )

        # =====================================================
        # IMPORTANT:
        # INDEXES ARE CREATED ONLY AFTER MIGRATION.
        # This prevents an old SQLite database from failing
        # because an index references a newly-added column.
        # =====================================================

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_archive_unit_series
            ON aygaz_main_archive(unit_code, series_code)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_archive_retention
            ON aygaz_main_archive(
                retention_end_year,
                destruction_status
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_archive_classification
            ON aygaz_main_archive(classification)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_requests_status
            ON archive_requests(status, unit_code)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_audit_time
            ON audit_log(timestamp)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_access_time
            ON archive_access(timestamp)
            """
        )

        # =====================================================
        # SEED DATA
        # =====================================================

        conn.executemany(
            """
            INSERT OR IGNORE
            INTO institutions(id,name,code)
            VALUES(?,?,?)
            """,
            [
                (
                    1,
                    "AYGAZ A.Ş.",
                    "10"
                ),
                (
                    11,
                    "ZİNERJİ A.Ş.",
                    "40"
                ),
                (
                    12,
                    "ANADOLU HİSARI TANKERCİLİK",
                    "30"
                ),
                (
                    13,
                    "AYGAZ DOĞALGAZ",
                    "20"
                ),
                (
                    15,
                    "AKPA A.Ş.",
                    "50"
                ),
                (
                    17,
                    "GAZAL A.Ş.",
                    "60"
                ),
            ]
        )

        conn.executemany(
            """
            INSERT OR IGNORE
            INTO units(
                id,
                name,
                code,
                inst_code,
                inst_name
            )
            VALUES(?,?,?,?,?)
            """,
            [
                (
                    1,
                    "TANIMSIZ",
                    "0",
                    "10",
                    "AYGAZ A.Ş."
                ),
                (
                    2,
                    "BİLGİ SİSTEM MÜDÜRLÜĞÜ",
                    "1001",
                    "10",
                    "AYGAZ A.Ş."
                ),
                (
                    3,
                    "BÜTÇE PLANLAMA VE KONTROL MÜDÜRLÜĞÜ",
                    "1002",
                    "10",
                    "AYGAZ A.Ş."
                ),
                (
                    4,
                    "FİNANSMAN MÜDÜRLÜĞÜ",
                    "1003",
                    "10",
                    "AYGAZ A.Ş."
                ),
                (
                    5,
                    "MUHASEBE MÜDÜRLÜĞÜ",
                    "1004",
                    "10",
                    "AYGAZ A.Ş."
                ),
                (
                    6,
                    "BAYİ GELİŞTİRME MÜDÜRLÜĞÜ",
                    "1005",
                    "10",
                    "AYGAZ A.Ş."
                ),
                (
                    7,
                    "İNSAN KAYNAKLARI MÜDÜRLÜĞÜ",
                    "1006",
                    "10",
                    "AYGAZ A.Ş."
                ),
                (
                    8,
                    "GEMİ İŞLETME MÜDÜRLÜĞÜ",
                    "1007",
                    "10",
                    "AYGAZ A.Ş."
                ),
                (
                    9,
                    "İŞLETME MÜHENDİSLİK YATIRIMLAR MÜDÜRLÜĞÜ",
                    "1008",
                    "10",
                    "AYGAZ A.Ş."
                ),
            ]
        )

        conn.executemany(
            """
            INSERT OR IGNORE
            INTO series(
                id,
                name,
                unit_code,
                unit_name,
                series_code,
                retention_year,
                legal_basis,
                trigger_event,
                disposition,
                confidentiality
            )
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    1,
                    "PERSONEL ÖZLÜK DOSYALARI",
                    "1006",
                    "İNSAN KAYNAKLARI MÜDÜRLÜĞÜ",
                    "1",
                    10,
                    "İş Kanunu Md. 75",
                    "İş ilişkisinin sona ermesi / kurum politikasıyla doğrulanacak süre",
                    "İMHA",
                    "RESTRICTED",
                ),
                (
                    3,
                    "MAKBUZ VE TAHSİLAT BELGELERİ",
                    "1004",
                    "MUHASEBE MÜDÜRLÜĞÜ",
                    "3",
                    10,
                    "VUK Md. 253",
                    "Belgenin düzenlenmesi / yasal sürenin başlangıcı doğrulanmalı",
                    "İMHA",
                    "CONFIDENTIAL",
                ),
                (
                    4,
                    "MAHSUP VE YEVMİYE FİŞLERİ",
                    "1004",
                    "MUHASEBE MÜDÜRLÜĞÜ",
                    "4",
                    10,
                    "TTK Md. 82",
                    "İlgili hesap döneminin kapanışı",
                    "İMHA",
                    "CONFIDENTIAL",
                ),
                (
                    9,
                    "TİCARİ BAYİLİK VE MÜLKİYET SÖZLEŞMELERİ",
                    "1004",
                    "MUHASEBE MÜDÜRLÜĞÜ",
                    "9",
                    100,
                    "Kurum hukuk politikasıyla doğrulanmalı",
                    "Sözleşmenin sona ermesi / uyuşmazlık yokluğu",
                    "İMHA",
                    "CONFIDENTIAL",
                ),
                (
                    11,
                    "İŞ SAĞLIĞI VE AMBARLI TEFTİŞ RAPORLARI",
                    "1008",
                    "İŞLETME MÜHENDİSLİK YATIRIMLAR MÜDÜRLÜĞÜ",
                    "11",
                    15,
                    "6331 sayılı mevzuatla birlikte Aygaz Hukuk/İSG politikası doğrulanmalı",
                    "Raporun kapanışı",
                    "İMHA",
                    "CONFIDENTIAL",
                ),
            ]
        )

        conn.executemany(
            """
            INSERT OR IGNORE
            INTO roles(
                role_code,
                role_name,
                permissions
            )
            VALUES(?,?,?)
            """,
            [
                (
                    "ARCHIVE_ADMIN",
                    "Arşiv Yöneticisi",
                    "ARCHIVE_READ,ARCHIVE_CREATE,ARCHIVE_EDIT,REQUEST_MANAGE,DESTRUCTION_REQUEST,DESTRUCTION_REVIEW,DESTRUCTION_APPROVE,DESTRUCTION_EXECUTE,LEGAL_HOLD,AUDIT_VIEW,USER_ADMIN,EXPORT",
                ),
                (
                    "ARCHIVE_OFFICER",
                    "Arşiv Görevlisi",
                    "ARCHIVE_READ,ARCHIVE_CREATE,ARCHIVE_EDIT,REQUEST_MANAGE,DESTRUCTION_REQUEST,LEGAL_HOLD,EXPORT",
                ),
                (
                    "ARCHIVE_AUDITOR",
                    "Denetim",
                    "ARCHIVE_READ,AUDIT_VIEW,EXPORT",
                ),
                (
                    "ARCHIVE_USER",
                    "Birim Kullanıcısı",
                    "ARCHIVE_READ,REQUEST_CREATE,REQUEST_VIEW",
                ),
                (
                    "DESTRUCTION_REVIEWER",
                    "İmha İnceleme",
                    "ARCHIVE_READ,DESTRUCTION_REQUEST,DESTRUCTION_REVIEW,LEGAL_HOLD,AUDIT_VIEW",
                ),
                (
                    "DESTRUCTION_EXECUTOR",
                    "İmha Uygulama",
                    "ARCHIVE_READ,DESTRUCTION_EXECUTE,AUDIT_VIEW",
                ),
            ]
        )

        if conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0] == 0:

            conn.execute(
                """
                INSERT INTO users(
                    username,
                    full_name,
                    unit_code,
                    role_code,
                    active
                )
                VALUES(?,?,?,?,1)
                """,
                (
                    "local\\admin",
                    "Arşiv Yöneticisi",
                    "ALL",
                    "ARCHIVE_ADMIN",
                )
            )

        if conn.execute(
            "SELECT COUNT(*) FROM aygaz_main_archive"
        ).fetchone()[0] == 0:

            seed = [
                (
                    "90101",
                    "1411-23-201",
                    "Bayi faaliyet raporları",
                    "6",
                    "1004",
                    "01/08/2023",
                    "31/08/2023",
                    "23050",
                    "H11.211",
                    "AYGAZ",
                    "Depoda",
                    "BEKLİYOR",
                    None,
                    2028,
                    "INTERNAL",
                    0,
                    0,
                    "Dosyanın kapanışı",
                    "Kurum politikasıyla doğrulanmalı",
                    "1004",
                    "",
                    "H11 / 211",
                    0,
                    0,
                    iso_now(),
                    iso_now(),
                    "local\\admin",
                    "local\\admin",
                ),
                (
                    "90102",
                    "1411-23-202",
                    "Ticari bayilik sözleşmeleri",
                    "9",
                    "1004",
                    "01/08/2023",
                    "31/08/2023",
                    "23051",
                    "H11.212",
                    "AYGAZ",
                    "Zimmette",
                    "BEKLİYOR",
                    None,
                    2123,
                    "CONFIDENTIAL",
                    0,
                    0,
                    "Sözleşmenin sona ermesi",
                    "Kurum hukuk politikasıyla doğrulanmalı",
                    "1004",
                    "Kullanıcı",
                    "H11 / 212",
                    0,
                    0,
                    iso_now(),
                    iso_now(),
                    "local\\admin",
                    "local\\admin",
                ),
                (
                    "90085",
                    "1205-22
