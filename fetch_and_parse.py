#!/usr/bin/env python3
"""
fetch_and_parse.py — Агро Звіт ТОВ «Долинське»
Завантажує xlsx-файли з OneDrive через rclone, парсить і повертає dict з даними.

Структура OneDrive: "onedrive:Долинское ОТЧЕТЫ/2026_2/ДД.ММ/"
Якщо папка сьогоднішнього дня відсутня — бере останню доступну.

Виходить JSON-файл data.json у поточній директорії (читається build_html.py).

Залежності: rclone (в PATH), openpyxl
GitHub Actions: rclone.conf зберігається як Secret RCLONE_CONF
"""

import subprocess
import sys
import os
import json
import datetime
import re
from pathlib import Path
from openpyxl import load_workbook

# ─── Константи ────────────────────────────────────────────────────────────────

ONEDRIVE_BASE = "onedrive:Долинское ОТЧЕТЫ/2026_2"
LOCAL_DIR = Path("./data_files")  # куди завантажувати

# Назви файлів (шукаємо без урахування регістру)
FILE_PATTERNS = {
    "fuel":     "паливо",
    "worktime": "облік",
    "harvest":  "косіння",
    "seeding":  "посівна",
}

# Прив'язка колонок паливного файлу (рядок 3 = заголовки машин)
# col_idx (0-based від col B = idx 1)
FUEL_MACHINES = {
    "JCB 541-70":          1,
    "CASE 5088":           2,
    "Deutz великий":       3,
    "Deutz малий":         4,
    "КІЙ":                 5,
    "ХТА 200":             6,
    "МТЗ-892":             7,
    "МТЗ-80":              8,
    "Т-150":               9,
    "Газон (дізель)":      10,
    "Форд":                11,
    "Різне":               12,
    # col 13 = Всього ДП
    "ГАЗОН":               14,
    "Ніва":                15,
    "Газон (треповка)":    16,
    "Помпа":               17,
}
FUEL_DP_TOTAL_COL = 13   # 0-based; "Всього ДП"

# Машини для розрахунку л/га (виключаємо транспорт і ХТА)
FUEL_LHA_MACHINES = {
    # fuel_name: список підрядків для пошуку в назві техніки в Обліку
    "CASE 5088":      ["CASE-5088", "CASE 5088"],
    "Deutz великий":  ["ХТЗ-17221/Дойц Х720", "ДОЙЦ Х720 + PON", "Deutz X720"],
    "КІЙ":            ["КИЙ 14102 + КПП", "КИЙ 14102"],
    "МТЗ-80":         ["МТЗ-80 + ЗККШ", "МТЗ-80"],
    # МТЗ-892 виключаємо — в обліку записується як "МТЗ-892/Дойц115/КИЙ-14102" (три машини разом)
}

# Уточнені площі полів (га в обробітку), коли в довіднику Excel стоїть інше.
# Ключ — назва поля в нижньому регістрі, як у довіднику косіння.
FIELD_AREA_OVERRIDES = {
    "9 малаківка": 7,   # Денис, 27.10.2026: в обробітку 7 га (у довіднику 9)
}

# ─── rclone helpers ───────────────────────────────────────────────────────────

def rclone_list_dirs(remote_path: str) -> list[str]:
    """Повертає список підпапок у remote_path."""
    result = subprocess.run(
        ["rclone", "lsd", remote_path, "--max-depth", "1"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[rclone lsd ERROR] {result.stderr}", file=sys.stderr)
        return []
    dirs = []
    for line in result.stdout.splitlines():
        # формат: "          -1 2026-10-25 11:00:00        -1 25.10"
        parts = line.strip().split()
        if parts:
            dirs.append(parts[-1])
    return dirs


def rclone_copy_dir(remote_dir: str, local_dir: Path) -> bool:
    """Копіює папку з OneDrive локально."""
    local_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["rclone", "copy", remote_dir, str(local_dir), "--progress"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[rclone copy ERROR] {result.stderr}", file=sys.stderr)
        return False
    return True


def find_latest_dir() -> str | None:
    """Знаходить найновішу папку ДД.ММ в OneDrive."""
    dirs = rclone_list_dirs(ONEDRIVE_BASE)
    # Фільтруємо папки формату ДД.ММ
    valid = []
    for d in dirs:
        if re.match(r"^\d{2}\.\d{2}$", d):
            valid.append(d)
    if not valid:
        return None
    # Сортуємо по дд.мм → беремо найновішу
    def sort_key(s):
        dd, mm = s.split(".")
        return int(mm) * 100 + int(dd)
    valid.sort(key=sort_key)
    return valid[-1]


def download_files(date_str: str | None = None) -> Path | None:
    """
    Завантажує файли для вказаної дати (або останньої доступної).
    Повертає шлях до локальної папки з файлами.
    """
    if date_str is None:
        today = datetime.date.today()
        date_str = today.strftime("%d.%m")

    # Перевіряємо чи є папка для сьогоднішньої дати
    dirs = rclone_list_dirs(ONEDRIVE_BASE)
    if date_str not in dirs:
        print(f"[INFO] Папка {date_str} не знайдена, беремо останню доступну")
        date_str = find_latest_dir()
        if not date_str:
            print("[ERROR] Не знайдено жодної папки ДД.ММ", file=sys.stderr)
            return None

    remote_path = f"{ONEDRIVE_BASE}/{date_str}"
    local_path = LOCAL_DIR / date_str
    print(f"[INFO] Завантажую {remote_path} → {local_path}")

    if not rclone_copy_dir(remote_path, local_path):
        return None

    return local_path


def find_file(local_dir: Path, keyword: str) -> Path | None:
    """Шукає файл по ключовому слову (без урахування регістру)."""
    for f in local_dir.iterdir():
        if f.suffix.lower() == ".xlsx" and keyword.lower() in f.name.lower():
            return f
    return None


# ─── Парсери ──────────────────────────────────────────────────────────────────

def parse_fuel(filepath: Path) -> dict:
    """
    Парсить Звіт ПАЛИВО.xlsx.
    Повертає:
      - monthly: {машина: {дата: літри}} — ВСІ дати від 2026-09-01
      - balance: {теор_дп, факт_дп, теор_бензин, факт_бензин, дата}
      - balance_history: [{date, theor_dp}] — всі рядки для динамічного залишку
    """
    wb = load_workbook(filepath, read_only=True, data_only=True)
    result = {"monthly": {}, "balance": {}, "balance_history": [], "petrol_machines": set()}

    SKIP_SHEETS = ["Архів", "Баланс", "Резервуари", "Довідники"]
    START_DATE = datetime.date(2026, 9, 1)

    # Читаємо всі місячні листи (не-службові), збираємо заправки від START_DATE
    for sheet_name in wb.sheetnames:
        if any(x in sheet_name for x in SKIP_SHEETS):
            continue

        ws = wb[sheet_name]
        # Рядок 2 — групи («ДП» … «Всього ДП» | «БЕНЗИН» … «ВСЬОГО бензин» |
        # «БЕНЗИН (власні авто)» … «Всього хлопці»), рядок 3 — назви машин.
        # Колонки визначаємо за групою, а не за назвою: «Різне» є і в ДП, і в бензині,
        # а «Газон (дізель)» — це дизель, хоч і «Газон».
        hdr2 = next(ws.iter_rows(min_row=2, max_row=2, values_only=True), ())
        hdr3 = next(ws.iter_rows(min_row=3, max_row=3, values_only=True), ())
        groups = []  # [(col_idx, тип)]
        for ci, v in enumerate(hdr2):
            s = str(v).strip().lower() if v else ""
            if s == "дп":
                groups.append((ci, "dp"))
            elif s.startswith("бензин (власні"):
                groups.append((ci, "own"))
            elif s == "бензин":
                groups.append((ci, "ben"))
            elif s.startswith("всього") or s.startswith("весь") or s.startswith("завоз") or s.startswith("щуп"):
                groups.append((ci, "stop"))
        groups.sort()
        machine_cols = {}  # {display_name: (col_idx, type)}
        for ci, v in enumerate(hdr3):
            if not v or not isinstance(v, str):
                continue
            gtype = None
            for gci, gt in groups:
                if gci <= ci:
                    gtype = gt
            if gtype not in ("dp", "ben", "own"):
                continue
            name = v.strip()
            if gtype == "ben" and name.lower() == "різне":
                name = "Різне (бензин)"
            if gtype == "own":
                name = f"{name} (авто)"
            machine_cols[name] = (ci, gtype)
            if gtype in ("ben", "own"):
                result["petrol_machines"].add(name)

        if not machine_cols:
            continue

        # Зчитуємо дані (row4+)
        for row in ws.iter_rows(min_row=4, values_only=True):
            date_val = row[0]
            if not isinstance(date_val, datetime.datetime):
                continue
            rec_date = date_val.date()
            if rec_date < START_DATE:
                continue
            date_key = rec_date.isoformat()
            for machine_name, (col_idx, _t) in machine_cols.items():
                if col_idx < len(row):
                    val = row[col_idx]
                    if val and isinstance(val, (int, float)) and val > 0:
                        if machine_name not in result["monthly"]:
                            result["monthly"][machine_name] = {}
                        result["monthly"][machine_name][date_key] = float(val)

    # Баланс (власник) — ПОВНА ІСТОРІЯ по датах
    today_date = datetime.date.today()
    balance_sheet = "Баланс (власник)"
    if balance_sheet in wb.sheetnames:
        ws_bal = wb[balance_sheet]
        balance_history = []
        for row in ws_bal.iter_rows(min_row=5, values_only=True):
            if not isinstance(row[0], datetime.datetime):
                continue
            rec_date = row[0].date()
            if rec_date > today_date:
                continue  # пропускаємо майбутні рядки
            try:
                # col17 (0-based) = теоретичний залишок ДП
                # col18 = фактичний залишок ДП
                # col20 = теоретичний залишок Бензин
                # col21 = фактичний залишок Бензин
                # col17 = теоретичний залишок (число або рядок "НЕМАЄ...")
                raw17 = row[17] if len(row) > 17 else None
                theor_dp = _safe_float(raw17) if isinstance(raw17, (int, float)) else None
                fact_dp  = _safe_float(row[18] if len(row) > 18 else None)
                raw20 = row[20] if len(row) > 20 else None
                theor_ben = _safe_float(raw20) if isinstance(raw20, (int, float)) else None
                fact_ben  = _safe_float(row[21] if len(row) > 21 else None)
                # Відображуваний залишок: fact якщо є, інакше theor
                display_dp  = fact_dp  if fact_dp  else theor_dp
                display_ben = fact_ben if fact_ben else theor_ben
                if display_dp is None and display_ben is None:
                    continue
                balance_history.append({
                    "date":       rec_date.isoformat(),
                    "theor_dp":   theor_dp,
                    "fact_dp":    fact_dp,
                    "display_dp": display_dp,       # для JS: завжди заповнено
                    "theor_ben":  theor_ben,
                    "fact_ben":   fact_ben,
                    "display_ben": display_ben,
                })
            except Exception:
                continue
        result["balance_history"] = balance_history
        # Для зворотної сумісності — остання відома точка
        if balance_history:
            result["balance"] = balance_history[-1]

    result["petrol_machines"] = sorted(result["petrol_machines"])
    wb.close()
    return result


def parse_worktime(filepath: Path) -> dict:
    """
    Парсить Облік_роб_часу.xlsx.
    Читає ВСІ місячні листи (вересень 2026+), не тільки поточний.
    Повертає всі записи (га і год):
      [{date, name, work_type, machine, field, qty_ha, qty_hrs, unit, crop}]
    """
    wb = load_workbook(filepath, read_only=True, data_only=True)
    result = {"records": []}

    # Збираємо всі місячні листи (не Архів, не Розрахунок, не службові)
    SKIP_KEYWORDS = ["Архів", "Розрахунок", "Розцінки", "Довідники"]
    month_sheets = [
        sn for sn in wb.sheetnames
        if not any(k in sn for k in SKIP_KEYWORDS)
    ]

    # Визначаємо мінімальну дату старту — 01.09.2026
    START_DATE = datetime.date(2026, 9, 1)

    for sheet_name in month_sheets:
        ws = wb[sheet_name]
        for row in ws.iter_rows(min_row=4, values_only=True):
            date_val = row[0]
            if not isinstance(date_val, datetime.datetime):
                continue
            rec_date = date_val.date()
            if rec_date < START_DATE:
                continue  # пропускаємо старіші записи

            unit = str(row[6]).strip() if row[6] else ""
            raw_qty = row[5]
            qty = None
            if raw_qty is not None:
                try:
                    qty = float(str(raw_qty).replace("год", "").replace(",", ".").strip())
                except (TypeError, ValueError):
                    qty = None
            if qty == 0:
                qty = None

            unit_lower = unit.lower()
            qty_ha = qty if unit_lower == "га" else None
            qty_hrs = qty if "год" in unit_lower else None

            # Рядки без кількості (Вихідний, Обліковець без год тощо) теж показуємо
            # у таблиці дня — інакше день виглядає як «працював один черговий».
            if qty_ha is None and qty_hrs is None and not row[2]:
                continue
            # «Вихідний» у звіт не потрапляє зовсім
            if row[2] and str(row[2]).strip().lower().startswith("вихідн"):
                continue

            result["records"].append({
                "date": rec_date.isoformat(),
                "name": str(row[1]).strip() if row[1] else "",
                "work_type": str(row[2]).strip() if row[2] else "",
                "machine": str(row[3]).strip() if row[3] else "",
                "field": str(row[4]).strip() if row[4] else "",
                "qty_ha": qty_ha,
                "qty_hrs": qty_hrs,
                "unit": unit,
                "crop": str(row[7]).strip() if len(row) > 7 and row[7] else "",
            })

    wb.close()
    return result


def parse_harvest(filepath: Path) -> dict:
    """
    Парсить Косіння_2026.xlsx, лист '2026'.
    Колонки (1-based): 1 дата | 2 поле | 3 га | 4 соняшник кг | 5 кукурудза кг |
      6 кукурудза на доробіток кг | 7 пшениця кг | 8 мусор сонях кг |
      9-12 відправка на елеватор | 13-16 залишки по рядку (не наростаючі!) |
      17-21 довідник полів, а нижче (кол. 17-20) — зведена таблиця власника
      «На складі зараз (за мінусом вивезеного)»: Культура | Вивезено | Інші витрати | Залишок.

    Правила:
      - рядок без поля і без га, але з кг культур (13.07 — «давня» пшениця/залишки
        минулого року) — це не урожай 2026, у records/totals не йде;
      - кукурудза = кукурудза + кукурудза на доробіток (як у таблиці власника);
      - залишок на складі беремо з таблиці власника, а не з останнього рядка.
    """
    SEASON_START = datetime.date(2026, 1, 1)
    wb = load_workbook(filepath, read_only=False, data_only=True)
    result = {"records": [], "totals": {}, "stock": {}, "by_month": {},
              "opening_stock": {}, "other_issues": []}

    ws = wb["2026"] if "2026" in wb.sheetnames else None
    if ws is None:
        wb.close()
        return result

    totals = {k: 0.0 for k in (
        "sunflower_ha", "corn_ha", "wheat_ha",
        "sunflower_kg", "corn_kg", "wheat_kg", "waste_sun_kg",
        "sent_sun", "sent_corn", "sent_wheat", "sent_waste_sun")}
    by_month = {}

    def num(v):
        return float(v) if isinstance(v, (int, float)) else 0.0

    for r in range(3, ws.max_row + 1):
        d = ws.cell(r, 1).value
        if not isinstance(d, (datetime.datetime, datetime.date)):
            continue
        d = d.date() if isinstance(d, datetime.datetime) else d
        if d < SEASON_START:
            continue
        field = ws.cell(r, 2).value
        ha = num(ws.cell(r, 3).value)
        sun = num(ws.cell(r, 4).value)
        corn = num(ws.cell(r, 5).value) + num(ws.cell(r, 6).value)
        wht = num(ws.cell(r, 7).value)
        waste = num(ws.cell(r, 8).value)
        sent = [num(ws.cell(r, c).value) for c in (9, 10, 11, 12)]

        if not ha and field in (None, "") and (sun or corn or wht):
            # давні залишки на складі, не урожай цього сезону
            result["opening_stock"] = {"date": d.isoformat(), "sunflower_kg": sun,
                                       "corn_kg": corn, "wheat_kg": wht, "waste_sun_kg": waste}
            continue
        if not (ha or sun or corn or wht or waste or any(sent)):
            continue

        rec = {
            "date": d.isoformat(),
            "field": str(field).strip() if field is not None else "",
            "ha": ha,
            "sunflower_kg": sun, "corn_kg": corn, "wheat_kg": wht, "waste_sun_kg": waste,
            "sent_sun": sent[0], "sent_corn": sent[1], "sent_wheat": sent[2], "sent_waste_sun": sent[3],
        }
        result["records"].append(rec)

        crop_ha_key = ("sunflower_ha" if sun else "corn_ha" if corn else "wheat_ha" if wht else None)
        if ha and crop_ha_key:
            totals[crop_ha_key] += ha
        totals["sunflower_kg"] += sun
        totals["corn_kg"] += corn
        totals["wheat_kg"] += wht
        totals["waste_sun_kg"] += waste
        totals["sent_sun"] += sent[0]
        totals["sent_corn"] += sent[1]
        totals["sent_wheat"] += sent[2]
        totals["sent_waste_sun"] += sent[3]

        mk = d.strftime("%Y-%m")
        bm = by_month.setdefault(mk, {k: 0.0 for k in (
            "sunflower_kg", "corn_kg", "wheat_kg", "waste_sun_kg",
            "sunflower_ha", "corn_ha", "wheat_ha")})
        bm["sunflower_kg"] += sun
        bm["corn_kg"] += corn
        bm["wheat_kg"] += wht
        bm["waste_sun_kg"] += waste
        if ha and crop_ha_key:
            bm[crop_ha_key] += ha

    # ── Довідник полів (кол. 17 «Найменування поля», 19 «Га в обробітку») ────
    fields = []
    for r in range(3, min(ws.max_row, 100) + 1):
        name = ws.cell(r, 17).value
        if name is None or (isinstance(name, str) and name.strip().lower().startswith("на складі")):
            break
        area = num(ws.cell(r, 19).value)
        area = FIELD_AREA_OVERRIDES.get(str(name).strip().lower(), area)
        fields.append({"field": str(name).strip(), "area_ha": area})
    result["fields"] = fields

    # ── Таблиця власника «На складі зараз» ──────────────────────────────────
    stock = {}
    CROP_KEYS = {"пшениця": "wheat_kg", "соняшник": "sunflower_kg",
                 "кукурудза": "corn_kg", "мусор": "waste_sun_kg"}
    anchor = None
    for r in range(1, min(ws.max_row, 300) + 1):
        v = ws.cell(r, 17).value
        if isinstance(v, str) and v.strip().lower().startswith("на складі зараз"):
            anchor = r
            break
    if anchor:
        for r in range(anchor + 1, anchor + 12):
            name = ws.cell(r, 17).value
            if not isinstance(name, str):
                continue
            low = name.strip().lower()
            if low.startswith("інші видачі"):
                break
            for k, key in CROP_KEYS.items():
                if low.startswith(k):
                    stock[key] = num(ws.cell(r, 20).value)
                    stock[key.replace("_kg", "_sent_kg")] = num(ws.cell(r, 18).value)
                    stock[key.replace("_kg", "_other_kg")] = num(ws.cell(r, 19).value)
        # Інші видачі зі складу (премії, на посів, під з/п)
        for r in range(anchor + 1, min(ws.max_row, anchor + 80) + 1):
            v = ws.cell(r, 17).value
            if isinstance(v, (datetime.datetime, datetime.date)):
                result["other_issues"].append({
                    "date": (v.date() if isinstance(v, datetime.datetime) else v).isoformat(),
                    "crop": str(ws.cell(r, 18).value or ""),
                    "kg": num(ws.cell(r, 19).value),
                    "comment": str(ws.cell(r, 20).value or ""),
                })

    result["totals"] = totals
    result["by_month"] = by_month
    result["stock"] = stock or {"sunflower_kg": 0, "corn_kg": 0, "wheat_kg": 0, "waste_sun_kg": 0}
    wb.close()
    return result


def parse_seeding(filepath: Path) -> dict:
    """
    Парсить посівна_2026.xlsx.
    Лист '2026': Дата | Поле | Га | Найменування робіт | Добриво | кг добрива | Посівмат кг | Залишок
    + план (колонки L-O): Поле | Га | Культура | Гібрид

    Повертає:
      - records: тільки рядки з "посів" в найменуванні
      - totals: {total_ha, total_seed_kg, total_fertilizer_kg}
      - plan: [{field, ha, crop, hybrid}]
    """
    wb = load_workbook(filepath, read_only=True, data_only=True)
    result = {"records": [], "totals": {}, "plan": []}

    ws = None
    for sn in wb.sheetnames:
        if sn == "2026":
            ws = wb[sn]
            break

    if ws:
        totals = {"total_ha": 0, "total_seed_kg": 0, "total_fertilizer_kg": 0}

        for row in ws.iter_rows(min_row=2, values_only=True):
            date_val = row[0]

            # Парсимо план (колонки L=11, M=12, N=13, O=14)
            plan_field = row[11] if len(row) > 11 else None
            plan_ha = row[12] if len(row) > 12 else None
            plan_crop = row[13] if len(row) > 13 else None
            plan_hybrid = row[14] if len(row) > 14 else None
            if plan_field and plan_ha:
                result["plan"].append({
                    "field": str(plan_field).strip(),
                    "ha": _safe_float(plan_ha) or 0,
                    "crop": str(plan_crop).strip() if plan_crop else "",
                    "hybrid": str(plan_hybrid).strip() if plan_hybrid else "",
                })

            # Парсимо посів-записи
            if not isinstance(date_val, datetime.datetime):
                continue
            work_type = str(row[3]).strip() if row[3] else ""
            wt_lower = work_type.lower()
            # Тільки чисті посівні роботи, без "гербіцид перед посівом" тощо
            if not (wt_lower.startswith("посів") or wt_lower.startswith("сівба") or
                    ("посів " in wt_lower and "гербіцид" not in wt_lower)):
                continue

            ha = _safe_float(row[2]) or 0
            fertilizer_kg = _safe_float(row[5]) or 0
            # seed_kg може бути числом АБО рядком типу "Пшениця-4500кг"
            raw_seed = row[6]
            if isinstance(raw_seed, (int, float)):
                seed_kg = _safe_float(raw_seed) or 0
            elif isinstance(raw_seed, str):
                # витягуємо перше число з рядка (напр. "Пшениця-4500кг" → 4500)
                m = re.search(r"(\d[\d\s,\.]*)", raw_seed.replace(" ", ""))
                seed_kg = float(m.group(1).replace(",", ".")) if m else 0
            else:
                seed_kg = 0
            remainder = _safe_float(row[7])

            result["records"].append({
                "date": date_val.date().isoformat(),
                "field": str(row[1]).strip() if row[1] else "",
                "ha": ha,
                "work_type": work_type,
                "fertilizer": str(row[4]).strip() if row[4] else "",
                "fertilizer_kg": fertilizer_kg,
                "seed_kg": seed_kg,
                "remainder_kg": remainder,
            })
            totals["total_ha"] += ha
            totals["total_seed_kg"] += seed_kg
            totals["total_fertilizer_kg"] += fertilizer_kg

        result["totals"] = totals
        # Видаляємо дублікати плану (лише перші унікальні поля)
        seen = set()
        unique_plan = []
        for p in result["plan"]:
            key = p["field"]
            if key not in seen:
                seen.add(key)
                unique_plan.append(p)
        result["plan"] = unique_plan

    wb.close()
    return result


# ─── Розрахунок л/га ──────────────────────────────────────────────────────────

def _normalize_work_type(work_type: str) -> str:
    """Нормалізує тип роботи до стислої назви для групування."""
    wt = work_type.strip().lower()
    if "оранка" in wt:
        return "Оранка"
    if "диск" in wt:
        return "Дискування"
    if "мульч" in wt:
        return "Мульчування"
    if "посів" in wt or "сівба" in wt:
        return "Посів"
    if "комбайн" in wt or "збирання" in wt:
        return "Комбайнування"
    if "перевез" in wt:
        return "Перевезення"
    if "прикоч" in wt:
        return "Прикочування"
    if "подрібн" in wt:
        return "Подрібнення стерні"
    if "культив" in wt:
        return "Культивація"
    return work_type.strip()


def calc_lha(fuel_data: dict, worktime_data: dict) -> list[dict]:
    """
    Л/га по техніці (в межах кожного місяця).

    Метод «від заправки до заправки»: заправка дня X покриває всю роботу машини
    після попередньої заправки (того ж місяця) і до X включно. Перша заправка
    місяця покриває роботу з 1-го числа. Так кожен гектар потрапляє рівно в одну
    заправку — на відміну від старого методу (га лише найближчого дня ≤ X), який
    губив роботу між заправками і завищував л/га.

    Якщо в інтервалі кілька видів робіт — літри розподіляються пропорційно га.
    Заправка, після якої (до неї) не було га, переноситься на наступну заправку.
    Га після останньої заправки місяця ще не «оплачені» паливом і не враховуються.

    daily: [{date (дата заправки), liters, ha, work_type, ha_from, ha_to, lha}]
    """
    ha_by_machine = {}  # {fuel_key: {date: {work_type: ha}}}
    for rec in worktime_data["records"]:
        if not rec.get("qty_ha"):
            continue
        machine = rec["machine"]
        # Комбіновані записи (МТЗ-892/Дойц115/КИЙ — три машини в одному) — не розносимо
        if machine.count("/") >= 2:
            continue
        fuel_key = None
        for fuel_name, patterns in FUEL_LHA_MACHINES.items():
            if any(p.upper() in machine.upper() for p in patterns):
                fuel_key = fuel_name
                break
        if not fuel_key:
            continue
        wt = _normalize_work_type(rec.get("work_type", ""))
        day = ha_by_machine.setdefault(fuel_key, {}).setdefault(rec["date"], {})
        day[wt] = day.get(wt, 0) + rec["qty_ha"]

    results = []
    monthly_fuel = fuel_data.get("monthly", {})
    for machine_name in FUEL_LHA_MACHINES:
        fuel_dates = monthly_fuel.get(machine_name, {})
        ha_dates = ha_by_machine.get(machine_name, {})
        if not fuel_dates:
            continue
        daily = []
        months = sorted({d[:7] for d in fuel_dates})
        for m in months:
            fills = sorted((d, l) for d, l in fuel_dates.items() if d[:7] == m)
            prev = m + "-00"  # «до 1-го числа»
            carry = 0.0
            for fdate, liters in fills:
                interval = {d: v for d, v in ha_dates.items() if prev < d <= fdate}
                by_wt = {}
                for v in interval.values():
                    for wt, h in v.items():
                        by_wt[wt] = by_wt.get(wt, 0) + h
                total_ha = sum(by_wt.values())
                lit = liters + carry
                if total_ha <= 0:
                    carry = lit  # заправка «наперед» — переносимо
                    continue
                carry = 0.0
                d_from, d_to = min(interval), max(interval)
                for wt, h in sorted(by_wt.items(), key=lambda x: -x[1]):
                    part = lit * h / total_ha
                    daily.append({
                        "date": fdate, "liters": round(part, 1), "ha": h,
                        "work_type": wt, "ha_from": d_from, "ha_to": d_to,
                        "lha": round(part / h, 2),
                    })
                prev = fdate
            if carry > 0:
                daily.append({"date": fills[-1][0], "liters": round(carry, 1), "ha": 0,
                              "work_type": "Без га (не розподілено)", "ha_from": None,
                              "ha_to": None, "lha": None})

        total_fuel = sum(r["liters"] for r in daily)
        total_ha = sum(r["ha"] for r in daily)
        by_wt = {}
        for r in daily:
            b = by_wt.setdefault(r["work_type"], {"ha": 0, "fuel_l": 0})
            b["ha"] += r["ha"]
            b["fuel_l"] += r["liters"]
        results.append({
            "machine": machine_name,
            "total_fuel_l": round(total_fuel, 1),
            "total_ha": total_ha,
            "avg_lha": round(total_fuel / total_ha, 2) if total_ha else None,
            "by_work_type": [
                {"work_type": wt, "ha": round(v["ha"], 1), "fuel_l": round(v["fuel_l"]),
                 "avg_lha": round(v["fuel_l"] / v["ha"], 2) if v["ha"] else None}
                for wt, v in sorted(by_wt.items())
            ],
            "daily": daily,
        })
    return results


# ─── Допоміжні функції ────────────────────────────────────────────────────────

def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return f if f != 0 else None
    except (TypeError, ValueError):
        return None


# ─── Головна функція ─────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Агро Звіт: завантаження та парсинг даних")
    parser.add_argument("--date", help="Дата папки ДД.ММ (default: сьогодні)")
    parser.add_argument("--local", help="Локальна папка з файлами (без rclone)")
    parser.add_argument("--output", default="data.json", help="Вихідний JSON файл")
    args = parser.parse_args()

    # Визначаємо звідки брати файли
    if args.local:
        data_dir = Path(args.local)
        print(f"[INFO] Локальний режим: {data_dir}")
    else:
        data_dir = download_files(args.date)
        if not data_dir:
            print("[ERROR] Не вдалося завантажити файли", file=sys.stderr)
            sys.exit(1)

    # Знаходимо файли
    files = {}
    for key, pattern in FILE_PATTERNS.items():
        f = find_file(data_dir, pattern)
        if f:
            files[key] = f
            print(f"[INFO] Знайдено {key}: {f.name}")
        else:
            print(f"[WARN] Файл '{pattern}' не знайдено в {data_dir}", file=sys.stderr)

    # Парсимо
    data = {
        "generated_at": datetime.datetime.now().isoformat(),
        "data_date": "",  # заповнюється нижче — остання дата з даними (ISO)
    }

    if "fuel" in files:
        data["fuel"] = parse_fuel(files["fuel"])
    if "worktime" in files:
        data["worktime"] = parse_worktime(files["worktime"])
    if "harvest" in files:
        data["harvest"] = parse_harvest(files["harvest"])
    if "seeding" in files:
        data["seeding"] = parse_seeding(files["seeding"])

    # Розраховуємо л/га якщо є обидва джерела
    if "fuel" in data and "worktime" in data:
        data["lha"] = calc_lha(data["fuel"], data["worktime"])

    # Остання дата, за яку у файлах є хоч якісь дані (≤ сьогодні)
    today_iso = datetime.date.today().isoformat()
    cand = []
    for r in data.get("worktime", {}).get("records", []):
        cand.append(r["date"])
    for dates in data.get("fuel", {}).get("monthly", {}).values():
        cand.extend(dates.keys())
    for r in data.get("harvest", {}).get("records", []):
        cand.append(r["date"])
    cand = [d for d in cand if d <= today_iso]
    data["data_date"] = max(cand) if cand else today_iso

    # Записуємо
    output_path = Path(args.output)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Записано {output_path} ({output_path.stat().st_size} bytes)")

    # Підсумок
    if "harvest" in data:
        t = data["harvest"].get("totals", {})
        print(f"[Косіння] Соняшник: {t.get('sunflower_kg',0)/1000:.1f}т, "
              f"Кукурудза: {t.get('corn_kg',0)/1000:.1f}т, "
              f"Пшениця: {t.get('wheat_kg',0)/1000:.1f}т")
    if "seeding" in data:
        t = data["seeding"].get("totals", {})
        print(f"[Посівна] Га: {t.get('total_ha',0):.0f}, "
              f"Насіння: {t.get('total_seed_kg',0):.0f}кг, "
              f"Добриво: {t.get('total_fertilizer_kg',0):.0f}кг")
    if "fuel" in data:
        b = data["fuel"].get("balance", {})
        if b:
            dp = b.get("fact_dp") or b.get("theor_dp") or 0
            src = " (теор.)" if not b.get("fact_dp") else ""
            print(f"[Паливо] Залишок ДП{src}: {dp:.0f}л ({b.get('date','')})")


if __name__ == "__main__":
    main()
