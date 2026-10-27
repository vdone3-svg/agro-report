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
    result = {"monthly": {}, "balance": {}, "balance_history": []}

    SKIP_SHEETS = ["Архів", "Баланс", "Резервуари", "Довідники"]
    START_DATE = datetime.date(2026, 9, 1)

    # Читаємо всі місячні листи (не-службові), збираємо заправки від START_DATE
    for sheet_name in wb.sheetnames:
        if any(x in sheet_name for x in SKIP_SHEETS):
            continue

        ws = wb[sheet_name]
        # row3 = заголовки машин (0-based col)
        machine_cols = {}
        for i, row in enumerate(ws.iter_rows(min_row=3, max_row=3, values_only=True)):
            for col_idx, val in enumerate(row):
                if val and isinstance(val, str):
                    val_clean = val.strip()
                    for machine_name in FUEL_MACHINES:
                        if machine_name in machine_cols:
                            continue
                        if val_clean == machine_name or val_clean.startswith(machine_name):
                            machine_cols[machine_name] = col_idx
                            break
                    else:
                        for machine_name in FUEL_MACHINES:
                            if machine_name in machine_cols:
                                continue
                            if machine_name in val_clean:
                                machine_cols[machine_name] = col_idx
                                break

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
            for machine_name, col_idx in machine_cols.items():
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
                    qty = float(str(raw_qty).replace("год", "").strip())
                except (TypeError, ValueError):
                    qty = None

            unit_lower = unit.lower()
            qty_ha = qty if unit_lower == "га" else None
            qty_hrs = qty if "год" in unit_lower else None

            if qty_ha is None and qty_hrs is None:
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
    Парсить Косіння_2026.xlsx.
    Лист '2026': дата | №поля | га | соняшник кг | кукурудза кг | кукурудза доробіток |
                 пшениця кг | мусор | відп.соняшник | відп.кукурудза | відп.пшениця | відп.мусор |
                 ... залишки ...
    Повертає:
      - records: [{date, field, ha, sunflower_kg, corn_kg, wheat_kg, sent_sun, sent_corn, sent_wheat}]
      - totals: {sunflower_ha, corn_ha, wheat_ha, sunflower_kg, corn_kg, wheat_kg}
    """
    wb = load_workbook(filepath, read_only=True, data_only=True)
    result = {"records": [], "totals": {}}

    ws = None
    for sn in wb.sheetnames:
        if sn == "2026":
            ws = wb[sn]
            break

    if ws:
        # row2 = заголовки, row3+ = дані
        totals = {
            "sunflower_ha": 0, "corn_ha": 0, "wheat_ha": 0,
            "sunflower_kg": 0, "corn_kg": 0, "wheat_kg": 0,
            "sent_sun": 0, "sent_corn": 0, "sent_wheat": 0,
        }
        for row in ws.iter_rows(min_row=3, values_only=True):
            date_val = row[0]
            if not isinstance(date_val, (datetime.datetime, datetime.date)):
                continue
            if isinstance(date_val, datetime.datetime):
                date_val = date_val.date()

            ha = _safe_float(row[2])
            sun_kg = _safe_float(row[3])
            corn_kg = _safe_float(row[4])
            wheat_kg = _safe_float(row[6])
            sent_sun = _safe_float(row[8])
            sent_corn = _safe_float(row[9])
            sent_wheat = _safe_float(row[10])

            rec = {
                "date": date_val.isoformat(),
                "field": str(row[1]).strip() if row[1] is not None else "",
                "ha": ha or 0,
                "sunflower_kg": sun_kg or 0,
                "corn_kg": corn_kg or 0,
                "wheat_kg": wheat_kg or 0,
                "sent_sun": sent_sun or 0,
                "sent_corn": sent_corn or 0,
                "sent_wheat": sent_wheat or 0,
            }
            result["records"].append(rec)

            # Підраховуємо підсумки
            if ha:
                if sun_kg:
                    totals["sunflower_ha"] += ha
                elif corn_kg:
                    totals["corn_ha"] += ha
                elif wheat_kg:
                    totals["wheat_ha"] += ha
            totals["sunflower_kg"] += sun_kg or 0
            totals["corn_kg"] += corn_kg or 0
            totals["wheat_kg"] += wheat_kg or 0
            totals["sent_sun"] += sent_sun or 0
            totals["sent_corn"] += sent_corn or 0
            totals["sent_wheat"] += sent_wheat or 0

        result["totals"] = totals

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
    Розраховує л/га для кожної машини за поточний місяць.
    Логіка: заправка дати X ÷ га з найближчого дня ≤ X де є записи по цій техніці.
    Додатково: розбивка по типах робіт (оранка vs дискування тощо).
    Важливо: для підрахунку л/га за місяць беремо тільки місяці де є заправки.
    """
    # Визначаємо місяці в яких є заправки (для кожної машини)
    fuel_months = {}  # {machine_name: set of "YYYY-MM"}
    for machine_name, dates in fuel_data.get("monthly", {}).items():
        fuel_months[machine_name] = {d[:7] for d in dates.keys()}

    # Будуємо карту га по техніці і типу роботи:
    # {fuel_key: {date: {work_type: ha, '_total': ha}}}
    ha_by_machine = {}
    for rec in worktime_data["records"]:
        if not rec.get("qty_ha"):
            continue  # для л/га потрібні тільки га-записи
        machine = rec["machine"]
        date = rec["date"]
        ha = rec["qty_ha"]
        work_type = _normalize_work_type(rec.get("work_type", ""))

        # Пропускаємо комбіновані записи (МТЗ-892/Дойц115/КИЙ — три машини в одному)
        if machine.count("/") >= 2:
            continue
        # Знаходимо відповідне паливне ім'я
        fuel_key = None
        for fuel_name, patterns in FUEL_LHA_MACHINES.items():
            for pat in patterns:
                if pat.upper() in machine.upper():
                    fuel_key = fuel_name
                    break
            if fuel_key:
                break
        if not fuel_key:
            continue

        # Враховуємо тільки га за місяці де є заправки цієї машини
        if fuel_key in fuel_months and date[:7] not in fuel_months[fuel_key]:
            continue

        if fuel_key not in ha_by_machine:
            ha_by_machine[fuel_key] = {}
        day = ha_by_machine[fuel_key].setdefault(date, {"_total": 0})
        day[work_type] = day.get(work_type, 0) + ha
        day["_total"] += ha

    results = []
    monthly_fuel = fuel_data.get("monthly", {})

    for machine_name, ha_dates in ha_by_machine.items():
        fuel_dates = monthly_fuel.get(machine_name, {})
        if not fuel_dates:
            continue

        # total: всі заправки + всі га за місяць (незалежно від пар дата-дата)
        total_fuel = sum(fuel_dates.values())
        total_ha = sum(v["_total"] for v in ha_dates.values())
        _seen_ha_dates = set()  # використовується в daily-циклі для by_work_type

        # Збираємо підсумок по типах робіт за місяць
        by_work_type = {}  # {work_type: {ha, fuel_l}}
        all_work_types = set()
        for day_data in ha_dates.values():
            for wt, wt_ha in day_data.items():
                if wt != "_total":
                    all_work_types.add(wt)

        # Деталі по датах заправки
        daily = []
        for fuel_date, liters in sorted(fuel_dates.items()):
            # Знаходимо найближчий день роботи ≤ fuel_date
            matching_day = None
            matching_date = None
            for ha_date in sorted(ha_dates.keys(), reverse=True):
                if ha_date <= fuel_date:
                    matching_day = ha_dates[ha_date]
                    matching_date = ha_date
                    break

            matching_ha = matching_day["_total"] if matching_day else 0
            # Тип роботи того дня (домінуючий за га, якщо кілька)
            work_type_day = ""
            if matching_day:
                best_wt = max(
                    ((wt, wt_ha) for wt, wt_ha in matching_day.items() if wt != "_total"),
                    key=lambda x: x[1], default=("", 0)
                )
                work_type_day = best_wt[0]
                # Накопичуємо по типах
                for wt, wt_ha in matching_day.items():
                    if wt == "_total":
                        continue
                    if wt not in by_work_type:
                        by_work_type[wt] = {"ha": 0, "fuel_l": 0}
                    by_work_type[wt]["ha"] += wt_ha
                    # Розподіляємо паливо пропорційно га між типами роботи
                    if matching_ha:
                        by_work_type[wt]["fuel_l"] += liters * (wt_ha / matching_ha)

            lha = round(liters / matching_ha, 2) if matching_ha else None
            daily.append({
                "date": fuel_date,
                "liters": liters,
                "ha": matching_ha,
                "ha_date": matching_date,
                "work_type": work_type_day,
                "lha": lha,
            })
            # by_work_type — накопичуємо га тільки раз на унікальну дату робіт
            if matching_date and matching_date not in _seen_ha_dates:
                _seen_ha_dates.add(matching_date)

        # Підрахунок л/га по типах робіт
        work_type_summary = []
        for wt, vals in sorted(by_work_type.items()):
            wt_ha = vals["ha"]
            wt_fuel = vals["fuel_l"]
            work_type_summary.append({
                "work_type": wt,
                "ha": round(wt_ha, 1),
                "fuel_l": round(wt_fuel, 0),
                "avg_lha": round(wt_fuel / wt_ha, 2) if wt_ha else None,
            })

        results.append({
            "machine": machine_name,
            "total_fuel_l": total_fuel,
            "total_ha": total_ha,
            "avg_lha": round(total_fuel / total_ha, 2) if total_ha else None,
            "by_work_type": work_type_summary,
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
        "data_date": args.date or datetime.date.today().strftime("%d.%m"),
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
