"""Kho linh kiện: quản lý số lượng, mã nhà cung cấp, BOM (có/thiếu), cảnh báo sắp hết, nhập đơn hàng.

Chỉ dùng thư viện chuẩn (sqlite3, csv, zipfile/xml cho .xlsx) để chạy được trên OpenWrt.
Dữ liệu: /mnt/data/kho/kho.db (+ bản sao lưu mỗi ngày trong /mnt/data/kho/backup, giữ 14 bản).

Đọc file (BOM hoặc đơn hàng): CSV (tự nhận dấu phân cách và bảng mã) hoặc XLSX. Tự tìm dòng tiêu đề và
nhận cột theo tên quen thuộc của LCSC / JLCPCB, Digi-Key, Mouser, KiCad, EasyEDA, Altium; sửa lại được trên trang.

Khớp dòng BOM với linh kiện trong kho, theo thứ tự: mã LCSC -> mã Digi-Key -> mã Mouser -> MPN (bỏ khoảng trắng,
dấu -) -> giá trị + package. Dòng nào khớp sai thì chọn lại tay trên trang.
"""
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

DATA_DIR = os.environ.get("KHO_DIR", "/mnt/data/kho")
DB_FILE = os.path.join(DATA_DIR, "kho.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backup")
KEEP_BACKUPS = 14
MAX_UPLOAD = 5 * 1024 * 1024
SUPPLIERS = ("lcsc", "digikey", "mouser", "taobao", "other")

PART_FIELDS = ("mpn", "manufacturer", "name", "category", "package", "value", "location",
               "qty", "min_qty", "price", "currency", "datasheet", "image", "notes")

# ------------------------------------------------------------------ nhận cột theo tên
# tên cột (đã chuẩn hóa: chữ thường, bỏ ký tự đặc biệt) -> trường. Thứ tự trong list = ưu tiên.
ALIASES = {
    "lcsc": ["lcscpartnumber", "lcscpart", "lcsc", "lcscpn", "lcscno", "jlcpcbpart", "jlcpcbpartnumber",
             "lcscpartno", "supplierpartlcsc"],
    "digikey": ["digikeypartnumber", "digikeypart", "digikey", "digikeypn", "dkpartnumber", "dkpn",
                "digikeyno"],
    "mouser": ["mouser", "mouserpartnumber", "mouserpart", "mouserno", "mouserpn"],
    "taobao": ["taobao", "taobaolink", "linktaobao", "taobaourl"],
    "mpn": ["manufacturerpartnumber", "manufacturepartnumber", "mfrpartnumber", "mfrpart", "mfr", "mpn",
            "manufacturerpart", "mfrpartno", "partnumbermfr", "mfrno", "mãlinhkiện", "malinhkien"],
    "manufacturer": ["manufacturer", "manufacturername", "mfrname", "hãng", "hang", "nhàsảnxuất"],
    "qty": ["orderqty", "quantity", "qty", "quantityordered", "shippedqty", "qtyshipped", "số lượng", "sốlượng",
            "soluong", "sl", "quantityperpcb", "count", "tồnkho", "ton"],
    "designator": ["designator", "designators", "reference", "references", "ref", "refdes", "partreference"],
    "value": ["value", "comment", "giátrị", "giatri"],
    "package": ["package", "footprint", "case", "packagecase", "kiểuchân", "dóng gói", "đónggói"],
    "name": ["description", "name", "partname", "productdescription", "tên", "ten", "mô tả", "môtả"],
    "category": ["category", "loại", "loai", "nhóm", "nhom", "type"],
    "location": ["location", "vịtrí", "vitri", "ngăn", "ngan", "bin", "storage"],
    "price": ["unitprice", "unitpriceusd", "price", "priceusd", "đơngiá", "dongia"],
    "supplier": ["supplier", "vendor", "nhàcungcấp"],
    "supplier_part": ["supplierpart", "supplierpartnumber", "vendorpart"],
    "min_qty": ["minqty", "minimum", "min", "tốithiểu", "toithieu", "minstock"],
    "dnp": ["dnp", "donotplace", "dnf"],
}
FIELD_LABELS = {"lcsc": "Mã LCSC", "digikey": "Mã Digi-Key", "mouser": "Mã Mouser", "taobao": "Link Taobao",
                "mpn": "MPN", "manufacturer": "Hãng", "qty": "Số lượng", "designator": "Designator",
                "value": "Giá trị", "package": "Package", "name": "Mô tả", "category": "Loại",
                "location": "Vị trí", "price": "Đơn giá", "supplier": "Nhà cung cấp",
                "supplier_part": "Mã nhà cung cấp", "min_qty": "Tối thiểu", "dnp": "DNP"}
LCSC_RE = re.compile(r"^C\d{2,9}$", re.I)


def _norm_header(h):
    h = str(h or "").strip().lower()
    h = re.sub(r"\(.*?\)|\[.*?\]", "", h)          # bỏ "(USD)", "($)"
    return re.sub(r"[\s_\-.#:/\\'\"]+", "", h)


def guess_mapping(headers):
    """headers -> {field: index}. Mỗi cột chỉ gán cho một trường."""
    normed = [_norm_header(h) for h in headers]
    mapping, used = {}, set()
    for field, names in ALIASES.items():
        for name in names:
            key = _norm_header(name)
            idx = next((i for i, h in enumerate(normed) if h == key and i not in used), None)
            if idx is None:   # khớp một phần cho tên dài (vd "manufacturerpartnumber1")
                idx = next((i for i, h in enumerate(normed) if len(key) >= 6 and key in h and i not in used), None)
            if idx is not None:
                mapping[field] = idx
                used.add(idx)
                break
    # Digi-Key xuất cột "Part Number" = mã Digi-Key; file khác "Part Number" thường là MPN.
    if "partnumber" in normed:
        i = normed.index("partnumber")
        if i not in used:
            dk = any("digikey" in h or "digi" in h for h in normed) or any(h == "customerreference" for h in normed)
            mapping.setdefault("digikey" if dk else "mpn", i)
    return mapping


def mpn_key(s):
    return re.sub(r"[\s\-_/.,]+", "", str(s or "")).upper()


_OCR_FIX = str.maketrans("OISBZQ", "015820")


def mpn_fuzzy(s):
    """Khóa so khớp gần đúng cho MPN đọc bằng OCR: coi O=0, I=1, S=5, B=8, Z=2, Q=0."""
    return mpn_key(s).translate(_OCR_FIX)


def _num(s, default=None):
    if s is None:
        return default
    if isinstance(s, (int, float)):
        return s
    t = str(s).strip().replace(" ", "").replace("$", "").replace("¥", "").replace("€", "")
    if not t:
        return default
    t = t.replace(",", "") if re.fullmatch(r"[\d,]+(\.\d+)?", t) else t.replace(",", ".")
    m = re.search(r"-?\d+(\.\d+)?", t)
    return float(m.group()) if m else default


def _int(s, default=0):
    v = _num(s)
    return int(round(v)) if v is not None else default


# ------------------------------------------------------------------ đọc file
def _read_xlsx(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
    sheets = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    if not sheets:
        raise ValueError("File .xlsx không có sheet")
    root = ET.fromstring(z.read(sheets[0]))
    rows = []
    for r in root.iter("{%s}row" % ns["m"]):
        row = {}
        for c in r.findall("m:c", ns):
            ref = c.get("r", "")
            col = 0
            for ch in re.match(r"[A-Z]*", ref).group():
                col = col * 26 + ord(ch) - 64
            t = c.get("t")
            v = c.find("m:v", ns)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
            else:
                val = v.text if v is not None else ""
                if val and re.fullmatch(r"-?\d+\.0+", val):
                    val = val.split(".")[0]
            row[(col or len(row) + 1) - 1] = val or ""
        if row:
            rows.append([row.get(i, "") for i in range(max(row) + 1)])
    return rows


def _decode(data):
    for enc in ("utf-8-sig", "utf-16"):
        try:
            t = data.decode(enc)
            if enc == "utf-16" and not (data[:2] in (b"\xff\xfe", b"\xfe\xff")):
                continue
            return t
        except UnicodeDecodeError:
            continue
    for enc in ("cp1258", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "replace")


def read_table(name, data):
    """Trả về list các dòng (list chuỗi) từ CSV / TSV / XLSX."""
    if len(data) > MAX_UPLOAD:
        raise ValueError("File quá lớn (tối đa 5 MB)")
    if data[:2] == b"PK" or str(name).lower().endswith((".xlsx", ".xlsm")):
        try:
            return _read_xlsx(data)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
            raise ValueError(f"Không đọc được file Excel: {e}")
    if str(name).lower().endswith(".xls") and data[:4] == b"\xd0\xcf\x11\xe0":
        raise ValueError("File .xls (Excel cũ) chưa hỗ trợ: mở bằng Excel rồi lưu lại thành .xlsx hoặc .csv")
    text = _decode(data)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if sample.count("\t") > sample.count(",") else csv.excel
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), dialect)]


def find_header(rows):
    """Dòng tiêu đề = dòng đầu (trong 30 dòng) nhận được nhiều cột nhất."""
    best, best_i = 0, 0
    for i, row in enumerate(rows[:30]):
        n = len(guess_mapping(row))
        if n > best:
            best, best_i = n, i
    if best < 2:
        raise ValueError("Không nhận ra dòng tiêu đề (cần ít nhất 2 cột như Số lượng, MPN, Mã LCSC…)")
    return best_i


def parse_rows(rows, mapping):
    """Áp mapping -> list dict theo trường. Bỏ dòng trống / dòng tổng."""
    out = []
    for row in rows:
        if not any(c.strip() for c in row):
            continue
        rec = {f: (row[i].strip() if i < len(row) else "") for f, i in mapping.items() if i is not None}
        # mã LCSC đôi khi nằm ở cột "supplier part" hoặc cột khác
        if not rec.get("lcsc"):
            sp = rec.get("supplier_part", "")
            if LCSC_RE.match(sp) or (rec.get("supplier", "").lower().startswith(("lcsc", "jlc")) and sp):
                rec["lcsc"] = sp
        if rec.get("lcsc") and not LCSC_RE.match(rec["lcsc"]):
            m = re.search(r"\bC\d{2,9}\b", rec["lcsc"])
            rec["lcsc"] = m.group().upper() if m else ""
        elif rec.get("lcsc"):
            rec["lcsc"] = rec["lcsc"].upper()
        if not any(rec.get(k) for k in ("mpn", "lcsc", "digikey", "mouser", "value", "name", "taobao")):
            continue
        low = " ".join(str(v).lower() for v in rec.values())
        if re.match(r"^(total|tổng|subtotal|merchandise)", low.strip()):
            continue
        out.append(rec)
    return out


# ------------------------------------------------------------------ CSDL
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS parts (
  id INTEGER PRIMARY KEY, mpn TEXT DEFAULT '', mpn_key TEXT DEFAULT '', manufacturer TEXT DEFAULT '',
  name TEXT DEFAULT '', category TEXT DEFAULT '', package TEXT DEFAULT '', value TEXT DEFAULT '',
  location TEXT DEFAULT '', qty INTEGER DEFAULT 0, min_qty INTEGER DEFAULT 0, price REAL, currency TEXT DEFAULT 'USD',
  datasheet TEXT DEFAULT '', image TEXT DEFAULT '', notes TEXT DEFAULT '', created REAL, updated REAL);
CREATE INDEX IF NOT EXISTS parts_mpn_key ON parts (mpn_key);
CREATE TABLE IF NOT EXISTS part_suppliers (
  id INTEGER PRIMARY KEY, part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
  supplier TEXT NOT NULL, sku TEXT DEFAULT '', url TEXT DEFAULT '', price REAL);
CREATE INDEX IF NOT EXISTS ps_sku ON part_suppliers (supplier, sku);
CREATE INDEX IF NOT EXISTS ps_part ON part_suppliers (part_id);
CREATE TABLE IF NOT EXISTS stock_log (
  id INTEGER PRIMARY KEY, part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
  ts REAL, delta INTEGER, qty_after INTEGER, reason TEXT DEFAULT '', ref TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS log_part ON stock_log (part_id, ts);
CREATE TABLE IF NOT EXISTS boms (id INTEGER PRIMARY KEY, name TEXT, created REAL, boards INTEGER DEFAULT 1,
  notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS bom_lines (
  id INTEGER PRIMARY KEY, bom_id INTEGER NOT NULL REFERENCES boms(id) ON DELETE CASCADE,
  line INTEGER, designator TEXT DEFAULT '', qty INTEGER DEFAULT 1, value TEXT DEFAULT '', package TEXT DEFAULT '',
  mpn TEXT DEFAULT '', manufacturer TEXT DEFAULT '', name TEXT DEFAULT '', lcsc TEXT DEFAULT '',
  digikey TEXT DEFAULT '', mouser TEXT DEFAULT '', dnp INTEGER DEFAULT 0,
  part_id INTEGER REFERENCES parts(id) ON DELETE SET NULL, match TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS bl_bom ON bom_lines (bom_id);
CREATE TABLE IF NOT EXISTS scanned_labels (label_id TEXT PRIMARY KEY, part_id INTEGER, ts REAL, qty INTEGER, raw TEXT);
CREATE TABLE IF NOT EXISTS lcsc_cache (code TEXT PRIMARY KEY, ts REAL, data TEXT);
CREATE TABLE IF NOT EXISTS price_cache (supplier TEXT, key TEXT, ts REAL, data TEXT, PRIMARY KEY (supplier, key));
CREATE TABLE IF NOT EXISTS part_price (part_id INTEGER PRIMARY KEY REFERENCES parts(id) ON DELETE CASCADE,
  unit REAL, supplier TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '',
  note TEXT DEFAULT '', created REAL);
CREATE TABLE IF NOT EXISTS kho_users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
  customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  salt TEXT, it INTEGER, hash TEXT, created REAL, last_login REAL);
CREATE TABLE IF NOT EXISTS kho_sessions (key TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES kho_users(id) ON DELETE CASCADE, exp REAL);
"""


# ------------------------------------------------------------------ đọc mã vạch / QR trên nhãn
GS_CHARS = "\x1d\x1e\x04"   # phân cách trường của chuẩn ANSI MH10.8.2 (Digi-Key, Mouser DataMatrix)


def parse_label(code):
    """Nhận nội dung mã quét được -> dict {supplier, lcsc, digikey, mpn, qty, order, label_id, query}.

    - LCSC: QR dạng {pbn:PICK…,on:WM…,pc:C52711259,pm:CGA0603X7R104M500JT,qty:1500,…} (không phải JSON chuẩn)
    - Digi-Key / chuẩn ANSI MH10.8.2 (DataMatrix): [)>␞06␝P<mã DK>␝1P<MPN>␝…␝Q<số lượng>…
    - Mã LCSC trơn (C2040) hoặc link trang sản phẩm LCSC (…_C2040.html)
    - Còn lại: dùng làm từ khóa tìm kiếm.
    """
    code = str(code or "").strip()
    out = {"supplier": "", "lcsc": "", "digikey": "", "mouser": "", "mpn": "", "qty": 0, "order": "", "label_id": "",
           "query": ""}
    if not code:
        raise ValueError("Mã trống")
    if code.startswith("{") and re.search(r"[{,]\s*pc\s*:", code):
        d = {}
        for part in re.split(r",(?=\s*\w+\s*:)", code.strip().strip("{}")):
            k, _, v = part.partition(":")
            d[k.strip().lower()] = v.strip().strip('"')
        pc = d.get("pc", "").upper()
        out.update(supplier="lcsc" if pc else "", lcsc=pc, mpn=d.get("pm", ""), qty=_int(d.get("qty"), 0),
                   order=d.get("on", ""))
        # nhận diện nhãn theo mã đơn + mã LCSC (không dùng mã pick) để quét QR hay chụp chữ đều chống cộng trùng
        if d.get("on") and (pc or d.get("pm")):
            out["label_id"] = f"lcsc:{d['on']}:{pc or mpn_key(d.get('pm'))}"
        return out
    if code.startswith("[)>") or (sum(code.count(c) for c in GS_CHARS) >= 2):
        fields = [f for f in re.split("[" + GS_CHARS + "]", code) if f]
        info = {}
        for f in fields:
            for key in ("1P", "30P", "P", "Q", "1K", "10K", "11K", "1T", "4L", "11Z", "12Z", "13Z"):
                if f.startswith(key) and key not in info:
                    info[key] = f[len(key):]
                    break
        out.update(supplier="digikey", mpn=info.get("1P", ""), digikey=info.get("P", "") or info.get("30P", ""),
                   qty=_int(info.get("Q"), 0), order=info.get("1K", "") or info.get("10K", ""))
        if out["order"] or info.get("1T") or info.get("11K"):
            out["label_id"] = f"dk:{out['order']}:{info.get('11K', '')}:{info.get('1T', '')}:{out['digikey'] or out['mpn']}"
        return out
    m = re.search(r"\b(C\d{3,10})(?:\.html|\b)", code, re.I) if "lcsc" in code.lower() else None
    if LCSC_RE.match(code) or m:
        out.update(supplier="lcsc", lcsc=(m.group(1) if m else code).upper())
        return out
    out["query"] = code[:200]
    return out


class Kho:
    def __init__(self):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        self._backup()
        self.db = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for table in ("parts", "boms"):   # nâng cấp CSDL cũ: thêm chủ sở hữu (0 = của mình, >0 = id khách)
            cols = [r[1] for r in self.db.execute(f"PRAGMA table_info({table})")]
            if "owner_id" not in cols:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN owner_id INTEGER NOT NULL DEFAULT 0")
        self.db.execute("CREATE INDEX IF NOT EXISTS parts_owner ON parts (owner_id)")
        self.db.commit()
        self.lock = threading.RLock()
        self.pending = {}   # token -> (thời điểm, dữ liệu file đã đọc) chờ xác nhận nhập
        self.fails = {}     # ip -> [số lần sai, khóa tới] (đăng nhập tài khoản khách)

    def _backup(self):
        """Sao lưu kho.db mỗi ngày một bản (lúc server khởi động / mỗi lần ghi đầu tiên trong ngày)."""
        if not os.path.exists(DB_FILE):
            return
        dst = os.path.join(BACKUP_DIR, time.strftime("kho-%Y%m%d.db"))
        if not os.path.exists(dst):
            src = sqlite3.connect(DB_FILE)
            try:
                with sqlite3.connect(dst) as d:
                    src.backup(d)
            finally:
                src.close()
            for old in sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("kho-"))[:-KEEP_BACKUPS]:
                os.remove(os.path.join(BACKUP_DIR, old))

    def _q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # ------------------------------------------------------------ linh kiện
    def _suppliers_of(self, ids):
        if not ids:
            return {}
        out = {}
        for r in self._q(f"SELECT * FROM part_suppliers WHERE part_id IN ({','.join('?' * len(ids))}) ORDER BY id", ids):
            out.setdefault(r["part_id"], []).append(r)
        return out

    def _market_of(self, ids):
        """Giá thị trường rẻ nhất đã tra (đơn giá ở bậc số lượng nhỏ nhất) của từng linh kiện."""
        if not ids:
            return {}
        return {r["part_id"]: {"unit": r["unit"], "supplier": r["supplier"], "ts": r["ts"]} for r in self._q(
            f"SELECT * FROM part_price WHERE part_id IN ({','.join('?' * len(ids))})", ids)}

    def list_parts(self, q="", category="", location="", low=False, limit=200, offset=0, sort="updated", owner=None):
        """owner: None = mọi chủ sở hữu (quản lý), 0 = của mình, >0 = của khách đó."""
        where, args = [], []
        if owner is not None:
            where.append("p.owner_id = ?"); args.append(int(owner))
        if q:
            for word in q.split()[:6]:
                like = f"%{word}%"
                where.append("(p.mpn LIKE ? OR p.name LIKE ? OR p.value LIKE ? OR p.package LIKE ? OR p.manufacturer LIKE ?"
                             " OR p.category LIKE ? OR p.location LIKE ? OR p.notes LIKE ?"
                             " OR p.id IN (SELECT part_id FROM part_suppliers WHERE sku LIKE ? OR url LIKE ?))")
                args += [like] * 10
        if category:
            where.append("p.category = ?"); args.append(category)
        if location:
            where.append("p.location = ?"); args.append(location)
        if low:
            where.append("p.min_qty > 0 AND p.qty <= p.min_qty")
        w = ("WHERE " + " AND ".join(where)) if where else ""
        order = {"updated": "p.updated DESC", "mpn": "p.mpn COLLATE NOCASE", "qty": "p.qty",
                 "location": "p.location COLLATE NOCASE, p.mpn COLLATE NOCASE",
                 "category": "p.category COLLATE NOCASE, p.value COLLATE NOCASE"}.get(sort, "p.updated DESC")
        total = self._q(f"SELECT COUNT(*) n FROM parts p {w}", args)[0]["n"]
        items = self._q(f"SELECT p.*, c.name owner_name FROM parts p LEFT JOIN customers c ON c.id = p.owner_id {w} "
                        f"ORDER BY {order} LIMIT ? OFFSET ?",
                        args + [max(1, min(int(limit), 1000)), max(0, int(offset))])
        sup = self._suppliers_of([p["id"] for p in items])
        mk = self._market_of([p["id"] for p in items])
        for p in items:
            p["suppliers"] = sup.get(p["id"], [])
            p["market"] = mk.get(p["id"])
            p["low"] = p["min_qty"] > 0 and p["qty"] <= p["min_qty"]
        return {"items": items, "total": total}

    def get_part(self, pid, owner=None):
        rows = self._q("SELECT p.*, c.name owner_name FROM parts p LEFT JOIN customers c ON c.id = p.owner_id "
                       "WHERE p.id = ?", (pid,))
        if not rows or (owner is not None and rows[0]["owner_id"] != int(owner)):
            raise ValueError("Không có linh kiện này")
        p = rows[0]
        p["suppliers"] = self._suppliers_of([pid]).get(pid, [])
        p["market"] = self._market_of([pid]).get(pid)
        p["low"] = p["min_qty"] > 0 and p["qty"] <= p["min_qty"]
        p["log"] = self._q("SELECT * FROM stock_log WHERE part_id = ? ORDER BY ts DESC LIMIT 50", (pid,))
        p["boms"] = self._q("SELECT DISTINCT b.id, b.name, l.qty FROM bom_lines l JOIN boms b ON b.id = l.bom_id "
                            "WHERE l.part_id = ? ORDER BY b.created DESC", (pid,))
        return p

    def save_part(self, d):
        """Tạo mới (không có id) hoặc sửa. Đổi số lượng ở đây cũng được ghi vào lịch sử."""
        now = time.time()
        vals = {}
        for f in PART_FIELDS:
            if f in d:
                v = d[f]
                if f in ("qty", "min_qty"):
                    v = max(0, _int(v)) if f == "min_qty" else _int(v)
                elif f == "price":
                    v = _num(v)
                else:
                    v = str(v if v is not None else "").strip()[:500]
                vals[f] = v
        if "mpn" in vals:
            vals["mpn_key"] = mpn_key(vals["mpn"])
        if "owner_id" in d or not d.get("id"):
            vals["owner_id"] = self._check_owner(d.get("owner_id", 0))
        with self.lock:
            self._backup()
            pid = d.get("id")
            if pid:
                old = self._q("SELECT qty FROM parts WHERE id = ?", (pid,))
                if not old:
                    raise ValueError("Không có linh kiện này")
                if vals:
                    self.db.execute(f"UPDATE parts SET {', '.join(f + ' = ?' for f in vals)}, updated = ? WHERE id = ?",
                                    list(vals.values()) + [now, pid])
                if "qty" in vals and vals["qty"] != old[0]["qty"]:
                    self._log(pid, vals["qty"] - old[0]["qty"], vals["qty"], d.get("reason") or "Sửa số lượng")
            else:
                if not any(vals.get(k) for k in ("mpn", "name", "value")) and not d.get("suppliers"):
                    raise ValueError("Cần ít nhất MPN, tên hoặc giá trị")
                vals.setdefault("qty", 0)
                cur = self.db.execute(f"INSERT INTO parts ({', '.join(vals)}, created, updated) VALUES "
                                      f"({', '.join('?' * len(vals))}, ?, ?)", list(vals.values()) + [now, now])
                pid = cur.lastrowid
                # SQLite có thể dùng lại id của linh kiện đã xóa: dọn dữ liệu sót (nếu có) để không lẫn sang người khác
                self.db.execute("DELETE FROM stock_log WHERE part_id = ?", (pid,))
                self.db.execute("DELETE FROM part_suppliers WHERE part_id = ?", (pid,))
                self.db.execute("DELETE FROM part_price WHERE part_id = ?", (pid,))
                self.db.execute("UPDATE bom_lines SET part_id = NULL, match = '' WHERE part_id = ?", (pid,))
                if vals["qty"]:
                    self._log(pid, vals["qty"], vals["qty"], d.get("reason") or "Tạo mới")
            if "suppliers" in d:
                self.db.execute("DELETE FROM part_suppliers WHERE part_id = ?", (pid,))
                for s in d["suppliers"] or []:
                    sup = str(s.get("supplier", "other")).lower()
                    sku, url = str(s.get("sku", "")).strip()[:200], str(s.get("url", "")).strip()[:500]
                    if sup not in SUPPLIERS or not (sku or url):
                        continue
                    if sup == "lcsc":
                        sku = sku.upper()
                    self.db.execute("INSERT INTO part_suppliers (part_id, supplier, sku, url, price) VALUES (?,?,?,?,?)",
                                    (pid, sup, sku, url, _num(s.get("price"))))
            self.db.commit()
        return self.get_part(pid)

    def delete_part(self, pid):
        with self.lock:
            self._backup()
            self.db.execute("DELETE FROM parts WHERE id = ?", (pid,))
            self.db.execute("DELETE FROM part_price WHERE part_id = ?", (pid,))
            self.db.commit()

    def _log(self, pid, delta, after, reason, ref=""):
        self.db.execute("INSERT INTO stock_log (part_id, ts, delta, qty_after, reason, ref) VALUES (?,?,?,?,?,?)",
                        (pid, time.time(), delta, after, str(reason)[:200], str(ref)[:200]))

    def adjust(self, pid, delta=None, set_to=None, reason="", ref=""):
        with self.lock:
            self._backup()
            row = self._q("SELECT qty FROM parts WHERE id = ?", (pid,))
            if not row:
                raise ValueError("Không có linh kiện này")
            old = row[0]["qty"]
            new = _int(set_to) if set_to is not None else old + _int(delta)
            if new < 0:
                raise ValueError(f"Không đủ: trong kho còn {old}")
            if new != old:
                self.db.execute("UPDATE parts SET qty = ?, updated = ? WHERE id = ?", (new, time.time(), pid))
                self._log(pid, new - old, new, reason or ("Kiểm kê" if set_to is not None else
                                                           "Nhập" if new > old else "Xuất"), ref)
                self.db.commit()
        return self.get_part(pid)

    def meta(self, owner=None):
        w, a = ("WHERE owner_id = ?", (int(owner),)) if owner is not None else ("", ())
        aw = (w + " AND" if w else "WHERE")
        cnt = self._q("SELECT COUNT(*) n, COALESCE(SUM(qty),0) pcs, "
                      "COALESCE(SUM(qty * COALESCE(price, (SELECT unit FROM part_price pp WHERE pp.part_id = parts.id), 0)),0) value, "
                      "COALESCE(SUM(CASE WHEN min_qty > 0 AND qty <= min_qty THEN 1 ELSE 0 END),0) low, "
                      f"COALESCE(SUM(CASE WHEN qty <= 0 THEN 1 ELSE 0 END),0) out FROM parts {w}", a)[0]
        return {**cnt,
                "categories": [r["category"] for r in self._q(
                    f"SELECT category, COUNT(*) n FROM parts {aw} category != '' GROUP BY category ORDER BY n DESC", a)],
                "locations": [r["location"] for r in self._q(
                    f"SELECT location FROM parts {aw} location != '' GROUP BY location ORDER BY location COLLATE NOCASE", a)],
                "boms": self._q(f"SELECT COUNT(*) n FROM boms {w}", a)[0]["n"]}

    # ------------------------------------------------------------ tìm linh kiện theo mã
    def find(self, lcsc="", digikey="", mouser="", mpn="", value="", package="", owner=0):
        """Trả về (part_id, cách khớp) hoặc (None, ''). Chỉ tìm trong hàng của chủ sở hữu `owner`."""
        owner = int(owner or 0)
        for sup, sku in (("lcsc", lcsc), ("digikey", digikey), ("mouser", mouser)):
            sku = str(sku or "").strip()
            if sku:
                r = self._q("SELECT s.part_id FROM part_suppliers s JOIN parts p ON p.id = s.part_id "
                            "WHERE s.supplier = ? AND s.sku = ? COLLATE NOCASE AND p.owner_id = ? LIMIT 1",
                            (sup, sku.upper() if sup == "lcsc" else sku, owner))
                if r:
                    return r[0]["part_id"], sup
        k = mpn_key(mpn)
        if len(k) >= 3:
            r = self._q("SELECT id FROM parts WHERE mpn_key = ? AND owner_id = ? LIMIT 1", (k, owner))
            if r:
                return r[0]["id"], "mpn"
        if len(k) >= 6:   # OCR đọc nhầm O/0, S/5…: so khớp gần đúng
            fk = mpn_fuzzy(k)
            for row in self._q("SELECT id, mpn_key FROM parts WHERE mpn_key != '' AND length(mpn_key) = ? AND owner_id = ?",
                               (len(k), owner)):
                if mpn_fuzzy(row["mpn_key"]) == fk:
                    return row["id"], "mpn gần đúng"
        if value and package:
            r = self._q("SELECT id FROM parts WHERE value = ? COLLATE NOCASE AND package = ? COLLATE NOCASE "
                        "AND owner_id = ? ORDER BY qty DESC LIMIT 1", (value.strip(), package.strip(), owner))
            if r:
                return r[0]["id"], "value+package"
        return None, ""

    # ------------------------------------------------------------ đọc file: xem trước rồi xác nhận
    def preview(self, name, data, kind):
        rows = read_table(name, data)
        h = find_header(rows)
        headers = rows[h]
        mapping = guess_mapping(headers)
        token = secrets.token_hex(8)
        now = time.time()
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if now - v[0] < 1800}
            self.pending[token] = (now, {"name": name, "headers": headers, "rows": rows[h + 1:], "kind": kind})
        sample = parse_rows(rows[h + 1:h + 9], mapping)
        return {"token": token, "name": name, "headers": headers, "mapping": mapping, "fields": FIELD_LABELS,
                "rows": len([r for r in rows[h + 1:] if any(c.strip() for c in r)]), "sample": sample,
                "sample_raw": rows[h + 1:h + 9]}

    def _take(self, token, mapping):
        with self.lock:
            p = self.pending.get(token)
        if not p:
            raise ValueError("Phiên nhập file đã hết hạn, hãy chọn lại file")
        m = {f: int(i) for f, i in (mapping or {}).items() if f in FIELD_LABELS and i not in (None, "", -1, "-1")}
        return p[1], parse_rows(p[1]["rows"], m)

    def import_stock(self, token, mapping, mode="add", supplier="", location="", category="", ref="", owner=0):
        """Nhập đơn hàng / file kiểm kê. mode: add = cộng thêm, set = đặt đúng số lượng. Linh kiện chưa có thì tạo."""
        info, recs = self._take(token, mapping)
        owner = self._check_owner(owner)
        created, updated, skipped = 0, 0, []
        with self.lock:
            self._backup()
            for r in recs:
                qty = _int(r.get("qty"), 0)
                if r.get("supplier_part") and supplier in ("digikey", "mouser") and not r.get(supplier):
                    r[supplier] = r["supplier_part"]
                pid, _ = self.find(r.get("lcsc"), r.get("digikey"), r.get("mouser"), r.get("mpn"), owner=owner)
                sups = [{"supplier": s, "sku": r[s], "price": r.get("price")} for s in ("lcsc", "digikey", "mouser")
                        if r.get(s)]
                if r.get("taobao"):
                    sups.append({"supplier": "taobao", "url": r["taobao"], "sku": "", "price": r.get("price")})
                if pid is None:
                    if not any(r.get(k) for k in ("mpn", "lcsc", "digikey", "mouser", "name", "value")):
                        skipped.append(r); continue
                    d = {f: r.get(f, "") for f in ("mpn", "manufacturer", "name", "package", "value")}
                    d.update(category=r.get("category") or category, location=r.get("location") or location,
                             qty=qty, price=r.get("price"), suppliers=sups, reason=f"Nhập file {info['name']}",
                             owner_id=owner)
                    if r.get("min_qty"):
                        d["min_qty"] = r["min_qty"]
                    self.save_part(d)
                    created += 1
                else:
                    old = self.get_part(pid)
                    # bổ sung thông tin còn trống + mã nhà cung cấp mới
                    fill = {f: r[f] for f in ("mpn", "manufacturer", "name", "package", "value", "category", "location")
                            if r.get(f) and not old.get(f)}
                    have = {(s["supplier"], s["sku"].upper(), s["url"]) for s in old["suppliers"]}
                    new_sups = [s for s in sups if (s["supplier"], str(s.get("sku", "")).upper(), s.get("url", "")) not in have]
                    if fill or new_sups:
                        self.save_part({"id": pid, **fill, **({"suppliers": old["suppliers"] + new_sups} if new_sups else {})})
                    if mode == "set":
                        self.adjust(pid, set_to=qty, reason=f"Kiểm kê từ file {info['name']}", ref=ref)
                    elif qty:
                        self.adjust(pid, delta=qty, reason=f"Nhập từ {info['name']}", ref=ref)
                    updated += 1
            self.pending.pop(token, None)
        return {"created": created, "updated": updated, "skipped": len(skipped), "total": len(recs)}

    # ------------------------------------------------------------ BOM
    def bom_create(self, token, mapping, name="", boards=1, owner=0):
        info, recs = self._take(token, mapping)
        owner = self._check_owner(owner)
        if not recs:
            raise ValueError("Không đọc được dòng nào trong BOM")
        now = time.time()
        with self.lock:
            self._backup()
            cur = self.db.execute("INSERT INTO boms (name, created, boards, owner_id) VALUES (?, ?, ?, ?)",
                                  ((name or info["name"]).strip()[:120], now, max(1, _int(boards, 1)), owner))
            bid = cur.lastrowid
            for i, r in enumerate(recs, 1):
                des = r.get("designator", "")
                qty = _int(r.get("qty"), 0) or (len([x for x in re.split(r"[,;\s]+", des) if x]) if des else 1)
                dnp = str(r.get("dnp", "")).strip().lower() in ("1", "x", "yes", "true", "dnp", "dnf")
                pid, how = self.find(r.get("lcsc"), r.get("digikey"), r.get("mouser"), r.get("mpn"),
                                     r.get("value"), r.get("package"), owner=owner)
                self.db.execute(
                    "INSERT INTO bom_lines (bom_id, line, designator, qty, value, package, mpn, manufacturer, name, lcsc, "
                    "digikey, mouser, dnp, part_id, match) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (bid, i, des[:2000], qty, r.get("value", "")[:200], r.get("package", "")[:200], r.get("mpn", "")[:200],
                     r.get("manufacturer", "")[:200], r.get("name", "")[:500], r.get("lcsc", ""), r.get("digikey", ""),
                     r.get("mouser", ""), int(dnp), pid, how))
            self.db.commit()
            self.pending.pop(token, None)
        return self.bom(bid)

    def boms(self, owner=None):
        w, a = ("WHERE b.owner_id = ?", (int(owner),)) if owner is not None else ("", ())
        return self._q("SELECT b.*, c.name owner_name, COUNT(l.id) lines, "
                       "SUM(CASE WHEN l.part_id IS NULL AND l.dnp = 0 THEN 1 ELSE 0 END) unmatched "
                       "FROM boms b LEFT JOIN bom_lines l ON l.bom_id = b.id LEFT JOIN customers c ON c.id = b.owner_id "
                       f"{w} GROUP BY b.id ORDER BY b.created DESC", a)

    def _bom_owner(self, bid, owner=None):
        """Chủ sở hữu của BOM; báo lỗi nếu `owner` (khách) không phải chủ."""
        r = self._q("SELECT owner_id FROM boms WHERE id = ?", (bid,))
        if not r or (owner is not None and r[0]["owner_id"] != int(owner)):
            raise ValueError("Không có BOM này")
        return r[0]["owner_id"]

    def bom(self, bid, boards=None, owner=None):
        self._bom_owner(bid, owner)
        b = self._q("SELECT b.*, c.name owner_name FROM boms b LEFT JOIN customers c ON c.id = b.owner_id "
                    "WHERE b.id = ?", (bid,))
        b = b[0]
        n = max(1, _int(boards, b["boards"])) if boards is not None else b["boards"]
        lines = self._q("SELECT l.*, p.mpn p_mpn, p.name p_name, p.value p_value, p.package p_package, p.qty p_qty, "
                        "p.location p_location, p.min_qty p_min, p.price p_price FROM bom_lines l "
                        "LEFT JOIN parts p ON p.id = l.part_id WHERE l.bom_id = ? ORDER BY l.line", (bid,))
        # cùng một linh kiện dùng ở nhiều dòng: cộng dồn nhu cầu để tính thiếu cho đúng
        need_by_part = {}
        for ln in lines:
            if ln["part_id"] and not ln["dnp"]:
                need_by_part[ln["part_id"]] = need_by_part.get(ln["part_id"], 0) + ln["qty"] * n
        s = {"lines": 0, "ok": 0, "short": 0, "missing": 0, "dnp": 0, "cost_short": 0.0}
        for ln in lines:
            ln["need"] = 0 if ln["dnp"] else ln["qty"] * n
            if ln["dnp"]:
                ln["status"] = "dnp"; s["dnp"] += 1; ln["have"] = ln["p_qty"]; ln["short"] = 0
                continue
            s["lines"] += 1
            if not ln["part_id"]:
                ln["status"], ln["have"], ln["short"] = "missing", 0, ln["need"]
                s["missing"] += 1
                continue
            have = ln["p_qty"] or 0
            total_need = need_by_part[ln["part_id"]]
            ln["have"], ln["total_need"] = have, total_need
            ln["short"] = max(0, min(ln["need"], total_need - have))
            ln["status"] = "ok" if have >= total_need else "short"
            s["ok" if ln["status"] == "ok" else "short"] += 1
            if ln["short"] and ln["p_price"]:
                s["cost_short"] += ln["short"] * ln["p_price"]
        s["cost_short"] = round(s["cost_short"], 2)
        s["buildable"] = self._buildable(lines) if not s["missing"] else 0
        return {**b, "boards_view": n, "lines": lines, "summary": s}

    @staticmethod
    def _buildable(lines):
        per_part = {}
        for ln in lines:
            if ln["part_id"] and not ln["dnp"] and ln["qty"] > 0:
                per_part.setdefault(ln["part_id"], [0, ln["p_qty"] or 0])
                per_part[ln["part_id"]][0] += ln["qty"]
        if not per_part:
            return 0
        return max(0, min(have // need for need, have in per_part.values()))

    def bom_update(self, bid, name=None, boards=None, notes=None, owner=None):
        self._bom_owner(bid, owner)
        sets, args = [], []
        for k, v in (("name", name), ("boards", boards), ("notes", notes)):
            if v is not None:
                sets.append(f"{k} = ?"); args.append(max(1, _int(v, 1)) if k == "boards" else str(v)[:500])
        if sets:
            with self.lock:
                self.db.execute(f"UPDATE boms SET {', '.join(sets)} WHERE id = ?", args + [bid])
                self.db.commit()
        return self.bom(bid)

    def bom_set_line(self, line_id, part_id=None, qty=None, dnp=None, owner=None):
        r = self._q("SELECT bom_id FROM bom_lines WHERE id = ?", (line_id,))
        if not r:
            raise ValueError("Không có dòng này")
        bom_owner = self._bom_owner(r[0]["bom_id"], owner)
        if part_id:   # chỉ được khớp với linh kiện của cùng chủ sở hữu
            self.get_part(int(part_id), bom_owner)
        with self.lock:
            if part_id is not None:
                self.db.execute("UPDATE bom_lines SET part_id = ?, match = ? WHERE id = ?",
                                (part_id or None, "tay" if part_id else "", line_id))
            if qty is not None:
                self.db.execute("UPDATE bom_lines SET qty = ? WHERE id = ?", (max(0, _int(qty)), line_id))
            if dnp is not None:
                self.db.execute("UPDATE bom_lines SET dnp = ? WHERE id = ?", (int(bool(dnp)), line_id))
            self.db.commit()
            r = self._q("SELECT bom_id FROM bom_lines WHERE id = ?", (line_id,))
        if not r:
            raise ValueError("Không có dòng này")
        return self.bom(r[0]["bom_id"])

    def bom_rematch(self, bid, owner=None):
        """Khớp lại các dòng chưa khớp (sau khi đã thêm linh kiện vào kho)."""
        bom_owner = self._bom_owner(bid, owner)
        with self.lock:
            for ln in self._q("SELECT * FROM bom_lines WHERE bom_id = ? AND part_id IS NULL", (bid,)):
                pid, how = self.find(ln["lcsc"], ln["digikey"], ln["mouser"], ln["mpn"], ln["value"], ln["package"],
                                     owner=bom_owner)
                if pid:
                    self.db.execute("UPDATE bom_lines SET part_id = ?, match = ? WHERE id = ?", (pid, how, ln["id"]))
            self.db.commit()
        return self.bom(bid)

    def bom_add_missing(self, bid):
        """Tạo linh kiện (số lượng 0) cho các dòng chưa có trong kho, để theo dõi / đặt mua."""
        bom_owner = self._bom_owner(bid)
        made = 0
        for ln in self._q("SELECT * FROM bom_lines WHERE bom_id = ? AND part_id IS NULL AND dnp = 0", (bid,)):
            sups = [{"supplier": s, "sku": ln[s]} for s in ("lcsc", "digikey", "mouser") if ln[s]]
            p = self.save_part({"mpn": ln["mpn"], "manufacturer": ln["manufacturer"], "name": ln["name"],
                                "value": ln["value"], "package": ln["package"], "qty": 0, "suppliers": sups,
                                "owner_id": bom_owner})
            with self.lock:
                self.db.execute("UPDATE bom_lines SET part_id = ?, match = 'tạo mới' WHERE id = ?", (p["id"], ln["id"]))
                self.db.commit()
            made += 1
        return {**self.bom(bid), "added": made}

    def bom_consume(self, bid, boards):
        """Lắp N bo: trừ kho tất cả linh kiện của BOM (dừng nếu thiếu)."""
        b = self.bom(bid, boards)
        if b["summary"]["missing"] or b["summary"]["short"]:
            raise ValueError("Còn linh kiện thiếu / chưa khớp, không trừ kho được")
        n = b["boards_view"]
        with self.lock:
            self._backup()
            per_part = {}
            for ln in b["lines"]:
                if ln["part_id"] and not ln["dnp"] and ln["need"]:
                    per_part[ln["part_id"]] = per_part.get(ln["part_id"], 0) + ln["need"]
            for pid, need in per_part.items():
                self.adjust(pid, delta=-need, reason=f"Lắp {n} bo {b['name']}", ref=f"bom:{bid}")
        return self.bom(bid)

    def bom_delete(self, bid, owner=None):
        self._bom_owner(bid, owner)
        with self.lock:
            self.db.execute("DELETE FROM boms WHERE id = ?", (bid,))
            self.db.commit()

    def bom_shortage_csv(self, bid, boards=None, supplier="lcsc", owner=None):
        """CSV linh kiện cần mua. supplier=lcsc: định dạng dán vào BOM Tool / giỏ hàng LCSC (mã, số lượng)."""
        b = self.bom(bid, boards, owner)
        out = io.StringIO()
        w = csv.writer(out)
        sups = self._suppliers_of(list({ln["part_id"] for ln in b["lines"] if ln["part_id"]}))
        if supplier == "lcsc":
            w.writerow(["LCSC Part Number", "Quantity", "MPN", "Designator"])
        else:
            w.writerow(["Quantity", "MPN", "Manufacturer", "Value", "Package", "LCSC", "Digi-Key", "Mouser", "Designator"])
        for ln in b["lines"]:
            if not ln["short"]:
                continue
            codes = {s["supplier"]: s["sku"] for s in sups.get(ln["part_id"], [])}
            lcsc = codes.get("lcsc") or ln["lcsc"]
            mpn = ln["p_mpn"] or ln["mpn"]
            if supplier == "lcsc":
                w.writerow([lcsc, ln["short"], mpn, ln["designator"]])
            else:
                w.writerow([ln["short"], mpn, ln["manufacturer"], ln["value"], ln["package"], lcsc,
                            codes.get("digikey") or ln["digikey"], codes.get("mouser") or ln["mouser"], ln["designator"]])
        return out.getvalue()

    # ------------------------------------------------------------ xuất toàn bộ kho
    def export_csv(self, owner=None):
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["ID", "Owner", "MPN", "Manufacturer", "Description", "Category", "Value", "Package", "Location", "Quantity",
                    "Min Qty", "Unit Price", "LCSC", "Digi-Key", "Mouser", "Taobao", "Datasheet", "Notes"])
        wh, a = ("WHERE p.owner_id = ?", (int(owner),)) if owner is not None else ("", ())
        parts = self._q("SELECT p.*, c.name owner_name FROM parts p LEFT JOIN customers c ON c.id = p.owner_id "
                        f"{wh} ORDER BY p.owner_id, p.category, p.value, p.mpn", a)
        sups = self._suppliers_of([p["id"] for p in parts])
        for p in parts:
            c = {}
            for s in sups.get(p["id"], []):
                c.setdefault(s["supplier"], s["url"] if s["supplier"] == "taobao" else s["sku"])
            w.writerow([p["id"], p["owner_name"] or "Của tôi", p["mpn"], p["manufacturer"], p["name"], p["category"], p["value"], p["package"],
                        p["location"], p["qty"], p["min_qty"], p["price"] if p["price"] is not None else "",
                        c.get("lcsc", ""), c.get("digikey", ""), c.get("mouser", ""), c.get("taobao", ""),
                        p["datasheet"], p["notes"]])
        return "﻿" + out.getvalue()     # BOM UTF-8 để Excel mở đúng tiếng Việt


# ------------------------------------------------------------------ thông tin sản phẩm LCSC + quét nhãn
LCSC_API = "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={}"
LCSC_CACHE_DAYS = 30


def _lcsc_to_part(r):
    """Kết quả API LCSC -> các trường linh kiện."""
    main = next((p for p in (r.get("paramVOList") or []) if p.get("isMain")), None)
    prices = r.get("productPriceList") or []
    return {k: v for k, v in {
        "mpn": r.get("productModel") or "",
        "manufacturer": r.get("brandNameEn") or "",
        "package": r.get("encapStandard") or "",
        "category": r.get("catalogName") or r.get("parentCatalogName") or "",
        "name": (r.get("productIntroEn") or "").replace(" RoHS", "").strip(),
        "value": (main or {}).get("paramValueEn") or "",
        "datasheet": (r.get("pdfUrl") or "").split("?")[0],
        "image": (r.get("productImages") or [""])[0],
        "price": prices[0].get("usdPrice") if prices else None,
    }.items() if v not in ("", None)}


def lcsc_info(self, code, refresh=False):
    """Tra thông tin sản phẩm LCSC (API của trang lcsc.com, có thể đổi bất cứ lúc nào), lưu đệm 30 ngày."""
    code = str(code or "").strip().upper()
    if not LCSC_RE.match(code):
        raise ValueError("Mã LCSC phải dạng C12345")
    if not refresh:
        row = self._q("SELECT ts, data FROM lcsc_cache WHERE code = ?", (code,))
        if row and time.time() - row[0]["ts"] < LCSC_CACHE_DAYS * 86400:
            return json.loads(row[0]["data"])
    req = urllib.request.Request(LCSC_API.format(code), headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        j = json.loads(resp.read().decode("utf-8", "replace"))
    r = j.get("result") if isinstance(j, dict) else None
    if not r:
        raise ValueError(f"LCSC không có mã {code}")
    info = _lcsc_to_part(r)
    with self.lock:
        self.db.execute("INSERT OR REPLACE INTO lcsc_cache VALUES (?, ?, ?)", (code, time.time(), json.dumps(info)))
        self.db.commit()
    return info


def scan(self, code, owner=0):
    """Đọc mã quét -> linh kiện khớp trong kho của `owner` (nếu có), nhãn đã nhập chưa, gợi ý thông tin từ LCSC."""
    owner = self._check_owner(owner)
    lab = parse_label(code)
    res = {"label": lab, "part": None, "already": None, "lcsc_info": None, "lcsc_error": "", "results": []}
    if lab["query"]:
        res["results"] = self.list_parts(lab["query"], limit=20, owner=owner)["items"]
        if len(res["results"]) == 1:
            res["part"] = res["results"][0]
        return res
    pid, how = self.find(lab["lcsc"], lab["digikey"], lab["mouser"], lab["mpn"], owner=owner)
    if pid:
        res["part"], res["match"] = self.get_part(pid), how
    if lab["label_id"]:
        row = self._q("SELECT * FROM scanned_labels WHERE label_id = ?", (lab["label_id"],))
        res["already"] = row[0] if row else None
    if lab["lcsc"] and not pid:
        try:
            res["lcsc_info"] = self.lcsc_info(lab["lcsc"])
        except Exception as e:  # noqa: BLE001 - không tra được LCSC thì vẫn tạo tay được
            res["lcsc_error"] = str(e)[:200]
    return res


def scan_apply(self, code, action, qty=None, part_id=None, fields=None, owner=0):
    """action: add = cộng số lượng nhãn vào linh kiện (part_id hoặc tự khớp); create = tạo linh kiện mới rồi nhập."""
    lab = parse_label(code)
    owner = self._check_owner(owner)
    n = _int(qty, lab["qty"]) if qty not in (None, "") else lab["qty"]
    ref = lab["order"] or ""
    sups = [{"supplier": s, "sku": lab[s]} for s in ("lcsc", "digikey", "mouser") if lab[s]]
    with self.lock:
        if action == "create":
            d = {"mpn": lab["mpn"], "qty": 0, "suppliers": sups, "owner_id": owner}
            if lab["lcsc"]:
                try:
                    d.update(self.lcsc_info(lab["lcsc"]))
                except Exception:  # noqa: BLE001
                    pass
            d.update({k: v for k, v in (fields or {}).items() if k in PART_FIELDS and v not in (None, "")})
            d["qty"], d["owner_id"] = 0, owner
            part_id = self.save_part(d)["id"]
        else:
            if not part_id:
                part_id, _ = self.find(lab["lcsc"], lab["digikey"], lab["mouser"], lab["mpn"], owner=owner)
            if not part_id:
                raise ValueError("Không tìm thấy linh kiện trong kho: chọn “Tạo mới”")
            p = self.get_part(part_id)
            have = {(s["supplier"], s["sku"].upper()) for s in p["suppliers"]}
            new = [s for s in sups if (s["supplier"], s["sku"].upper()) not in have]
            extra = {k: v for k, v in (fields or {}).items() if k in ("location", "min_qty", "category") and v not in (None, "")}
            if new or extra:
                self.save_part({"id": part_id, **extra, **({"suppliers": p["suppliers"] + new} if new else {})})
        if n:
            src = {"lcsc": "LCSC", "digikey": "Digi-Key"}.get(lab["supplier"], "nhãn")
            self.adjust(part_id, delta=n, reason=f"Quét nhãn {src}", ref=ref)
        if lab["label_id"]:
            self.db.execute("INSERT OR REPLACE INTO scanned_labels VALUES (?, ?, ?, ?, ?)",
                            (lab["label_id"], part_id, time.time(), n, str(code)[:500]))
            self.db.commit()
    return self.get_part(part_id)


def fill_from_lcsc(self, pid, overwrite=False):
    """Điền các trường còn trống của linh kiện từ thông tin LCSC (theo mã LCSC đã lưu)."""
    p = self.get_part(pid)
    code = next((s["sku"] for s in p["suppliers"] if s["supplier"] == "lcsc" and s["sku"]), "")
    if not code:
        raise ValueError("Linh kiện chưa có mã LCSC")
    info = self.lcsc_info(code, refresh=True)
    upd = {k: v for k, v in info.items() if overwrite or not p.get(k)}
    return self.save_part({"id": pid, **upd}) if upd else p


Kho.lcsc_info = lcsc_info
Kho.scan = scan
Kho.scan_apply = scan_apply
Kho.fill_from_lcsc = fill_from_lcsc


# ------------------------------------------------------------------ giá theo nhà cung cấp (LCSC, Digi-Key)
PRICE_CACHE_HOURS = 24
DIGIKEY_CONF = os.environ.get("KHO_DIGIKEY_CONF", "/etc/bpi-digikey.json")   # {"client_id", "client_secret"} — chỉ trên board
DIGIKEY_API = "https://api.digikey.com"
_dk_token = {"value": "", "exp": 0}
_dk_lock = threading.Lock()


def _http_json(url, data=None, headers=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        try:
            j = json.loads(body)
            body = j.get("detail") or j.get("title") or j.get("ErrorMessage") or j.get("error_description") or body
        except ValueError:
            pass
        raise OSError(f"HTTP {e.code}: {body}") from None


def _price_lcsc(code):
    j = _http_json(LCSC_API.format(urllib.parse.quote(code)))
    r = j.get("result") if isinstance(j, dict) else None
    if not r:
        raise ValueError(f"LCSC không có mã {code}")
    tiers = [[int(t.get("ladder") or 1), float(t.get("usdPrice") or t.get("currencyPrice") or 0)]
             for t in (r.get("productPriceList") or []) if t.get("usdPrice") or t.get("currencyPrice")]
    return {"tiers": sorted(tiers), "currency": "USD", "stock": r.get("stockNumber"), "moq": r.get("minBuyNumber"),
            "mult": r.get("minPacketNumber") if r.get("minPacketUnit") != "Reel" else None,
            "sku": code, "mpn": r.get("productModel") or "",
            "url": f"https://www.lcsc.com/product-detail/{urllib.parse.quote(code)}.html"}


def digikey_conf():
    try:
        with open(DIGIKEY_CONF, encoding="utf-8") as f:
            c = json.load(f)
        return c if c.get("client_id") and c.get("client_secret") else None
    except (OSError, ValueError):
        return None


def digikey_save_conf(client_id, client_secret):
    client_id, client_secret = str(client_id or "").strip(), str(client_secret or "").strip()
    if not client_id and not client_secret:   # xóa khóa
        try:
            os.remove(DIGIKEY_CONF)
        except OSError:
            pass
        return {"configured": False}
    if not client_id or not client_secret:
        raise ValueError("Cần cả Client ID và Client Secret")
    tmp = DIGIKEY_CONF + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"client_id": client_id, "client_secret": client_secret}, f)
    os.replace(tmp, DIGIKEY_CONF)
    with _dk_lock:
        _dk_token.update(value="", exp=0)
    try:
        _dk_access_token()   # thử luôn: sai khóa thì báo ngay và không lưu
    except Exception:
        os.remove(DIGIKEY_CONF)
        raise
    return {"configured": True}


def _dk_access_token():
    c = digikey_conf()
    if not c:
        raise ValueError("Chưa nhập khóa API Digi-Key (Client ID / Secret)")
    with _dk_lock:
        if _dk_token["value"] and _dk_token["exp"] > time.time() + 60:
            return c, _dk_token["value"]
        body = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"],
                                       "grant_type": "client_credentials"}).encode()
        j = _http_json(DIGIKEY_API + "/v1/oauth2/token", body, {"Content-Type": "application/x-www-form-urlencoded"})
        _dk_token.update(value=j["access_token"], exp=time.time() + int(j.get("expires_in", 600)))
        return c, _dk_token["value"]


def _price_digikey(key):
    """key: mã Digi-Key (296-1234-1-ND) hoặc MPN. API Product Information v4."""
    c, tok = _dk_access_token()
    j = _http_json(f"{DIGIKEY_API}/products/v4/search/{urllib.parse.quote(key, safe='')}/productdetails", headers={
        "X-DIGIKEY-Client-Id": c["client_id"], "Authorization": "Bearer " + tok,
        "X-DIGIKEY-Locale-Site": "US", "X-DIGIKEY-Locale-Language": "en", "X-DIGIKEY-Locale-Currency": "USD"})
    p = j.get("Product") or {}
    if not p:
        raise ValueError(f"Digi-Key không có {key}")
    vs = [v for v in (p.get("ProductVariations") or []) if v.get("StandardPricing")]
    want = key.upper()
    v = next((v for v in vs if (v.get("DigiKeyProductNumber") or "").upper() == want), None) or \
        min(vs, key=lambda v: (v.get("MinimumOrderQuantity") or 1, -(v.get("QuantityAvailableforPackageType") or 0)), default=None)
    if not v:
        raise ValueError(f"Digi-Key không có giá cho {key}")
    tiers = sorted([int(t["BreakQuantity"]), float(t["UnitPrice"])] for t in v["StandardPricing"] if t.get("UnitPrice"))
    return {"tiers": tiers, "currency": "USD", "stock": p.get("QuantityAvailable"),
            "moq": v.get("MinimumOrderQuantity"), "mult": None, "sku": v.get("DigiKeyProductNumber") or key,
            "package": (v.get("PackageType") or {}).get("Name", ""),
            "mpn": p.get("ManufacturerProductNumber") or "", "url": p.get("ProductUrl") or ""}


PRICE_SOURCES = {"lcsc": _price_lcsc, "digikey": _price_digikey}


def supplier_price(self, supplier, key, refresh=False):
    key = str(key or "").strip()
    if not refresh:
        row = self._q("SELECT ts, data FROM price_cache WHERE supplier = ? AND key = ?", (supplier, key.upper()))
        if row and time.time() - row[0]["ts"] < PRICE_CACHE_HOURS * 3600:
            return {**json.loads(row[0]["data"]), "ts": row[0]["ts"]}
    d = PRICE_SOURCES[supplier](key)
    now = time.time()
    with self.lock:
        self.db.execute("INSERT OR REPLACE INTO price_cache VALUES (?, ?, ?, ?)", (supplier, key.upper(), now, json.dumps(d)))
        self.db.commit()
    return {**d, "ts": now}


def price_at(tiers, qty):
    """Đơn giá khi mua `qty` con (bậc lớn nhất ≤ qty; dưới bậc đầu thì lấy bậc đầu)."""
    if not tiers:
        return None
    best = tiers[0][1]
    for q, pr in tiers:
        if qty >= q:
            best = pr
    return best


def part_prices(self, pid, refresh=False, owner=None):
    """Giá của linh kiện ở từng nhà cung cấp: LCSC theo mã C…, Digi-Key theo mã Digi-Key, hoặc theo MPN nếu có khóa API."""
    p = self.get_part(pid, owner)
    jobs = [(s["supplier"], s["sku"]) for s in p["suppliers"] if s["supplier"] in PRICE_SOURCES and s["sku"]]
    if not any(j[0] == "digikey" for j in jobs) and p["mpn"] and digikey_conf():
        jobs.append(("digikey", p["mpn"]))
    out = []
    for sup, key in dict.fromkeys(jobs):
        try:
            d = self.supplier_price(sup, key, refresh)
            out.append({"supplier": sup, "key": key, **d, "unit": d["tiers"][0][1] if d["tiers"] else None})
        except Exception as e:  # noqa: BLE001 - một nhà cung cấp lỗi thì vẫn hiện nhà khác
            out.append({"supplier": sup, "key": key, "error": str(e)[:200]})
    ok = [o for o in out if o.get("unit")]
    with self.lock:
        if ok:
            b = min(ok, key=lambda o: o["unit"])
            self.db.execute("INSERT OR REPLACE INTO part_price VALUES (?, ?, ?, ?)", (pid, b["unit"], b["supplier"], time.time()))
        elif not any("error" in o for o in out):
            self.db.execute("DELETE FROM part_price WHERE part_id = ?", (pid,))
        self.db.commit()
    return {"part_id": pid, "prices": out, "market": self._market_of([pid]).get(pid),
            "digikey_configured": bool(digikey_conf())}


_price_job = {"running": False, "done": 0, "total": 0, "errors": 0, "started": 0, "finished": 0, "last_error": ""}


def refresh_all_prices(self, owner=None, force=False):
    """Cập nhật giá mọi linh kiện có mã LCSC / Digi-Key (hoặc MPN khi có khóa Digi-Key), chạy nền."""
    if _price_job["running"]:
        return dict(_price_job)
    w, a = ("WHERE p.owner_id = ?", [int(owner)]) if owner is not None else ("", [])
    if digikey_conf():
        ids = [r["id"] for r in self._q(f"SELECT p.id FROM parts p {w} ORDER BY p.id", a)]
    else:
        ids = [r["id"] for r in self._q(f"SELECT DISTINCT p.id FROM parts p JOIN part_suppliers s ON s.part_id = p.id "
                                        f"AND s.supplier = 'lcsc' AND s.sku != '' {w} ORDER BY p.id", a)]
    _price_job.update(running=True, done=0, total=len(ids), errors=0, started=time.time(), finished=0, last_error="")

    def run():
        try:
            for pid in ids:
                try:
                    r = self.part_prices(pid, refresh=force)
                    errs = [o["error"] for o in r["prices"] if "error" in o]
                    if errs:
                        _price_job["errors"] += 1
                        _price_job["last_error"] = errs[0]
                except Exception as e:  # noqa: BLE001
                    _price_job["errors"] += 1
                    _price_job["last_error"] = str(e)[:200]
                _price_job["done"] += 1
                time.sleep(0.4)   # nhẹ tay với API của nhà cung cấp
        finally:
            _price_job.update(running=False, finished=time.time())
    threading.Thread(target=run, daemon=True).start()
    return dict(_price_job)


def price_job_status(self):
    return {**_price_job, "digikey_configured": bool(digikey_conf())}


Kho.supplier_price = supplier_price
Kho.part_prices = part_prices
Kho.refresh_all_prices = refresh_all_prices
Kho.price_job_status = price_job_status

# ------------------------------------------------------------------ khách + tài khoản khách
PBKDF2_ITER, SESSION_DAYS, MAX_FAILS, LOCK_SECONDS = 200_000, 30, 5, 300
KHO_COOKIE = "bpi_kho"


def _pw_hash(pw, salt, it):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), it).hex()


def _check_owner(self, owner):
    """0 = của mình; >0 phải là id khách có thật."""
    o = _int(owner, 0)
    if o and not self._q("SELECT 1 FROM customers WHERE id = ?", (o,)):
        raise ValueError("Không có khách này")
    return o


def customers(self):
    rows = self._q("SELECT c.*, (SELECT COUNT(*) FROM parts p WHERE p.owner_id = c.id) parts, "
                   "(SELECT COALESCE(SUM(qty),0) FROM parts p WHERE p.owner_id = c.id) pcs, "
                   "(SELECT COUNT(*) FROM boms b WHERE b.owner_id = c.id) boms FROM customers c ORDER BY c.name COLLATE NOCASE")
    users = {}
    for u in self._q("SELECT id, username, customer_id, created, last_login FROM kho_users ORDER BY username"):
        users.setdefault(u["customer_id"], []).append(u)
    for c in rows:
        c["users"] = users.get(c["id"], [])
    return rows


def save_customer(self, d):
    name = str(d.get("name", "")).strip()[:100]
    if not name:
        raise ValueError("Cần tên khách")
    vals = (name, str(d.get("phone", "")).strip()[:50], str(d.get("note", "")).strip()[:300])
    with self.lock:
        if d.get("id"):
            self._check_owner(d["id"])
            self.db.execute("UPDATE customers SET name = ?, phone = ?, note = ? WHERE id = ?", vals + (int(d["id"]),))
            cid = int(d["id"])
        else:
            cid = self.db.execute("INSERT INTO customers (name, phone, note, created) VALUES (?, ?, ?, ?)",
                                  vals + (time.time(),)).lastrowid
        self.db.commit()
    return next(c for c in self.customers() if c["id"] == cid)


def delete_customer(self, cid):
    cid = self._check_owner(cid)
    n = self._q("SELECT (SELECT COUNT(*) FROM parts WHERE owner_id = ?) + (SELECT COUNT(*) FROM boms WHERE owner_id = ?) n",
                (cid, cid))[0]["n"]
    if n:
        raise ValueError("Khách còn linh kiện / BOM trong kho: chuyển hoặc xóa trước")
    with self.lock:
        self.db.execute("DELETE FROM customers WHERE id = ?", (cid,))
        self.db.commit()


def save_user(self, customer_id, username, password=""):
    """Tạo tài khoản khách (hoặc đặt lại mật khẩu nếu đã có). Mật khẩu trống -> tự tạo, trả về 1 lần."""
    cid = self._check_owner(customer_id)
    if not cid:
        raise ValueError("Chọn khách cho tài khoản")
    username = str(username or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,31}", username):
        raise ValueError("Tên đăng nhập: 3–32 ký tự chữ thường, số, . _ -")
    pw = str(password or "") or secrets.token_urlsafe(9)
    if len(pw) < 6:
        raise ValueError("Mật khẩu ít nhất 6 ký tự")
    salt = secrets.token_hex(16)
    with self.lock:
        row = self._q("SELECT id, customer_id FROM kho_users WHERE username = ?", (username,))
        if row:
            if row[0]["customer_id"] != cid:
                raise ValueError("Tên đăng nhập đã dùng cho khách khác")
            self.db.execute("UPDATE kho_users SET salt = ?, it = ?, hash = ? WHERE id = ?",
                            (salt, PBKDF2_ITER, _pw_hash(pw, salt, PBKDF2_ITER), row[0]["id"]))
            self.db.execute("DELETE FROM kho_sessions WHERE user_id = ?", (row[0]["id"],))   # đăng xuất máy cũ
        else:
            self.db.execute("INSERT INTO kho_users (username, customer_id, salt, it, hash, created) VALUES (?,?,?,?,?,?)",
                            (username, cid, salt, PBKDF2_ITER, _pw_hash(pw, salt, PBKDF2_ITER), time.time()))
        self.db.commit()
    return {"username": username, "password": pw, "customer_id": cid}


def delete_user(self, username):
    with self.lock:
        self.db.execute("DELETE FROM kho_users WHERE username = ?", (str(username).strip().lower(),))
        self.db.commit()


def _skey(token):
    return hashlib.sha256(token.encode()).hexdigest()


def login(self, ip, username, password):
    now = time.time()
    with self.lock:
        cnt, until = self.fails.get(ip, [0, 0])
        if until > now:
            raise PermissionError(f"Sai quá nhiều lần, thử lại sau {int(until - now)} giây")
    u = self._q("SELECT * FROM kho_users WHERE username = ?", (str(username or "").strip().lower(),))
    if u and hmac.compare_digest(_pw_hash(str(password or ""), u[0]["salt"], u[0]["it"]), u[0]["hash"]):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.fails.pop(ip, None)
            self.db.execute("DELETE FROM kho_sessions WHERE exp < ?", (now,))
            self.db.execute("INSERT INTO kho_sessions VALUES (?, ?, ?)", (_skey(token), u[0]["id"], now + SESSION_DAYS * 86400))
            self.db.execute("UPDATE kho_users SET last_login = ? WHERE id = ?", (now, u[0]["id"]))
            self.db.commit()
        return token
    time.sleep(1)
    with self.lock:
        cnt += 1
        self.fails[ip] = [0, now + LOCK_SECONDS] if cnt >= MAX_FAILS else [cnt, 0]
        left = MAX_FAILS - cnt
    raise PermissionError("Sai tên đăng nhập hoặc mật khẩu" + (f", còn {left} lần thử" if left > 0 else
                                                              f", bị khóa {LOCK_SECONDS // 60} phút"))


def session_user(self, token):
    """Tài khoản khách của phiên (None nếu không hợp lệ)."""
    if not token:
        return None
    r = self._q("SELECT u.id, u.username, u.customer_id, c.name customer_name FROM kho_sessions s "
                "JOIN kho_users u ON u.id = s.user_id JOIN customers c ON c.id = u.customer_id "
                "WHERE s.key = ? AND s.exp > ?", (_skey(token), time.time()))
    return r[0] if r else None


def logout(self, token):
    with self.lock:
        self.db.execute("DELETE FROM kho_sessions WHERE key = ?", (_skey(token or ""),))
        self.db.commit()


for _f in (_check_owner, customers, save_customer, delete_customer, save_user, delete_user, login, session_user, logout):
    setattr(Kho, _f.__name__, _f)
