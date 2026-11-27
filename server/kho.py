"""Kho linh kiện: quản lý số lượng, mã nhà cung cấp, BOM (có/thiếu), cảnh báo sắp hết, nhập đơn hàng.

Chỉ dùng thư viện chuẩn (sqlite3, csv, zipfile/xml cho .xlsx) để chạy được trên OpenWrt.
Dữ liệu: /mnt/data/kho/kho.db (+ bản sao lưu mỗi ngày trong /mnt/data/kho/backup, giữ 14 bản).

Đọc file (BOM hoặc đơn hàng): CSV (tự nhận dấu phân cách và bảng mã) hoặc XLSX. Tự tìm dòng tiêu đề và
nhận cột theo tên quen thuộc của LCSC / JLCPCB, Digi-Key, Mouser, KiCad, EasyEDA, Altium; sửa lại được trên trang.

Khớp dòng BOM với linh kiện trong kho, theo thứ tự: mã LCSC -> mã Digi-Key -> mã Mouser -> MPN (bỏ khoảng trắng,
dấu -) -> giá trị + package. Dòng nào khớp sai thì chọn lại tay trên trang.
"""
import csv
import io
import os
import re
import secrets
import sqlite3
import threading
import time
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
"""


class Kho:
    def __init__(self):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        self._backup()
        self.db = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()
        self.pending = {}   # token -> (thời điểm, dữ liệu file đã đọc) chờ xác nhận nhập

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

    def list_parts(self, q="", category="", location="", low=False, limit=200, offset=0, sort="updated"):
        where, args = [], []
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
        items = self._q(f"SELECT * FROM parts p {w} ORDER BY {order} LIMIT ? OFFSET ?",
                        args + [max(1, min(int(limit), 1000)), max(0, int(offset))])
        sup = self._suppliers_of([p["id"] for p in items])
        for p in items:
            p["suppliers"] = sup.get(p["id"], [])
            p["low"] = p["min_qty"] > 0 and p["qty"] <= p["min_qty"]
        return {"items": items, "total": total}

    def get_part(self, pid):
        rows = self._q("SELECT * FROM parts WHERE id = ?", (pid,))
        if not rows:
            raise ValueError("Không có linh kiện này")
        p = rows[0]
        p["suppliers"] = self._suppliers_of([pid]).get(pid, [])
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

    def meta(self):
        cnt = self._q("SELECT COUNT(*) n, COALESCE(SUM(qty),0) pcs, COALESCE(SUM(qty * COALESCE(price,0)),0) value, "
                      "COALESCE(SUM(CASE WHEN min_qty > 0 AND qty <= min_qty THEN 1 ELSE 0 END),0) low, "
                      "COALESCE(SUM(CASE WHEN qty <= 0 THEN 1 ELSE 0 END),0) out FROM parts")[0]
        return {**cnt,
                "categories": [r["category"] for r in self._q(
                    "SELECT category, COUNT(*) n FROM parts WHERE category != '' GROUP BY category ORDER BY n DESC")],
                "locations": [r["location"] for r in self._q(
                    "SELECT location FROM parts WHERE location != '' GROUP BY location ORDER BY location COLLATE NOCASE")],
                "boms": self._q("SELECT COUNT(*) n FROM boms")[0]["n"]}

    # ------------------------------------------------------------ tìm linh kiện theo mã
    def find(self, lcsc="", digikey="", mouser="", mpn="", value="", package=""):
        """Trả về (part_id, cách khớp) hoặc (None, '')."""
        for sup, sku in (("lcsc", lcsc), ("digikey", digikey), ("mouser", mouser)):
            sku = str(sku or "").strip()
            if sku:
                r = self._q("SELECT part_id FROM part_suppliers WHERE supplier = ? AND sku = ? COLLATE NOCASE LIMIT 1",
                            (sup, sku.upper() if sup == "lcsc" else sku))
                if r:
                    return r[0]["part_id"], sup
        k = mpn_key(mpn)
        if len(k) >= 3:
            r = self._q("SELECT id FROM parts WHERE mpn_key = ? LIMIT 1", (k,))
            if r:
                return r[0]["id"], "mpn"
        if value and package:
            r = self._q("SELECT id FROM parts WHERE value = ? COLLATE NOCASE AND package = ? COLLATE NOCASE "
                        "ORDER BY qty DESC LIMIT 1", (value.strip(), package.strip()))
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

    def import_stock(self, token, mapping, mode="add", supplier="", location="", category="", ref=""):
        """Nhập đơn hàng / file kiểm kê. mode: add = cộng thêm, set = đặt đúng số lượng. Linh kiện chưa có thì tạo."""
        info, recs = self._take(token, mapping)
        created, updated, skipped = 0, 0, []
        with self.lock:
            self._backup()
            for r in recs:
                qty = _int(r.get("qty"), 0)
                if r.get("supplier_part") and supplier in ("digikey", "mouser") and not r.get(supplier):
                    r[supplier] = r["supplier_part"]
                pid, _ = self.find(r.get("lcsc"), r.get("digikey"), r.get("mouser"), r.get("mpn"))
                sups = [{"supplier": s, "sku": r[s], "price": r.get("price")} for s in ("lcsc", "digikey", "mouser")
                        if r.get(s)]
                if r.get("taobao"):
                    sups.append({"supplier": "taobao", "url": r["taobao"], "sku": "", "price": r.get("price")})
                if pid is None:
                    if not any(r.get(k) for k in ("mpn", "lcsc", "digikey", "mouser", "name", "value")):
                        skipped.append(r); continue
                    d = {f: r.get(f, "") for f in ("mpn", "manufacturer", "name", "package", "value")}
                    d.update(category=r.get("category") or category, location=r.get("location") or location,
                             qty=qty, price=r.get("price"), suppliers=sups, reason=f"Nhập file {info['name']}")
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
    def bom_create(self, token, mapping, name="", boards=1):
        info, recs = self._take(token, mapping)
        if not recs:
            raise ValueError("Không đọc được dòng nào trong BOM")
        now = time.time()
        with self.lock:
            self._backup()
            cur = self.db.execute("INSERT INTO boms (name, created, boards) VALUES (?, ?, ?)",
                                  ((name or info["name"]).strip()[:120], now, max(1, _int(boards, 1))))
            bid = cur.lastrowid
            for i, r in enumerate(recs, 1):
                des = r.get("designator", "")
                qty = _int(r.get("qty"), 0) or (len([x for x in re.split(r"[,;\s]+", des) if x]) if des else 1)
                dnp = str(r.get("dnp", "")).strip().lower() in ("1", "x", "yes", "true", "dnp", "dnf")
                pid, how = self.find(r.get("lcsc"), r.get("digikey"), r.get("mouser"), r.get("mpn"),
                                     r.get("value"), r.get("package"))
                self.db.execute(
                    "INSERT INTO bom_lines (bom_id, line, designator, qty, value, package, mpn, manufacturer, name, lcsc, "
                    "digikey, mouser, dnp, part_id, match) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (bid, i, des[:2000], qty, r.get("value", "")[:200], r.get("package", "")[:200], r.get("mpn", "")[:200],
                     r.get("manufacturer", "")[:200], r.get("name", "")[:500], r.get("lcsc", ""), r.get("digikey", ""),
                     r.get("mouser", ""), int(dnp), pid, how))
            self.db.commit()
            self.pending.pop(token, None)
        return self.bom(bid)

    def boms(self):
        return self._q("SELECT b.*, COUNT(l.id) lines, SUM(CASE WHEN l.part_id IS NULL AND l.dnp = 0 THEN 1 ELSE 0 END) "
                       "unmatched FROM boms b LEFT JOIN bom_lines l ON l.bom_id = b.id GROUP BY b.id ORDER BY b.created DESC")

    def bom(self, bid, boards=None):
        b = self._q("SELECT * FROM boms WHERE id = ?", (bid,))
        if not b:
            raise ValueError("Không có BOM này")
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

    def bom_update(self, bid, name=None, boards=None, notes=None):
        sets, args = [], []
        for k, v in (("name", name), ("boards", boards), ("notes", notes)):
            if v is not None:
                sets.append(f"{k} = ?"); args.append(max(1, _int(v, 1)) if k == "boards" else str(v)[:500])
        if sets:
            with self.lock:
                self.db.execute(f"UPDATE boms SET {', '.join(sets)} WHERE id = ?", args + [bid])
                self.db.commit()
        return self.bom(bid)

    def bom_set_line(self, line_id, part_id=None, qty=None, dnp=None):
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

    def bom_rematch(self, bid):
        """Khớp lại các dòng chưa khớp (sau khi đã thêm linh kiện vào kho)."""
        with self.lock:
            for ln in self._q("SELECT * FROM bom_lines WHERE bom_id = ? AND part_id IS NULL", (bid,)):
                pid, how = self.find(ln["lcsc"], ln["digikey"], ln["mouser"], ln["mpn"], ln["value"], ln["package"])
                if pid:
                    self.db.execute("UPDATE bom_lines SET part_id = ?, match = ? WHERE id = ?", (pid, how, ln["id"]))
            self.db.commit()
        return self.bom(bid)

    def bom_add_missing(self, bid):
        """Tạo linh kiện (số lượng 0) cho các dòng chưa có trong kho, để theo dõi / đặt mua."""
        made = 0
        for ln in self._q("SELECT * FROM bom_lines WHERE bom_id = ? AND part_id IS NULL AND dnp = 0", (bid,)):
            sups = [{"supplier": s, "sku": ln[s]} for s in ("lcsc", "digikey", "mouser") if ln[s]]
            p = self.save_part({"mpn": ln["mpn"], "manufacturer": ln["manufacturer"], "name": ln["name"],
                                "value": ln["value"], "package": ln["package"], "qty": 0, "suppliers": sups})
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

    def bom_delete(self, bid):
        with self.lock:
            self.db.execute("DELETE FROM boms WHERE id = ?", (bid,))
            self.db.commit()

    def bom_shortage_csv(self, bid, boards=None, supplier="lcsc"):
        """CSV linh kiện cần mua. supplier=lcsc: định dạng dán vào BOM Tool / giỏ hàng LCSC (mã, số lượng)."""
        b = self.bom(bid, boards)
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
    def export_csv(self):
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["ID", "MPN", "Manufacturer", "Description", "Category", "Value", "Package", "Location", "Quantity",
                    "Min Qty", "Unit Price", "LCSC", "Digi-Key", "Mouser", "Taobao", "Datasheet", "Notes"])
        parts = self._q("SELECT * FROM parts ORDER BY category, value, mpn")
        sups = self._suppliers_of([p["id"] for p in parts])
        for p in parts:
            c = {}
            for s in sups.get(p["id"], []):
                c.setdefault(s["supplier"], s["url"] if s["supplier"] == "taobao" else s["sku"])
            w.writerow([p["id"], p["mpn"], p["manufacturer"], p["name"], p["category"], p["value"], p["package"],
                        p["location"], p["qty"], p["min_qty"], p["price"] if p["price"] is not None else "",
                        c.get("lcsc", ""), c.get("digikey", ""), c.get("mouser", ""), c.get("taobao", ""),
                        p["datasheet"], p["notes"]])
        return "﻿" + out.getvalue()     # BOM UTF-8 để Excel mở đúng tiếng Việt
