from datetime import datetime
import base64
import io
import os
from pathlib import Path
import sqlite3
import uuid
from xml.sax.saxutils import escape
import zipfile

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Aygaz Arşiv Sistemi",
    page_icon="Aygaz.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_PATH = Path(__file__).resolve().with_name("aibs_database.db")

CURRENT_YEAR = datetime.now().year

st.markdown("""
<style>
/* 1. TÜM BUTONLAR (Mavi zemin, beyaz yazı - sabit) */
div.stButton, div[data-testid="stButton"], 
div.stDownloadButton, div[data-testid="stDownloadButton"],
div.stFormSubmitButton, div[data-testid="stFormSubmitButton"] {
    background: transparent !important;
    padding: 0px !important;
    border: none !important;
    box-shadow: none !important;
}

div.stButton > button,
div[data-testid="stButton"] > button,
div.stDownloadButton > button,
div[data-testid="stDownloadButton"] > button,
div.stFormSubmitButton > button,
div[data-testid="stFormSubmitButton"] > button,
button[data-testid^="baseButton"] {
    background-color: #005691 !important;
    background: #005691 !important;
    border: none !important;
    outline: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    box-shadow: none !important;
}

div.stButton > button *,
div[data-testid="stButton"] > button *,
div.stDownloadButton > button *,
div[data-testid="stDownloadButton"] > button *,
div.stFormSubmitButton > button *,
div[data-testid="stFormSubmitButton"] > button *,
button[data-testid^="baseButton"] * {
    color: #ffffff !important;
    -webkit-text-fill-color: #ffffff !important;
}

div.stButton > button:hover,
div[data-testid="stButton"] > button:hover,
div.stDownloadButton > button:hover,
div[data-testid="stDownloadButton"] > button:hover,
div.stFormSubmitButton > button:hover,
div[data-testid="stFormSubmitButton"] > button:hover,
button[data-testid^="baseButton"]:hover {
    background-color: #004070 !important;
    background: #004070 !important;
}

/* 2. KULLANICI KUTUSU & GİRDİ ALANLARI (Beyaz zemin, SİYAH yazı, görünür ok) */
div[data-baseweb="select"] > div,
div[data-testid="stTextInput"] > div > div {
    background-color: #ffffff !important;
    border-radius: 6px !important;
}

/* Kutunun içindeki ismi kesin olarak SİYAH yap */
div[data-baseweb="select"] *,
div[data-testid="stSelectbox"] *,
div[data-testid="stTextInput"] input,
input, select, textarea {
    color: #000000 !important;
    -webkit-text-fill-color: #000000 !important;
}

/* Sağdaki açılır oku koru ve siyah yap */
div[data-baseweb="select"] svg,
div[data-testid="stSelectbox"] svg {
    display: block !important;
    visibility: visible !important;
    fill: #000000 !important;
    color: #000000 !important;
}
</style>
""", unsafe_allow_html=True)
def get_db():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def init_database():
    connection = get_db()
    cursor = connection.cursor()
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS institutions (id INTEGER PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS units (id INTEGER PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE, inst_code TEXT, inst_name TEXT);
        CREATE TABLE IF NOT EXISTS series (id INTEGER PRIMARY KEY, name TEXT NOT NULL, unit_code TEXT, unit_name TEXT, series_code TEXT NOT NULL UNIQUE, retention_year INTEGER, legal_basis TEXT);
        CREATE TABLE IF NOT EXISTS user_permissions (id INTEGER PRIMARY KEY, username TEXT, full_name TEXT, unit_code TEXT, auth_codes TEXT, role_desc TEXT);
        CREATE TABLE IF NOT EXISTS aygaz_main_archive (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_reg_no TEXT, doc_no TEXT, doc_name TEXT, series_code TEXT, unit_code TEXT, first_doc_date TEXT, last_doc_date TEXT, box_no TEXT, shelf_no TEXT, institution TEXT, status TEXT, destruction_status TEXT, retention_end_year INTEGER);
        CREATE TABLE IF NOT EXISTS archive_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, req_no TEXT, requester TEXT, unit_code TEXT, doc_item TEXT, delivery_type TEXT, urgency TEXT, status TEXT, notes TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS request_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, req_no TEXT, sender TEXT, message TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS archive_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, user TEXT, action_type TEXT, details TEXT);
        CREATE INDEX IF NOT EXISTS idx_archive_search ON aygaz_main_archive (unit_code, series_code, status);
        CREATE INDEX IF NOT EXISTS idx_archive_retention ON aygaz_main_archive (retention_end_year, destruction_status);
    """)
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
    cursor.executemany("INSERT OR IGNORE INTO series (id, name, unit_code, unit_name, series_code, retention_year, legal_basis) VALUES (?, ?, ?, ?, ?, ?, ?)", [
        (1, "PERSONEL ÖZLÜK DOSYALARI", "1006", "İNSAN KAYNAKLARI MÜDÜRLÜĞÜ", "1", 10, "İş Kanunu Md. 75"),
        (3, "MAKBUZ VE TAHSİLAT BELGELERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "3", 10, "VUK Md. 253"),
        (4, "MAHSUP VE YEVMİYE FİŞLERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "4", 10, "TTK Md. 82"),
        (9, "TİCARİ BAYİLİK VE MÜLKİYET SÖZLEŞMELERİ", "1004", "MUHASEBE MÜDÜRLÜĞÜ", "9", 100, "Süresiz Saklama"),
        (11, "İŞ SAĞLIĞI VE AMBARLI TEFTİŞ RAPORLARI", "1008", "İŞLETME MÜHENDİSLİK YATIRIMLAR MÜDÜRLÜĞÜ", "11", 15, "6331 Sayılı İSGK"),
    ])
    request_columns = {row[1] for row in cursor.execute("PRAGMA table_info(archive_requests)")}
    if "unit_code" not in request_columns:
        cursor.execute("ALTER TABLE archive_requests ADD COLUMN unit_code TEXT")
        if "unit" in request_columns:
            cursor.execute("UPDATE archive_requests SET unit_code = unit WHERE unit_code IS NULL")
    if "notes" not in request_columns:
        cursor.execute("ALTER TABLE archive_requests ADD COLUMN notes TEXT")
        if "description" in request_columns:
            cursor.execute("UPDATE archive_requests SET notes = description WHERE notes IS NULL")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_request_queue ON archive_requests (unit_code, status, created_at)")
    cursor.execute("""
        UPDATE user_permissions
        SET auth_codes = CASE
            WHEN auth_codes IS NULL OR TRIM(auth_codes) = '' THEN 'ADMIN'
            ELSE auth_codes || ',ADMIN'
        END
        WHERE unit_code = 'ALL'
          AND LOWER(role_desc) LIKE '%admin%'
          AND (auth_codes IS NULL OR UPPER(auth_codes) NOT LIKE '%ADMIN%')
    """)
    if cursor.execute("SELECT COUNT(*) FROM user_permissions").fetchone()[0] == 0:
        cursor.execute("INSERT INTO user_permissions VALUES (?, ?, ?, ?, ?, ?)", (1, "local\\admin", "Arşiv Yöneticisi", "ALL", "*", "Yönetici"))
    if cursor.execute("SELECT COUNT(*) FROM aygaz_main_archive").fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO aygaz_main_archive (doc_reg_no, doc_no, doc_name, series_code, unit_code, first_doc_date, last_doc_date, box_no, shelf_no, institution, status, destruction_status, retention_end_year)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            ("90101", "1411-23-201", "Bayi faaliyet raporları", "6", "1004", "01/08/2023", "31/08/2023", "23050", "H11.211", "AYGAZ", "Depoda", "Edilmedi", 2028),
            ("90102", "1411-23-202", "Ticari bayilik sözleşmeleri", "9", "1004", "01/08/2023", "31/08/2023", "23051", "H11.212", "AYGAZ", "Zimmette", "Edilmedi", 2123),
            ("90085", "1205-22-040", "İSG saha denetim raporları", "11", "1008", "10/05/2022", "15/05/2022", "22910", "H10.014", "AYGAZ", "Depoda", "Edilmedi", 2037),
        ])
    connection.commit()
# İmha ve durum sütunları kontrolü
    cursor.execute("PRAGMA table_info(aygaz_main_archive)")
    archive_cols = [row[1] for row in cursor.fetchall()]

    if "destruction_date" not in archive_cols:
        cursor.execute("ALTER TABLE aygaz_main_archive ADD COLUMN destruction_date TEXT")
    if "destruction_status" not in archive_cols:
        cursor.execute("ALTER TABLE aygaz_main_archive ADD COLUMN destruction_status TEXT DEFAULT 'BEKLİYOR'")

    connection.commit()
    connection.close()
def mark_record_as_destroyed(record_no):
    conn = get_db()
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%d.%m.%Y")
    cursor.execute("""
        UPDATE aygaz_main_archive 
        SET destruction_status = 'İMHA EDİLDİ', destruction_date = ? 
        WHERE doc_reg_no = ?
    """, (today_str, str(record_no)))
    conn.commit()
    conn.close()
    st.cache_data.clear()

def get_destroyed_records(year_filter=None):
    conn = get_db()
    query = """
        SELECT doc_reg_no AS 'Kayıt No', 
               doc_no AS 'Dosya No', 
               doc_name AS 'Belge Adı', 
               unit_code AS 'Birim', 
               retention_end_year AS 'İmha Yılı', 
               destruction_date AS 'İmha Tarihi', 
               destruction_status AS 'Durum' 
        FROM aygaz_main_archive 
        WHERE destruction_status = 'İMHA EDİLDİ'
    """
    if year_filter:
        query += f" AND (destruction_date LIKE '%{year_filter}%' OR retention_end_year = '{year_filter}')"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Imha_Listesi')
    return output.getvalue()
def read_df(query, params=()):
    connection = get_db()
    try:
        return pd.read_sql_query(query, connection, params=params)
    finally:
        connection.close()


def audit(user, action, details):
    connection = get_db()
    connection.execute("INSERT INTO archive_audit (timestamp, user, action_type, details) VALUES (?, ?, ?, ?)", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user, action, details))
    connection.commit()
    connection.close()


def excel_bytes(sheets):
    sheet_names = [str(name)[:31] for name in sheets]
    content_types = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">', '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>', '<Default Extension="xml" ContentType="application/xml"/>', '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>']
    workbook_relations = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    workbook_sheets = []
    for index, sheet_name in enumerate(sheet_names, 1):
        content_types.append(f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        workbook_relations.append(f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>')
        workbook_sheets.append(f'<sheet name="{escape(sheet_name)}" sheetId="{index}" r:id="rId{index}"/>')
    content_types.append('</Types>')
    workbook_relations.append('</Relationships>')
    workbook_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(workbook_sheets) + '</sheets></workbook>'
    root_relations = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", ''.join(content_types))
        archive.writestr("_rels/.rels", root_relations)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", ''.join(workbook_relations))
        for index, dataframe in enumerate(sheets.values(), 1):
            rows = [list(dataframe.columns)] + dataframe.fillna("").astype(str).values.tolist()
            row_xml = []
            for row_index, row in enumerate(rows, 1):
                cells = []
                for column_index, value in enumerate(row, 1):
                    column_letter = ""
                    current = column_index
                    while current:
                        current, remainder = divmod(current - 1, 26)
                        column_letter = chr(65 + remainder) + column_letter
                    cells.append(f'<c r="{column_letter}{row_index}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
                row_xml.append(f'<row r="{row_index}">' + ''.join(cells) + '</row>')
            sheet_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + ''.join(row_xml) + '</sheetData></worksheet>'
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml)
    return output.getvalue()


def download_excel(label, dataframe, filename, sheet_name="Arşiv Kataloğu", extra_sheets=None):
    sheets = {sheet_name: dataframe}
    if extra_sheets:
        sheets.update(extra_sheets)
    st.download_button(label, excel_bytes(sheets), filename, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


init_database()


def logo_data_uri():
    base_path = Path(__file__).resolve().parent
    logo_path = base_path / "Aygaz.png"
    if logo_path.exists():
        encoded_logo = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{encoded_logo}"
    return ""


def wordmark_data_uri():
    base_path = Path(__file__).resolve().parent
    wordmark_path = base_path / "aygaz_logo.jpg"
    if wordmark_path.exists():
        encoded_wordmark = base64.b64encode(wordmark_path.read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded_wordmark}"
    return ""

st.markdown("""
<style>
/* Tabloyu ve Hücreleri Beyaz, Başlıkları Aygaz Mavisi Yap */
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
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');
:root { --ink:#17232d; --muted:#687984; --line:#d8e2e8; --paper:#f5f8fa; --white:#fff; --aygaz:#0072bc; --aygaz-dark:#005b94; --teal:#147d72; --orange:#d47d36; }
html, body, [class*="css"] { font-family:'DM Sans', sans-serif; }
.stApp { background:var(--paper); color:var(--ink); }
[data-testid="stSidebar"] { background:#0072bc; border-right:0; }
[data-testid="stSidebar"] * { color:#ffffff !important; }
[data-testid="stSidebar"] div[data-baseweb="select"] > div { background:#ffffff !important; border-radius:7px !important; }
[data-testid="stSidebar"] div[data-baseweb="select"] > div,
[data-testid="stSidebar"] div[data-baseweb="select"] > div > div,
[data-testid="stSidebar"] div[data-baseweb="select"] > div > div > div,
[data-testid="stSidebar"] div[data-baseweb="select"] span,
[data-testid="stSidebar"] div[data-baseweb="select"] p,
[data-testid="stSidebar"] div[data-baseweb="select"] input { color:#005696 !important; -webkit-text-fill-color:#005696 !important; font-weight:600 !important; opacity:1 !important; text-shadow:none !important; }
[data-testid="stSidebar"] div[data-baseweb="select"] svg { fill:#005696 !important; color:#005696 !important; stroke:#005696 !important; }
[data-testid="stSidebar"] hr { border-color:#5aa6d2; }
[data-testid="stSidebar"] .stRadio label { padding:9px 11px; border-radius:7px; }
[data-testid="stSidebar"] .stRadio label:hover { background:#29434b; }
[data-testid="stDataFrame"] { background:#ffffff !important; border:1px solid #b9d8eb !important; }
[data-testid="stDataFrame"] iframe { background:#ffffff !important; }
[data-testid="stDataFrame"] [role="columnheader"] { background:#0072bc !important; color:#ffffff !important; }
[data-testid="stDataFrame"] [role="gridcell"] { background:#ffffff !important; color:#17232d !important; }
h1,h2,h3,h4 { color:var(--ink) !important; letter-spacing:0 !important; }
h1 { font-size:30px !important; } h2 { font-size:21px !important; } h3 { font-size:16px !important; }
p, label, .stCaption { color:var(--muted); }
.brand { padding:10px 0 25px; } .brand-mark { font-family:'Space Mono'; color:#ffffff; font-size:18px; letter-spacing:2px; }
.brand-name { color:white; font-size:21px; font-weight:700; margin-top:8px; } .brand-meta { color:#d9effb; font-size:11px; margin-top:3px; }
.topbar { background:white; border-bottom:1px solid var(--line); margin:-1rem -1rem 25px; padding:14px 28px; display:flex; align-items:center; justify-content:space-between; box-shadow:0 2px 10px rgba(20,49,67,.04); }
.aygaz-lockup { display:flex; align-items:center; gap:11px; color:var(--aygaz-dark); font-size:17px; font-weight:700; letter-spacing:.2px; }
.aygaz-symbol { width:29px; height:29px; border-radius:7px; background:var(--aygaz); display:grid; place-items:center; color:white; font-family:'Space Mono'; font-size:14px; font-weight:700; box-shadow:inset 0 -3px 0 rgba(0,0,0,.12); }
.topbar-user { display:flex; align-items:center; gap:9px; color:var(--ink); font-size:12px; font-weight:600; }
.topbar-user-dot { width:28px; height:28px; border-radius:50%; background:#e3f0f8; color:var(--aygaz-dark); display:grid; place-items:center; font-family:'Space Mono'; font-size:10px; }
.scope { background:#eaf4fa; border:1px solid #c9e2f2; color:#075b91; border-radius:5px; padding:8px 11px; font-size:12px; margin-bottom:17px; }
.eyebrow { font-family:'Space Mono'; color:var(--teal); font-size:11px; letter-spacing:1.4px; text-transform:uppercase; }
.page-head { display:flex; justify-content:space-between; align-items:end; margin:4px 0 22px; } .page-head p { margin:4px 0 0; font-size:13px; }
.stamp { border:1px solid var(--line); background:white; padding:9px 13px; border-radius:7px; font-family:'Space Mono'; font-size:11px; color:var(--muted); }
.metric { background:white; border:1px solid var(--line); border-radius:8px; padding:16px 17px; min-height:103px; }
.metric-label { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:1px; font-weight:700; } .metric-value { color:var(--ink); font-size:27px; font-weight:700; margin:8px 0 2px; } .metric-note { color:var(--muted); font-size:11px; }
.panel { background:white; border:1px solid var(--line); border-radius:8px; padding:18px; } .panel-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; } .panel-title { font-size:15px; font-weight:700; color:var(--ink); }
.mono { font-family:'Space Mono'; } .hint { background:#e6f3ef; border-left:3px solid var(--teal); padding:11px 13px; border-radius:4px; font-size:12px; color:#24544d; } .risk { background:#fff3e8; border-left:3px solid var(--orange); padding:11px 13px; border-radius:4px; font-size:12px; color:#75451f; }
.stButton button, .stDownloadButton button { border-radius:6px; font-weight:600; border:1px solid var(--line); min-height:38px; color:var(--ink) !important; } .stButton button[kind="primary"] { background:#148b80 !important; border-color:#148b80 !important; color:#ffffff !important; text-shadow:none !important; } .stButton button[kind="primary"] p { color:#ffffff !important; }
.stTextInput input, .stSelectbox div[data-baseweb="select"], .stTextArea textarea { border-radius:6px; } [data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:7px; }
</style>
""", unsafe_allow_html=True)

users_df = read_df("SELECT username, full_name, unit_code, auth_codes, role_desc FROM user_permissions ORDER BY id")
def normalize_auth_codes(auth_codes):
    if auth_codes is None:
        return set()

    return {
        code.strip().upper()
        for code in str(auth_codes).split(",")
        if code.strip()
    }


def has_permission(user_row, permission):
    permission = permission.strip().upper()

    auth_codes = normalize_auth_codes(user_row["auth_codes"])

    if "*" in auth_codes or "ADMIN" in auth_codes:
        return True

    return permission in auth_codes


def is_admin_user(user_row):
    role = str(user_row["role_desc"] or "").strip().lower()
    unit = str(user_row["unit_code"] or "").strip().upper()
    auth_codes = normalize_auth_codes(user_row["auth_codes"])

    return (
        unit == "ALL"
        or "admin" in role
        or "yönetici" in role
        or "ADMIN" in auth_codes
        or "*" in auth_codes
    )
with st.sidebar:
    sidebar_wordmark = wordmark_data_uri()
    sidebar_brand = f'<img src="{sidebar_wordmark}" alt="AYGAZ" style="width:148px;height:auto;display:block;margin:0 0 12px -4px">' if sidebar_wordmark else '<div class="brand-mark">AYGAZ</div>'
    st.markdown(f'<div class="brand">{sidebar_brand}<div class="brand-name">Arşiv Sistemi</div><div class="brand-meta">AMBARLI OPERASYON MERKEZİ</div></div>', unsafe_allow_html=True)
    if users_df.empty:
        st.error("user_permissions tablosunda kullanıcı bulunamadı.")
        st.stop()
    user_labels = [f"{row.full_name} · {row.unit_code}" for row in users_df.itertuples()]
    configured_user = os.getenv("AIBS_USER", "").casefold()
    default_index = next((index for index, row in enumerate(users_df.itertuples()) if str(row.username).casefold() == configured_user), 0)
    selected_user = st.selectbox("Kullanıcı", user_labels, index=default_index, label_visibility="visible")
    active_row = users_df.iloc[user_labels.index(selected_user)]
    active_name = active_row["full_name"]
    active_unit = active_row["unit_code"]
    active_user = active_row["username"]
    is_admin = is_admin_user(active_row)
    st.caption(f"{active_row['role_desc']} · {active_unit}")
    st.markdown("---")
menu_options = ["Katalog", "İş kuyruğu"]

if is_admin:
    menu_options.extend([
        "Tanımlar",
        "Saklama ve imha",
        "Günlükler",
        "Denetim izi"
    ])

menu = st.radio(
    "Çalışma alanı",
    menu_options,
    label_visibility="visible"
)

st.markdown("---")
    '<div style="color:#ffffff;font-size:12px;font-weight:600;">Veritabanı bağlı</div>',
    unsafe_allow_html=True
)
    st.caption(datetime.now().strftime("Son senkronizasyon  %d.%m.%Y · %H:%M"))

user_initial = active_name[:1].upper() if active_name else "K"
scope_label = "Tüm birimler" if active_unit == "ALL" else f"Birim kapsamı: {active_unit}"
logo_src = logo_data_uri()
logo_markup = f'<img src="{logo_src}" alt="Aygaz logosu" style="width:34px;height:34px;object-fit:contain">' if logo_src else '<div class="aygaz-symbol">A</div>'
st.markdown(f'<div class="topbar"><div class="aygaz-lockup">{logo_markup}<span>AYGAZ ARŞİV SİSTEMİ</span></div><div class="topbar-user"><div class="topbar-user-dot">{user_initial}</div><span>{active_name}</span><span class="mono" style="color:#687984;font-size:10px">{scope_label}</span></div></div>', unsafe_allow_html=True)


scope_sql = " AND unit_code = ?" if active_unit != "ALL" else ""
scope_params = (active_unit,) if active_unit != "ALL" else ()
scoped_count = read_df("SELECT COUNT(*) AS value FROM aygaz_main_archive WHERE 1=1" + scope_sql, scope_params).iloc[0]["value"]
open_requests = read_df("SELECT COUNT(*) AS value FROM archive_requests WHERE status NOT IN ('Tamamlandı / İade', 'Teslim Edildi', 'İptal / Red')" + scope_sql, scope_params).iloc[0]["value"]
custody_count = read_df("SELECT COUNT(*) AS value FROM aygaz_main_archive WHERE status = 'Zimmette'" + scope_sql, scope_params).iloc[0]["value"]
retention_count = read_df("SELECT COUNT(*) AS value FROM aygaz_main_archive WHERE retention_end_year <= ? AND destruction_status != 'Edildi'" + scope_sql, (CURRENT_YEAR,) + scope_params).iloc[0]["value"]


def header(title, description):
    st.markdown(f'<div class="page-head"><div><div class="eyebrow">AYGAZ ARŞİV SİSTEMİ / {menu.upper()}</div><h1>{title}</h1><p>{description}</p></div><div class="stamp">{datetime.now().strftime("%d %b %Y · %H:%M")}</div></div>', unsafe_allow_html=True)


if menu == "Katalog":
    header("Arşiv kataloğu", "Belgeyi adıyla değil, fiziksel hayat döngüsüyle bulun.")
    metrics = [("Katalog kaydı", f"{scoped_count:,}", "yetki kapsamındaki kayıtlar"), ("Açık iş", f"{open_requests}", "talep kuyruğunda"), ("Zimmette", f"{custody_count}", "aktif kullanıcı erişimi"), ("Süre riski", f"{retention_count}", f"{CURRENT_YEAR} ve öncesi")]
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
        query = "SELECT doc_reg_no AS [Kayıt No], doc_no AS [Dosya No], doc_name AS [Belge], series_code AS [Seri], unit_code AS [Birim], first_doc_date AS [İlk Evrak Tarihi], last_doc_date AS [Son Evrak Tarihi], box_no AS [Kutu No], shelf_no AS [Yer No], institution AS [Kurum], status AS [Durum], destruction_status AS [İmha Durumu], retention_end_year AS [Saklama Sonu] FROM aygaz_main_archive WHERE 1=1"
        params = []
        if active_unit != "ALL": query += " AND unit_code = ?"; params.append(active_unit)
        if search.strip(): query += " AND (doc_reg_no LIKE ? OR doc_no LIKE ? OR doc_name LIKE ? OR box_no LIKE ? OR shelf_no LIKE ?)"; params.extend([f"%{search.strip()}%"] * 5)
        if status != "Tümü": query += " AND status = ?"; params.append(status)
        if unit.strip() and active_unit == "ALL": query += " AND unit_code LIKE ?"; params.append(f"%{unit.strip()}%")
        catalog_df = read_df(query + " ORDER BY id DESC LIMIT ?", params + [limit])
        st.dataframe(catalog_df, width="stretch", hide_index=True, height=390)
        st.caption(f"{len(catalog_df)} kayıt gösteriliyor · Filtreler doğrudan arşiv kataloğuna uygulanıyor")
        download_excel("Katalog Excel indir", catalog_df, "aygaz-arsiv-katalog.xlsx")
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
                        new_unit = st.text_input("Birim kodu")
                        new_box = st.text_input("Kutu no")
                    with a3:
                        new_shelf = st.text_input("Raf / yer no")
                        new_first_date = st.text_input("İlk evrak tarihi", placeholder="GG/AA/YYYY")
                        new_last_date = st.text_input("Son evrak tarihi", placeholder="GG/AA/YYYY")
                    if st.form_submit_button("Arşiv kaydını oluştur", type="primary") and new_reg.strip() and new_doc_name.strip() and new_unit.strip():
                        connection = get_db()
                        connection.execute("INSERT INTO aygaz_main_archive (doc_reg_no, doc_no, doc_name, series_code, unit_code, first_doc_date, last_doc_date, box_no, shelf_no, institution, status, destruction_status, retention_end_year) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_reg.strip(), new_doc_no.strip(), new_doc_name.strip(), new_series.strip(), new_unit.strip(), new_first_date.strip(), new_last_date.strip(), new_box.strip(), new_shelf.strip(), "AYGAZ", "Depoda", "Edilmedi", CURRENT_YEAR + 10))
                        connection.commit(); connection.close(); audit(active_user, "Arşiv kaydı", f"{new_reg} · {new_doc_name}"); st.success("Arşiv kaydı oluşturuldu."); st.rerun()
    with right:
        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">Kayıt özeti</div><div class="mono">LIVE</div></div>', unsafe_allow_html=True)
        if not catalog_df.empty:
            selected_reg = st.selectbox("İncelenecek kayıt", catalog_df["Kayıt No"].tolist(), label_visibility="collapsed")
            selected = catalog_df[catalog_df["Kayıt No"] == selected_reg].iloc[0]
            st.markdown(f'<div class="eyebrow">KAYIT / {selected["Kayıt No"]}</div><h3>{selected["Belge"]}</h3><p><b>Fiziksel konum</b><br><span class="mono">KUTU {selected["Kutu No"]} · RAF {selected["Yer No"]}</span></p><p><b>Birim</b> {selected["Birim"]}<br><b>Seri</b> {selected["Seri"]}</p><div style="color:#1472bc;font-weight:700">● {selected["Durum"]}</div>', unsafe_allow_html=True)
            if st.button("Bu kayıt için talep aç", type="primary", width="stretch"): st.session_state["request_doc"] = f"#{selected['Kayıt No']} · {selected['Belge']}"; st.session_state["request_open"] = True; st.rerun()
        else: st.info("Filtrelere uyan kayıt bulunamadı.")
        st.markdown("</div>", unsafe_allow_html=True)
    if st.session_state.get("request_open"):
        st.markdown("### Yeni erişim talebi")
        with st.form("catalog_request"):
            c1, c2 = st.columns(2)
            with c1: request_doc = st.text_input("Kayıt", value=st.session_state.get("request_doc", ""), disabled=True); request_type = st.selectbox("Erişim biçimi", ["Fiziksel zimmet", "Dijital tarama (PDF)"])
            with c2: request_urgency = st.selectbox("Öncelik", ["Normal", "Acil", "Kritik"]); request_note = st.text_area("Gerekçe", placeholder="İnceleme amacı veya teslim notu...")
            if st.form_submit_button("Talebi kuyruğa al", type="primary"):
                request_no = f"TR-{uuid.uuid4().hex[:8].upper()}"
                connection = get_db(); connection.execute("INSERT INTO archive_requests (req_no, requester, unit_code, doc_item, delivery_type, urgency, status, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (request_no, active_name, active_unit, request_doc, request_type, request_urgency, "Onay Bekliyor", request_note, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))); connection.commit(); connection.close()
                audit(active_user, "Talep oluşturma", f"{request_no} · {request_doc}"); st.session_state["request_open"] = False; st.success(f"{request_no} numaralı talep kuyruğa alındı."); st.rerun()

elif menu == "Tanımlar" and is_admin:
    header("Tanımlar", "Mevcut Aygaz arşiv sınıflandırmasını bozmadan kurum, birim ve seri kayıtlarını incele.")
    definition_tabs = st.tabs(["Birimler", "Seriler", "Kurumlar"])
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
                    connection = get_db()
                    connection.execute("INSERT INTO units (name, code, inst_code, inst_name) VALUES (?, ?, ?, ?)", (new_unit_name.strip(), new_unit_code.strip(), new_unit_inst.strip(), "AYGAZ A.Ş."))
                    connection.commit(); connection.close(); audit(active_user, "Birim tanımı", f"{new_unit_code} · {new_unit_name}"); st.success("Birim kaydedildi."); st.rerun()
    with definition_tabs[1]:
        series_search = st.text_input("Serilerde ara", placeholder="Seri adı, kodu veya mevzuat...")
        series_query = "SELECT id AS [ID], name AS [Seri Adı], unit_code AS [Birim Kodu], unit_name AS [Birim], series_code AS [Seri Kodu], retention_year AS [Saklama (Yıl)], legal_basis AS [Mevzuat Dayanağı] FROM series WHERE 1=1"
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
                if st.form_submit_button("Seriyi kaydet", type="primary") and new_series_name.strip() and new_series_code.strip():
                    connection = get_db()
                    connection.execute("INSERT INTO series (name, unit_code, unit_name, series_code, retention_year, legal_basis) VALUES (?, ?, ?, ?, ?, ?)", (new_series_name.strip(), new_series_unit.strip(), "", new_series_code.strip(), new_series_retention, new_series_basis.strip()))
                    connection.commit(); connection.close(); audit(active_user, "Seri tanımı", f"{new_series_code} · {new_series_name}"); st.success("Seri kaydedildi."); st.rerun()
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
                    connection = get_db()
                    connection.execute("INSERT INTO institutions (name, code) VALUES (?, ?)", (new_institution_name.strip(), new_institution_code.strip()))
                    connection.commit(); connection.close(); audit(active_user, "Kurum tanımı", f"{new_institution_code} · {new_institution_name}"); st.success("Kurum kaydedildi."); st.rerun()

elif menu == "İş kuyruğu":
    header("İş kuyruğu", "Erişim taleplerini önceliklendir, hazırla ve iz bırak.")
    filter_sql = " AND unit_code = ?" if active_unit != "ALL" else ""
    queue_df = read_df("SELECT id, req_no AS [Talep], requester AS [Talep Eden], unit_code AS [Birim], doc_item AS [Kayıt], delivery_type AS [Teslim], urgency AS [Öncelik], status AS [Durum], created_at AS [Oluşturuldu], notes AS [Not] FROM archive_requests WHERE 1=1" + filter_sql + " ORDER BY id DESC", (active_unit,) if active_unit != "ALL" else ())
    q1, q2, q3 = st.columns(3); q1.metric("Toplam kuyruk", len(queue_df)); q2.metric("Onay bekleyen", int((queue_df["Durum"] == "Onay Bekliyor").sum()) if not queue_df.empty else 0); q3.metric("Acil işler", int(queue_df["Öncelik"].isin(["Acil", "Kritik"]).sum()) if not queue_df.empty else 0)
    st.markdown("<br>", unsafe_allow_html=True); st.dataframe(queue_df.drop(columns=["id"], errors="ignore"), width="stretch", hide_index=True, height=350)
    if not queue_df.empty:
        st.markdown("### Durum güncelle"); u1, u2, u3 = st.columns([2, 2, 1])
        with u1: selected_request = st.selectbox("Talep", queue_df["Talep"].tolist())
        with u2: new_status = st.selectbox("Yeni durum", ["Onay Bekliyor", "Hazırlanıyor", "Kuryede", "Teslim Edildi", "İptal / Red"])
        with u3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Güncelle", type="primary", width="stretch"):
                connection = get_db(); connection.execute("UPDATE archive_requests SET status = ? WHERE req_no = ?", (new_status, selected_request)); connection.commit(); connection.close(); audit(active_user, "Talep durumu", f"{selected_request} → {new_status}"); st.success("Talep durumu güncellendi."); st.rerun()
        st.markdown("### Talep içi mesajlaşma")
        try:
            message_df = read_df("SELECT * FROM request_messages WHERE req_no = ?", params=[selected_request])
            if not message_df.empty:
                st.dataframe(message_df, width="stretch", hide_index=True)
        except Exception:
            pass
        with st.form("request_message_form"):
            message = st.text_input("Mesaj", placeholder="Konum, teslimat veya inceleme notu...")
            if st.form_submit_button("Mesajı kaydet") and message.strip():
                connection = get_db()
                connection.execute("INSERT INTO request_messages (req_no, sender, message, created_at) VALUES (?, ?, ?, ?)", (selected_request, active_name, message.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                connection.commit(); connection.close()
                audit(active_user, "Talep mesajı", f"{selected_request} talebine mesaj eklendi")
                st.rerun()
elif menu == "Saklama ve imha" and is_admin:
    st.markdown("### Saklama ve İmha Yönetimi")

    tab1, tab2 = st.tabs(["Süresi Dolanlar (İmha Bekleyenler)", "İmha Edilen Belgeler Arşivi"])

    with tab1:
        st.markdown("#### İmha Edilecek Belgeler Listesi")
        conn = get_db()
        pending_df = pd.read_sql_query("""
            SELECT doc_reg_no AS 'Kayıt No', 
                   doc_no AS 'Dosya No', 
                   doc_name AS 'Belge Adı', 
                   unit_code AS 'Birim', 
                   retention_end_year AS 'İmha Yılı', 
                   destruction_status AS 'Durum'
            FROM aygaz_main_archive 
            WHERE (destruction_status IS NULL OR destruction_status != 'İMHA EDİLDİ') 
            AND CAST(retention_end_year AS INTEGER) <= 2026
        """, conn)
        conn.close()

        if not pending_df.empty:
            st.dataframe(pending_df, use_container_width=True)
            
            st.markdown("---")
            st.markdown("**İmha İşlemi Onayı**")
            col_sel, col_btn = st.columns([3, 1])
            with col_sel:
                selected_record = st.selectbox("İmha edilecek belgeyi seçin:", pending_df["Kayıt No"].tolist())
            with col_btn:
                st.write("")
                st.write("")
                if st.button("İmha Edildi Olarak İşaretle", type="primary", use_container_width=True):
                    mark_record_as_destroyed(selected_record)
                    st.success(f"Kayıt No {selected_record} başarıyla imha edildi olarak işaretlendi.")
                    st.rerun()
        else:
            st.info("İmha süresi dolmuş bekleyen belge bulunmamaktadır.")

    with tab2:
        st.markdown("#### 2026 Yılı İmha Tutanağı ve Arşivi")
        destroyed_df = get_destroyed_records(year_filter="2026")
        
        if not destroyed_df.empty:
            st.dataframe(destroyed_df, use_container_width=True)
            
            excel_data = convert_df_to_excel(destroyed_df)
            st.download_button(
                label="2026 İmha Edilen Belgeler Listesini İndir (Excel)",
                data=excel_data,
                file_name="Aygaz_Imha_Edilen_Belgeler_2026.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.info("2026 yılı için henüz imha edilmiş bir belge kaydı bulunmuyor.")
elif menu == "Günlükler" and is_admin:
    header("Yönetim raporları", "Arşiv hacmini, iş yükünü ve saklama riskini tek bakışta değerlendir.")
    unit_report = read_df("SELECT unit_code AS [Birim], COUNT(*) AS [Kayıt], SUM(CASE WHEN status = 'Zimmette' THEN 1 ELSE 0 END) AS [Zimmette], SUM(CASE WHEN retention_end_year <= ? AND destruction_status != 'Edildi' THEN 1 ELSE 0 END) AS [Süre riski] FROM aygaz_main_archive GROUP BY unit_code ORDER BY [Kayıt] DESC", (CURRENT_YEAR,))
    status_report = read_df("SELECT status AS [Durum], COUNT(*) AS [Kayıt] FROM aygaz_main_archive GROUP BY status ORDER BY [Kayıt] DESC")
    r1, r2 = st.columns(2)
    with r1:
        st.markdown("### Birim dağılımı")
        st.dataframe(unit_report, width="stretch", hide_index=True, height=300)
        st.bar_chart(unit_report.set_index("Birim")[["Kayıt", "Zimmette", "Süre riski"]])
    with r2:
        st.markdown("### Durum dağılımı")
        st.dataframe(status_report, width="stretch", hide_index=True, height=300)
        st.bar_chart(status_report.set_index("Durum"))
    st.markdown("### Kayıt hareket raporları")
    report_tabs = st.tabs(["Günlük kayıtlar", "Aylık kayıtlar"])
    with report_tabs[0]:
        report_day = st.date_input("Gün", value=datetime.now().date())
        daily_report = read_df("SELECT substr(first_doc_date, 7, 4) || '-' || substr(first_doc_date, 4, 2) || '-' || substr(first_doc_date, 1, 2) AS [Kayıt Tarihi], unit_code AS [Birim], COUNT(*) AS [Kayıt Sayısı] FROM aygaz_main_archive WHERE first_doc_date IS NOT NULL GROUP BY [Kayıt Tarihi], unit_code ORDER BY [Kayıt Tarihi] DESC")
        st.dataframe(daily_report, width="stretch", hide_index=True, height=220)
        download_excel("Günlük Excel indir", daily_report, "aygaz-gunluk-kayitlar.xlsx", "Günlük Kayıtlar")
    with report_tabs[1]:
        monthly_report = read_df("SELECT substr(first_doc_date, 7, 4) || '-' || substr(first_doc_date, 4, 2) AS [Ay], unit_code AS [Birim], COUNT(*) AS [Kayıt Sayısı] FROM aygaz_main_archive WHERE first_doc_date IS NOT NULL GROUP BY [Ay], unit_code ORDER BY [Ay] DESC")
        st.dataframe(monthly_report, width="stretch", hide_index=True, height=220)
        download_excel("Aylık Excel indir", monthly_report, "aygaz-aylik-kayitlar.xlsx", "Aylık Kayıtlar")
    download_excel("Yönetim raporunu indir", unit_report, "aygaz-arsiv-yonetim-raporu.xlsx", "Birim Raporu", {"Durum Raporu": status_report})

elif menu == "Denetim izi" and is_admin:
    header("Denetim izi", "Arşivde kim, ne zaman, hangi kararı verdi?")
    audit_df = read_df("SELECT timestamp AS [Zaman], user AS [Kullanıcı], action_type AS [İşlem], details AS [Detay] FROM archive_audit ORDER BY id DESC LIMIT 250")
    st.markdown('<div class="hint">Bu akış kullanıcı işlemlerini gösterir. Talep değişiklikleri ve erişim talepleri zaman damgasıyla tutulur.</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True); st.dataframe(audit_df, width="stretch", hide_index=True, height=520)

