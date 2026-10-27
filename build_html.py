#!/usr/bin/env python3
"""
build_html.py — Агро Звіт ТОВ «Долинське»
Читає data.json і генерує дашборд index.html у стилі v14 (dark-theme).
"""

import json
import sys
import argparse
import datetime
from pathlib import Path
from collections import defaultdict


def fmt_num(v, digits=0):
    if v is None:
        return "—"
    try:
        if digits == 0:
            return f"{int(round(float(v))):,}".replace(",", " ")
        else:
            return f"{float(v):.{digits}f}"
    except Exception:
        return str(v)


def build_html(data: dict) -> str:
    gen_at = data.get("generated_at", "")
    data_date = data.get("data_date", "")
    fuel = data.get("fuel", {})
    balance = fuel.get("balance", {})
    worktime = data.get("worktime", {})
    harvest = data.get("harvest", {})
    seeding = data.get("seeding", {})
    lha_list = data.get("lha", [])

    # ── Паливо ──────────────────────────────────────────────────
    theor_dp = balance.get("theor_dp") or 0
    bal_date = balance.get("date", data_date)

    fuel_monthly = fuel.get("monthly", {})
    total_dp_month = 0
    for machine, dates in fuel_monthly.items():
        if machine not in set(fuel.get("petrol_machines", [])):
            total_dp_month += sum(v for v in dates.values() if v)

    # ── Щоденні роботи ──────────────────────────────────────────
    wt_recs = worktime.get("records", [])
    today_str = datetime.date.today().isoformat()
    today_work = [r for r in wt_recs if r.get("date") == today_str]
    if not today_work and wt_recs:
        last_wt_date = max(r.get("date", "") for r in wt_recs)
        today_work = [r for r in wt_recs if r.get("date") == last_wt_date]
    work_date_label = today_work[0].get("date", today_str) if today_work else today_str
    total_ha_day = sum(r.get("qty_ha", 0) or 0 for r in today_work)

    # ── Збирання ────────────────────────────────────────────────
    htotals = harvest.get("totals", {})
    hrecs = harvest.get("records", [])
    sun_kg      = htotals.get("sunflower_kg", 0) or 0
    corn_kg     = htotals.get("corn_kg", 0) or 0
    wht_kg      = htotals.get("wheat_kg", 0) or 0
    waste_sun_kg= htotals.get("waste_sun_kg", 0) or 0
    sun_ha      = htotals.get("sunflower_ha", 0) or 0
    corn_ha     = htotals.get("corn_ha", 0) or 0
    wht_ha      = htotals.get("wheat_ha", 0) or 0

    # Залишки на складі (з останнього рядка harvest)
    hstock = harvest.get("stock", {})
    stock_sun  = hstock.get("sunflower_kg", 0) or 0
    stock_corn = hstock.get("corn_kg", 0) or 0
    stock_wht  = hstock.get("wheat_kg", 0) or 0
    stock_waste= hstock.get("waste_sun_kg", 0) or 0

    # Розбивка збирання по місяцях — з by_month (вже розраховано в парсері)
    harvest_by_month = harvest.get("by_month", {})
    monthly_harvest = defaultdict(lambda: defaultdict(float))
    for m, bm in harvest_by_month.items():
        monthly_harvest[m]["sun"]  = bm.get("sunflower_kg", 0) or 0
        monthly_harvest[m]["corn"] = bm.get("corn_kg", 0) or 0
        monthly_harvest[m]["wht"]  = bm.get("wheat_kg", 0) or 0
        monthly_harvest[m]["waste"]= bm.get("waste_sun_kg", 0) or 0

    # посівна — не показуємо в дашборді

    # ── Всі записи робочого часу (для calendar navigator) ───────
    all_work_records = [
        {
            "date": r.get("date", ""),
            "machine": r.get("machine", ""),
            "work_type": r.get("work_type", ""),
            "field": r.get("field", ""),
            "ha": r.get("qty_ha") or 0,
            "hrs": r.get("qty_hrs") or 0,
            "unit": r.get("unit", ""),
            "name": r.get("name", ""),
            "crop": r.get("crop", ""),
        }
        for r in wt_recs
        if r.get("date")
    ]

    # Збираємо список дат що мають записи
    dates_with_data = sorted(set(r["date"] for r in all_work_records))

    # ── Збираємо JSON для JS ─────────────────────────────────────
    js_data = json.dumps({
        "generated_at": gen_at,
        "data_date": data_date,
        "balance": {
            "theor_dp": round(theor_dp),
            "date": bal_date,
        },
        "balance_history": fuel.get("balance_history", []),
        "petrol_machines": fuel.get("petrol_machines", []),
        "fuel_monthly_total": round(total_dp_month),
        "fuel_by_machine": {
            m: round(sum(v for v in d.values() if v))
            for m, d in fuel_monthly.items()
            if sum(v for v in d.values() if v) > 0
        },
        "fuel_monthly_raw": {
            m: {date: round(v) for date, v in d.items() if v}
            for m, d in fuel_monthly.items()
        },
        "work_date": work_date_label,
        "work_records": [
            {
                "machine": r.get("machine", ""),
                "work_type": r.get("work_type", ""),
                "field": r.get("field", ""),
                "ha": r.get("qty_ha") or 0,
                "hrs": r.get("qty_hrs") or 0,
                "unit": r.get("unit", ""),
                "name": r.get("name", ""),
                "crop": r.get("crop", ""),
            }
            for r in today_work
        ],
        "total_ha_day": round(total_ha_day, 1),
        "all_work_records": all_work_records,
        "dates_with_data": dates_with_data,
        "lha": lha_list,
        # daily-записи для JS: машина → [{date, liters, ha, ha_date, work_type, lha}]
        "lha_daily_raw": {
            item["machine"]: item.get("daily", [])
            for item in lha_list
        },
        "harvest": {
            "sun_kg": round(sun_kg),
            "corn_kg": round(corn_kg),
            "wht_kg": round(wht_kg),
            "waste_sun_kg": round(waste_sun_kg),
            "sun_ha": round(sun_ha, 1),
            "corn_ha": round(corn_ha, 1),
            "wht_ha": round(wht_ha, 1),
            "stock": {
                "sun_kg": round(stock_sun),
                "corn_kg": round(stock_corn),
                "wht_kg": round(stock_wht),
                "waste_sun_kg": round(stock_waste),
            },
            "monthly": {
                m: {k: round(v) for k, v in vals.items()}
                for m, vals in sorted(monthly_harvest.items())
            },
            "fields": harvest.get("fields", []),
            "field_plan": [
                {"field": str(x.get("field", "")).strip(), "ha": x.get("ha"), "crop": x.get("crop", "")}
                for x in seeding.get("plan", [])
            ],
            "records": [
                {
                    "date": r.get("date", ""),
                    "field": r.get("field", ""),
                    "ha": r.get("ha", 0) or 0,
                    "sun_kg": r.get("sunflower_kg", 0) or 0,
                    "corn_kg": r.get("corn_kg", 0) or 0,
                    "wht_kg": r.get("wheat_kg", 0) or 0,
                    "waste_sun_kg": r.get("waste_sun_kg", 0) or 0,
                }
                for r in hrecs
                if (r.get("date") or "") >= "2026-01-01"
            ],
        },
    }, ensure_ascii=False)

    # ── Погода — заповнювач (оновлюється вручну / скриптом) ─────
    weather_js = """const WEATHER_FORECAST = [
  { date:"2026-10-26", rain:false, rainMm:0,   tempMax:13.1, rainProb:12, fog:false, cloud:97 },
  { date:"2026-10-27", rain:true,  rainMm:0.9, tempMax:14.1, rainProb:49, fog:false, cloud:93 },
  { date:"2026-10-28", rain:true,  rainMm:0.6, tempMax:11.4, rainProb:80, fog:false, cloud:98 },
  { date:"2026-10-29", rain:true,  rainMm:1.1, tempMax:11.8, rainProb:61, fog:false, cloud:76 },
  { date:"2026-10-30", rain:true,  rainMm:0.3, tempMax:10.7, rainProb:55, fog:false, cloud:99 },
  { date:"2026-10-31", rain:true,  rainMm:2.7, tempMax:11.3, rainProb:73, fog:false, cloud:96 },
  { date:"2026-11-01", rain:false, rainMm:0,   tempMax:10.2, rainProb:25, fog:false, cloud:99 },
  { date:"2026-11-02", rain:false, rainMm:0,   tempMax:9.6,  rainProb:10, fog:false, cloud:35 },
  { date:"2026-11-03", rain:false, rainMm:0,   tempMax:9.1,  rainProb:1,  fog:false, cloud:76 },
  { date:"2026-11-04", rain:false, rainMm:0,   tempMax:8.1,  rainProb:12, fog:false, cloud:69 },
];
const WEATHER_UPDATED = "26.10.2026 15:37 (AccuWeather)";"""

    html = f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Агро Звіт — ТОВ Долинське</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Montserrat:wght@700;800&display=swap">
<style>
:root {{
  --bg:#0f1117;--bg2:#181c27;--bg3:#1f2435;--border:#2a2f42;
  --fg:#e8eaf0;--fg2:#8b93a8;--accent:#4d9fff;--accent2:#2563a8;
  --green:#34d399;--yellow:#fbbf24;--red:#f87171;
  --diesel:#60a5fa;--petrol:#a78bfa;
  color-scheme:dark;
}}
@media (prefers-color-scheme:light){{:root:not([data-theme="dark"]){{
  --bg:#f4f6fb;--bg2:#ffffff;--bg3:#eef0f7;--border:#d4d8e8;
  --fg:#1a1f35;--fg2:#5c6480;--accent:#2563a8;--accent2:#1a4a8a;
  --green:#059669;--yellow:#d97706;--red:#dc2626;
  --diesel:#2563a8;--petrol:#7c3aed;color-scheme:light;
}}}}
:root[data-theme="light"]{{
  --bg:#f4f6fb;--bg2:#ffffff;--bg3:#eef0f7;--border:#d4d8e8;
  --fg:#1a1f35;--fg2:#5c6480;--accent:#2563a8;--accent2:#1a4a8a;
  --green:#059669;--yellow:#d97706;--red:#dc2626;
  --diesel:#2563a8;--petrol:#7c3aed;color-scheme:light;
}}
:root[data-theme="dark"]{{
  --bg:#0f1117;--bg2:#181c27;--bg3:#1f2435;--border:#2a2f42;
  --fg:#e8eaf0;--fg2:#8b93a8;--accent:#4d9fff;--accent2:#2563a8;
  --green:#34d399;--yellow:#fbbf24;--red:#f87171;
  --diesel:#60a5fa;--petrol:#a78bfa;color-scheme:dark;
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--fg);font-size:14px;line-height:1.5;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));}}
.header{{position:sticky;top:env(safe-area-inset-top,0px);z-index:100;background:var(--bg);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;padding-block:12px;}}
.header-left{{display:flex;align-items:center;gap:12px;}}
.header-logo{{display:flex;align-items:center;gap:10px;}}
.header-logo svg{{flex-shrink:0;}}
.header-logo-text{{display:flex;flex-direction:column;gap:0px;line-height:1;}}
.header-logo-text .agro{{font-family:'Montserrat','Inter',system-ui,sans-serif;font-weight:800;font-size:18px;color:var(--fg);letter-spacing:0.02em;}}
.header-logo-text .zvit{{font-family:'Montserrat','Inter',system-ui,sans-serif;font-weight:700;font-size:18px;color:var(--accent);letter-spacing:0.04em;}}
.header-logo-text .sub{{font-size:9px;color:var(--fg3);letter-spacing:0.14em;text-transform:uppercase;margin-top:2px;}}
.header h1{{font-size:16px;font-weight:600;}}
.header-date{{font-size:12px;color:var(--fg2);}}
.theme-toggle{{background:var(--bg3);border:1px solid var(--border);color:var(--fg2);width:32px;height:32px;border-radius:8px;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;}}
.main{{padding-block:16px;display:flex;flex-direction:column;gap:16px;max-width:1400px;margin:0 auto;}}
.section-title{{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--fg2);margin-bottom:10px;}}
.kpi-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;}}
.kpi{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:14px 16px;}}
.kpi-label{{font-size:11px;color:var(--fg2);margin-bottom:4px;}}
.kpi-value{{font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.1;}}
.kpi-unit{{font-size:12px;color:var(--fg2);font-family:'Inter',sans-serif;font-weight:400;margin-left:2px;}}
.kpi-sub{{font-size:11px;color:var(--fg2);margin-top:4px;}}
.kpi-value.green{{color:var(--green);}}.kpi-value.accent{{color:var(--accent);}}.kpi-value.yellow{{color:var(--yellow);}}.kpi-value.diesel{{color:var(--diesel);}}.kpi-value.red{{color:var(--red);}}
.card{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;overflow:hidden;}}
.card-header{{padding:12px 16px;border-bottom:1px solid var(--border);font-weight:600;font-size:13px;display:flex;align-items:center;gap:8px;}}
.tbl-wrap{{overflow-x:auto;}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
th{{text-align:left;padding:8px 12px;font-size:11px;font-weight:600;color:var(--fg2);letter-spacing:.05em;text-transform:uppercase;background:var(--bg3);border-bottom:1px solid var(--border);white-space:nowrap;}}
td{{padding:9px 12px;border-bottom:1px solid var(--border);vertical-align:middle;}}
tr:last-child td{{border-bottom:none;}}tr:hover td{{background:var(--bg3);}}
.num{{font-family:'JetBrains Mono',monospace;font-variant-numeric:tabular-nums;text-align:right;}}
.fuel-bars{{padding:14px 16px;display:flex;flex-direction:column;gap:10px;}}
.fuel-row{{display:flex;align-items:center;gap:10px;min-width:0;}}
.fuel-name{{width:140px;flex-shrink:0;font-size:12px;color:var(--fg2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.fuel-bar-wrap{{flex:1;background:var(--bg3);border-radius:4px;height:8px;min-width:0;overflow:hidden;}}
.fuel-bar{{height:100%;border-radius:4px;background:var(--diesel);transition:width .4s ease;}}
.fuel-val{{width:60px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--fg);flex-shrink:0;}}
.balance-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px;}}
.balance-item{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:14px 16px;}}
.balance-label{{font-size:11px;color:var(--fg2);margin-bottom:6px;}}
.balance-val{{font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:700;font-variant-numeric:tabular-nums;}}
.balance-val.diesel{{color:var(--diesel);}}.balance-val.petrol{{color:var(--petrol);}}
.no-data{{padding:24px;text-align:center;color:var(--fg2);font-size:13px;}}
/* л/га */
.lha-block{{border:1px solid var(--border);border-radius:8px;padding:10px 14px;margin-bottom:10px;background:var(--bg2);}}
.lha-block:last-child{{margin-bottom:0;}}
.lha-header{{display:flex;align-items:center;gap:12px;margin-bottom:8px;flex-wrap:wrap;}}
.lha-machine{{font-weight:700;font-size:0.95rem;flex:1;}}
.lha-total{{color:var(--fg2);font-size:0.8rem;}}
.lha-avg{{font-size:1.05rem;font-weight:600;font-family:'JetBrains Mono',monospace;}}
.lha-last{{font-size:0.78rem;color:var(--fg2);margin-top:6px;padding-top:6px;border-top:1px solid var(--border);}}
/* збирання */
.crop-progress{{padding:14px 16px;display:flex;flex-direction:column;gap:14px;}}
.cp-item{{display:flex;flex-direction:column;gap:6px;}}
.cp-head{{display:flex;align-items:baseline;justify-content:space-between;gap:8px;}}
.cp-name{{font-size:13px;font-weight:600;}}
.cp-nums{{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--fg2);white-space:nowrap;}}
.cp-track{{position:relative;height:12px;background:var(--bg3);border-radius:6px;overflow:hidden;}}
.cp-fill{{height:100%;border-radius:6px;transition:width .5s ease;}}
.cp-pct{{position:absolute;right:6px;top:50%;transform:translateY(-50%);font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.5);}}
.cp-detail{{display:flex;gap:16px;flex-wrap:wrap;}}
.cp-d{{font-size:11px;color:var(--fg2);}}
.cp-d strong{{color:var(--fg);}}
/* погода */
.wx-block{{margin-top:8px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:10px 12px;display:flex;flex-direction:column;gap:7px;}}
.wx-title{{font-size:11px;color:var(--fg2);}}
.wx-calendar{{display:flex;gap:4px;flex-wrap:wrap;}}
.wx-day{{padding:3px 7px;border-radius:5px;font-size:11px;font-family:'JetBrains Mono',monospace;color:#fff;font-weight:600;cursor:default;}}
.wx-summary{{display:flex;gap:10px;flex-wrap:wrap;}}
.wx-item{{font-size:11px;padding:2px 8px;border-radius:4px;font-weight:500;}}
.wx-stop{{background:rgba(248,113,113,.15);color:var(--red);}}.wx-fog{{background:rgba(251,191,36,.15);color:var(--yellow);}}.wx-finish{{background:rgba(52,211,153,.15);color:var(--green);}}
/* ── Календар ───────────────────────────────────────────── */
.date-btn{{background:var(--bg3);border:1px solid var(--border);color:var(--fg);padding:5px 12px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;font-family:'Inter',sans-serif;display:flex;align-items:center;gap:6px;transition:background .15s;white-space:nowrap;}}
.date-btn:hover{{background:var(--border);}}
.date-btn .cal-icon{{font-size:14px;}}
.cal-popup{{display:none;position:fixed;z-index:999;background:var(--bg2);border:1px solid var(--border);border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.45);padding:16px;min-width:280px;}}
.cal-popup.open{{display:block;}}
.cal-nav{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;}}
.cal-nav-btn{{background:none;border:1px solid var(--border);color:var(--fg2);width:28px;height:28px;border-radius:6px;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;}}
.cal-nav-btn:hover{{background:var(--bg3);}}
.cal-month-label{{font-weight:700;font-size:14px;}}
.cal-grid{{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;}}
.cal-dow{{text-align:center;font-size:10px;font-weight:600;color:var(--fg2);padding:3px 0;}}
.cal-day{{width:34px;height:34px;border-radius:6px;font-size:12px;font-family:'JetBrains Mono',monospace;cursor:pointer;border:none;background:transparent;color:var(--fg2);display:flex;align-items:center;justify-content:center;transition:background .1s,color .1s;position:relative;}}
.cal-day.has-data{{color:var(--fg);font-weight:600;background:var(--bg3);}}
.cal-day.has-data:hover{{background:var(--accent2);color:#fff;}}
.cal-day.selected{{background:var(--accent)!important;color:#fff!important;font-weight:700;}}
.cal-day.today-dot::after{{content:'';position:absolute;bottom:3px;left:50%;transform:translateX(-50%);width:4px;height:4px;border-radius:50%;background:var(--accent);}}
.cal-day.selected.today-dot::after{{background:#fff;}}
.cal-day:disabled,.cal-day.empty{{cursor:default;opacity:.2;}}
/* bench */
.bench-grid{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:0;overflow:hidden;border-radius:10px;border:1px solid var(--border);}}
.bench-head{{background:var(--bg3);padding:8px 10px;font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--fg2);border-bottom:1px solid var(--border);}}
.bench-cell{{background:var(--bg2);padding:10px 10px;font-size:13px;border-bottom:1px solid var(--border);}}
.bench-cell:nth-child(4n+1){{font-weight:600;}}
.bench-bar-wrap{{display:flex;align-items:center;gap:8px;}}
.bench-bar-outer{{flex:1;background:var(--bg3);border-radius:3px;height:6px;overflow:hidden;}}
.bench-bar-inner{{height:100%;border-radius:3px;}}
.bench-val{{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;white-space:nowrap;}}
.bench-badge{{display:inline-block;font-size:10px;padding:1px 6px;border-radius:4px;font-weight:600;margin-left:4px;vertical-align:middle;}}
.bench-badge.red{{background:rgba(248,113,113,.15);color:var(--red);}}.bench-badge.yellow{{background:rgba(251,191,36,.15);color:var(--yellow);}}.bench-badge.green{{background:rgba(52,211,153,.15);color:var(--green);}}
/* bench mobile card */
.bench-card{{display:none;flex-direction:column;gap:10px;padding:12px 14px;}}
.bench-card-item{{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:12px 14px;}}
.bench-card-title{{font-size:14px;font-weight:700;margin-bottom:10px;}}
.bench-row{{display:flex;align-items:center;gap:8px;margin-bottom:6px;}}
.bench-row:last-child{{margin-bottom:0;}}
.bench-row-label{{width:110px;flex-shrink:0;font-size:11px;color:var(--fg2);}}
.bench-row-bar{{flex:1;background:var(--bg3);border-radius:3px;height:7px;overflow:hidden;}}
.bench-row-fill{{height:100%;border-radius:3px;}}
.bench-row-val{{width:36px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;flex-shrink:0;}}
@media(max-width:600px){{
  body{{font-size:13px;}}
  .header{{padding-block:10px;gap:6px;}}
  .header h1{{font-size:15px;}}
  .header-date{{font-size:11px;}}
  .date-btn{{padding:6px 10px;font-size:12px;min-height:38px;}}
  .theme-toggle{{width:38px;height:38px;font-size:16px;}}
  .main{{padding-block:12px;gap:12px;}}
  .section-title{{font-size:10px;margin-bottom:8px;}}
  /* KPI */
  .kpi-row{{grid-template-columns:1fr 1fr;gap:8px;}}
  .kpi{{padding:10px 12px;}}
  .kpi-value{{font-size:20px;}}
  /* Баланс */
  .balance-row{{grid-template-columns:1fr 1fr;gap:8px;}}
  .balance-item{{padding:10px 12px;}}
  .balance-val{{font-size:17px;}}
  .balance-label{{font-size:10px;}}
  /* Паливо bars */
  .fuel-name{{width:90px;font-size:11px;}}
  .fuel-val{{width:48px;font-size:11px;}}
  .fuel-bars{{padding:10px 12px;gap:8px;}}
  /* Таблиця */
  th{{padding:6px 8px;font-size:10px;}}
  td{{padding:7px 8px;font-size:12px;}}
  .card-header{{padding:10px 12px;font-size:12px;}}
  /* Бенчмарк — ховаємо grid, показуємо картки */
  .bench-grid{{display:none;}}
  .bench-card{{display:flex;}}
  /* л/га */
  .lha-block{{padding:8px 10px;}}
  .lha-machine{{font-size:0.85rem;}}
  .lha-avg{{font-size:0.95rem;}}
  /* Збирання */
  .crop-progress{{padding:10px 12px;gap:12px;}}
  .cp-name{{font-size:12px;}}
  .cp-nums{{font-size:11px;}}
  /* Календар popup — повна ширина знизу */
  .cal-popup{{
    position:fixed;left:0!important;right:0!important;bottom:0!important;top:auto!important;
    width:100%!important;border-radius:16px 16px 0 0;padding:20px 16px;
    box-shadow:0 -8px 32px rgba(0,0,0,.5);
  }}
  .cal-day{{width:100%;height:40px;font-size:13px;border-radius:8px;}}
  .cal-grid{{gap:4px;}}
  .cal-dow{{font-size:11px;}}
  .cal-month-label{{font-size:15px;}}
  .cal-nav-btn{{width:36px;height:36px;font-size:16px;}}
}}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <div class="header-logo">
      <svg width="38" height="44" viewBox="0 0 56 60" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="26.5" y="6" width="3" height="34" rx="1.5" fill="#5E9A14"/>
        <ellipse cx="20" cy="16" rx="6" ry="4" transform="rotate(-30 20 16)" fill="#7CB518"/>
        <ellipse cx="18" cy="25" rx="6" ry="4" transform="rotate(-25 18 25)" fill="#5E9A14"/>
        <ellipse cx="19" cy="33" rx="5" ry="3.5" transform="rotate(-20 19 33)" fill="#4A7A10"/>
        <ellipse cx="36" cy="16" rx="6" ry="4" transform="rotate(30 36 16)" fill="#7CB518"/>
        <ellipse cx="38" cy="25" rx="6" ry="4" transform="rotate(25 38 25)" fill="#5E9A14"/>
        <ellipse cx="37" cy="33" rx="5" ry="3.5" transform="rotate(20 37 33)" fill="#4A7A10"/>
        <path d="M20 46L28 54L36 46" stroke="#C49A1A" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <div class="header-logo-text">
        <span class="agro">АГРО</span>
        <span class="zvit">ЗВІТ</span>
        <span class="sub">ТОВ «Долинське»</span>
      </div>
    </div>
    <div>
      <div class="header-date" id="reportDateLabel">Завантаження...</div>
    </div>
  </div>
  <div style="display:flex;gap:8px;align-items:center;">
    <button class="date-btn" id="datePickerBtn" onclick="toggleCalendar(event)">
      <span class="cal-icon">📅</span>
      <span id="datePickerLabel">—</span>
    </button>
    <button class="theme-toggle" onclick="toggleTheme()" title="Тема">☀︎</button>
  </div>
</div>

<!-- Календар popup -->
<div class="cal-popup" id="calPopup">
  <div class="cal-nav">
    <button class="cal-nav-btn" onclick="calPrev()">‹</button>
    <span class="cal-month-label" id="calMonthLabel"></span>
    <button class="cal-nav-btn" onclick="calNext()">›</button>
  </div>
  <div class="cal-grid" id="calDow"></div>
  <div class="cal-grid" id="calDays"></div>
</div>

<div class="main">

  <div>
    <div class="section-title">Прогрес збирання сезону</div>
    <div class="card">
      <div class="card-header"><span>📋</span> Виконання плану по культурах</div>
      <div class="crop-progress" id="cropProgress"></div>
    </div>
  </div>

  <div>
    <div class="section-title">Підсумок дня</div>
    <div class="kpi-row" id="kpiRow"></div>
  </div>

  <div>
    <div class="section-title">Паливо</div>
    <div class="balance-row" id="fuelBalanceRow"></div>
    <div style="margin-top:10px" class="card">
      <div class="card-header"><span>⛽</span> <span id="fuelSectionTitle">Витрата ДП по техніці (л)</span></div>
      <div class="fuel-bars" id="fuelBars"></div>
    </div>
  </div>

  <div>
    <div class="section-title" id="lhaSectionTitle">Витрата л/га (розбивка по видах робіт)</div>
    <div class="card">
      <div class="card-header"><span>📊</span> Ефективність по техніці</div>
      <div style="padding:14px 16px" id="lhaBlocks"></div>
    </div>
  </div>

  <div>
    <div class="section-title">Підсумок дня</div>
    <div class="card">
      <div class="card-header"><span>👷</span> Виконані роботи — <span id="workDateLabel">—</span>
        <span style="margin-left:auto;font-family:'JetBrains Mono',monospace;color:var(--accent)" id="workHaTotal"></span>
      </div>
      <div class="tbl-wrap">
        <table><thead><tr>
          <th>№</th><th>Механізатор / Працівник</th><th>Вид роботи</th><th>Поле</th><th>Техніка</th><th class="num">Га / Год</th><th>Культура</th>
        </tr></thead><tbody id="workBody"></tbody></table>
      </div>
    </div>
  </div>

  <div>
    <div class="section-title">Хід збирання по полях</div>
    <div class="card">
      <div class="card-header"><span>🌾</span> Урожайність по полях — наростаючий підсумок</div>
      <div class="tbl-wrap">
        <table id="harvestByFieldTable">
          <thead><tr>
            <th>Поле</th>
            <th class="num">Площа, га</th>
            <th>Культура</th>
            <th class="num">Зібрано, га</th>
            <th class="num">Зібрано, т</th>
            <th class="num">Урожайність, ц/га</th>
          </tr></thead>
          <tbody id="harvestByFieldBody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <div>
    <div class="section-title">Збирання — наростаючий підсумок по місяцях</div>
    <div class="card">
      <div class="card-header"><span>📈</span> Динаміка збирання по місяцях</div>
      <div id="harvestMonthly" style="padding:14px 16px"></div>
    </div>
  </div>

  <div>
    <div class="section-title">Бенчмарк врожайності 2026</div>
    <div class="card">
      <div class="card-header"><span>📊</span> Наше господарство vs Кіровоградська обл. vs Україна · ц/га</div>
      <div id="benchmarkTable"></div>
      <div class="bench-card" id="benchmarkCards"></div>
      <div style="font-size:10px;color:var(--fg2);padding:6px 10px;background:var(--bg3);border-top:1px solid var(--border)">
        Джерела: <a href="https://latifundist.com/urozhaj-online-2026" target="_blank" style="color:var(--accent);text-decoration:none">Latifundist (~19.10.2026)</a> ·
        <a href="https://ukragroconsult.com/news/urozhajnisty-sonyashnyku-v-ukrayini-zrosla-majzhe-na-20-kukurudzy-na-7/" target="_blank" style="color:var(--accent);text-decoration:none">UkrAgroConsult (~19.10.2026)</a>
      </div>
    </div>
  </div>

</div>

<script>
// ─── ДАНІ З ПАЙПЛАЙНУ ─────────────────────────────────────────────────────────
const DATA = {js_data};

// ─── ПЛАН ПО КУЛЬТУРАХ ────────────────────────────────────────────────────────
const CULTURE_PLAN = {{
  "Пшениця":  {{ ha:153, color:"var(--accent)",  icon:"🌾" }},
  "Кукурудза": {{ ha:303, color:"var(--green)",   icon:"🌽" }},
  "Соняшник":  {{ ha:280, color:"var(--yellow)",  icon:"🌻" }},
}};

// ─── ПОГОДА ───────────────────────────────────────────────────────────────────
{weather_js}

// ─── БЕНЧМАРК ─────────────────────────────────────────────────────────────────
const BENCHMARK = [
  {{ icon:"🌻", name:"Соняшник", us:13.3, obl:17.1, ua:22.0, color:"var(--yellow)" }},
  {{ icon:"🌽", name:"Кукурудза", us:25.3, obl:39.9, ua:58.8, color:"var(--green)" }},
  {{ icon:"🌾", name:"Пшениця",   us:33.1, obl:45.1, ua:49.5, color:"var(--accent)" }},
];
// «Наше господарство» — рахуємо з фактичних даних косіння (кг ÷ га), а не вручну
(function() {{
  const h = DATA.harvest || {{}};
  const y = (kg, ha) => (ha > 0 && kg > 0) ? +(kg / ha / 100).toFixed(1) : null;
  const ours = {{ "Соняшник": y(h.sun_kg, h.sun_ha), "Кукурудза": y(h.corn_kg, h.corn_ha), "Пшениця": y(h.wht_kg, h.wht_ha) }};
  BENCHMARK.forEach(r => {{ if (ours[r.name]) r.us = ours[r.name]; }});
}})();

// ─── ТЕМА ─────────────────────────────────────────────────────────────────────
function toggleTheme() {{
  const root = document.documentElement;
  const cur = root.getAttribute("data-theme");
  root.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
  localStorage.setItem("theme", root.getAttribute("data-theme"));
}}
(function() {{
  const saved = localStorage.getItem("theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
}})();

// ─── CALENDAR DATE PICKER ──────────────────────────────────────────────────────
const DATES_WITH_DATA = new Set(DATA.dates_with_data || []);
const DOW_UA = ["Нд","Пн","Вт","Ср","Чт","Пт","Сб"];
const MONTHS_UA = ["Січень","Лютий","Березень","Квітень","Травень","Червень",
                   "Липень","Серпень","Вересень","Жовтень","Листопад","Грудень"];

let calState = {{
  year: 0, month: 0,          // поточна відображена сторінка
  selected: DATA.work_date,   // активна дата (YYYY-MM-DD)
}};

// Ініціалізуємо на вибрану дату
(function initCal() {{
  const d = new Date(calState.selected + "T00:00:00");
  calState.year  = d.getFullYear();
  calState.month = d.getMonth();
}})();

function toggleCalendar(e) {{
  e.stopPropagation();
  const popup = document.getElementById("calPopup");
  if (popup.classList.contains("open")) {{
    popup.classList.remove("open");
    return;
  }}
  // На мобільному — CSS фіксує знизу, не треба позиціонувати
  if (window.innerWidth > 600) {{
    const btn = document.getElementById("datePickerBtn");
    const rect = btn.getBoundingClientRect();
    popup.style.top  = (rect.bottom + window.scrollY + 6) + "px";
    const left = Math.min(rect.left, window.innerWidth - 300);
    popup.style.left = Math.max(8, left) + "px";
  }} else {{
    popup.style.top  = "";
    popup.style.left = "";
  }}
  popup.classList.add("open");
  renderCalendar();
}}

document.addEventListener("click", function(e) {{
  const popup = document.getElementById("calPopup");
  if (!popup.contains(e.target) && e.target.id !== "datePickerBtn") {{
    popup.classList.remove("open");
  }}
}});

function calPrev() {{
  calState.month--;
  if (calState.month < 0) {{ calState.month = 11; calState.year--; }}
  renderCalendar();
}}
function calNext() {{
  calState.month++;
  if (calState.month > 11) {{ calState.month = 0; calState.year++; }}
  renderCalendar();
}}

function renderCalendar() {{
  const {{ year, month, selected }} = calState;
  document.getElementById("calMonthLabel").textContent = MONTHS_UA[month] + " " + year;

  // Дні тижня
  const dowEl = document.getElementById("calDow");
  dowEl.innerHTML = DOW_UA.map(d => `<div class="cal-dow">${{d}}</div>`).join("");

  // Сітка днів
  const firstDay = new Date(year, month, 1).getDay(); // 0=Нд
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const today = new Date().toISOString().slice(0, 10);

  // Зміщення (Пн=0): перетворюємо Нд(0) → 6, решта -1
  const offset = firstDay === 0 ? 6 : firstDay - 1;

  let html = "";
  // Порожні клітинки
  for (let i = 0; i < offset; i++) html += `<div class="cal-day empty"></div>`;

  for (let day = 1; day <= daysInMonth; day++) {{
    const iso = `${{year}}-${{String(month+1).padStart(2,"0")}}-${{String(day).padStart(2,"0")}}`;
    const hasData = DATES_WITH_DATA.has(iso);
    const isSel   = iso === selected;
    const isTod   = iso === today;
    let cls = "cal-day";
    if (hasData) cls += " has-data";
    if (isSel)   cls += " selected";
    if (isTod)   cls += " today-dot";
    if (!hasData && !isSel) {{
      html += `<div class="${{cls}}" title="Немає даних">${{day}}</div>`;
    }} else {{
      html += `<div class="${{cls}}" onclick="selectDate('${{iso}}')" title="${{iso}}">${{day}}</div>`;
    }}
  }}
  document.getElementById("calDays").innerHTML = html;
}}

function selectDate(iso) {{
  calState.selected = iso;
  document.getElementById("calPopup").classList.remove("open");
  renderDateSection(iso);
  // Оновлюємо лейбл кнопки
  const d = new Date(iso + "T00:00:00");
  document.getElementById("datePickerLabel").textContent =
    d.toLocaleDateString("uk-UA", {{day:"numeric", month:"long"}});
  // Повторно малюємо calendar якщо потрібно оновити "selected"
  renderCalendar();
}}

function renderDateSection(iso) {{
  // ── Таблиця робіт ──────────────────────────────────────────────────────────
  const recs = (DATA.all_work_records || []).filter(r => r.date === iso);
  // Га на полі: тільки записи з технікою, без перевезення (інакше га комбайна рахуються двічі)
  const totalHa = recs.filter(r => r.machine && !/перевез/i.test(r.work_type||""))
                      .reduce((s,r) => s + (r.ha||0), 0);
  document.getElementById("workDateLabel").textContent = iso;
  document.getElementById("workHaTotal").textContent = totalHa > 0 ? `Всього: ${{fmtN(totalHa,1)}} га` : "";
  const sorted = [...recs].sort((a,b) => {{
    const aHa = a.ha > 0, bHa = b.ha > 0;
    if (aHa !== bHa) return aHa ? -1 : 1;
    return (b.ha||0) - (a.ha||0);
  }});
  document.getElementById("workBody").innerHTML = sorted.length
    ? sorted.map((r, i) => {{
        const isHa = r.ha > 0;
        const qtyCell = isHa
          ? `<b>${{fmtN(r.ha, 1)}} га</b>`
          : (r.hrs > 0 ? `<span style="color:var(--fg2)">${{fmtN(r.hrs, 0)}} год</span>` : '—');
        const rowStyle = isHa ? "" : "opacity:0.75";
        return `<tr style="${{rowStyle}}">
          <td style="color:var(--fg2);font-size:11px;width:28px">${{i+1}}</td>
          <td style="font-weight:${{isHa ? 600 : 400}};color:${{isHa ? "var(--fg)" : "var(--fg2)"}}">${{r.name || '—'}}</td>
          <td>${{r.work_type}}</td>
          <td style="font-size:12px;color:var(--fg2)">${{r.field || ''}}</td>
          <td style="font-size:11px;color:var(--fg2)">${{r.machine || ''}}</td>
          <td class="num">${{qtyCell}}</td>
          <td style="font-size:11px;color:var(--fg2)">${{r.crop || ''}}</td>
        </tr>`;
      }}).join("")
    : `<tr><td colspan="7" class="no-data">Немає даних за ${{iso}}</td></tr>`;

  // ── Паливо накопичувально з 1-го числа місяця по вибрану дату ─────────────
  const fuelMonthly = DATA.fuel_monthly_raw || {{}};  // {{машина: {{дата: л}}}}
  const monthStart = iso.slice(0, 7) + "-01";  // "YYYY-MM-01"

  // Накопичувальні заправки з 1-го по iso (включно)
  const fuelCum = {{}};
  for (const [machine, dates] of Object.entries(fuelMonthly)) {{
    const total = Object.entries(dates)
      .filter(([d]) => d >= monthStart && d <= iso)
      .reduce((s, [,v]) => s + v, 0);
    if (total > 0) fuelCum[machine] = total;
  }}

  // Заправки тільки за конкретний день (для картки балансу)
  const fuelToday = {{}};
  for (const [machine, dates] of Object.entries(fuelMonthly)) {{
    if (dates[iso]) fuelToday[machine] = dates[iso];
  }}
  const GASOLINE_MACHINES = DATA.petrol_machines || [];
  const isDiesel = k => !GASOLINE_MACHINES.includes(k);
  const isPetrol = k => GASOLINE_MACHINES.includes(k);

  const totalDpDay  = Object.entries(fuelToday).filter(([k])=>isDiesel(k)).reduce((s,[,v])=>s+v,0);
  const totalDpCum  = Object.entries(fuelCum).filter(([k])=>isDiesel(k)).reduce((s,[,v])=>s+v,0);
  const totalBenDay = Object.entries(fuelToday).filter(([k])=>isPetrol(k)).reduce((s,[,v])=>s+v,0);
  const totalBenCum = Object.entries(fuelCum).filter(([k])=>isPetrol(k)).reduce((s,[,v])=>s+v,0);

  const fuelCumEntries = Object.entries(fuelCum).filter(([k])=>isDiesel(k)).sort((a,b)=>b[1]-a[1]);
  const maxFuelCum = fuelCumEntries.length ? fuelCumEntries[0][1] : 1;

  // Динамічний заголовок: "1–5 жовтня" тощо
  const MONTHS_UA_GEN = ["січня","лютого","березня","квітня","травня","червня",
    "липня","серпня","вересня","жовтня","листопада","грудня"];
  const dayNum = parseInt(iso.slice(8));
  const monthIdx = parseInt(iso.slice(5,7)) - 1;
  const periodLabel = dayNum === 1
    ? `1 ${{MONTHS_UA_GEN[monthIdx]}}`
    : `1–${{dayNum}} ${{MONTHS_UA_GEN[monthIdx]}}`;

  // Оновлюємо заголовок секції паливо
  const fuelSectionTitle = document.getElementById("fuelSectionTitle");
  if (fuelSectionTitle) {{
    fuelSectionTitle.textContent = `Витрата ДП ${{periodLabel}}`;
  }}

  // Оновлюємо картки балансу/заправки — динамічно по обраній даті
  const balHist = (DATA.balance_history || []).filter(r => r.date <= iso);
  const balRec = balHist.length ? balHist[balHist.length - 1] : null;
  const balDp = balRec ? (balRec.display_dp || balRec.fact_dp || balRec.theor_dp || 0) : (DATA.balance ? DATA.balance.theor_dp : 0);
  const balDate = balRec ? balRec.date : (DATA.balance ? DATA.balance.date : "—");
  const balEl = document.getElementById("fuelBalanceRow");
  const balBen = balRec ? (balRec.display_ben || balRec.fact_ben || balRec.theor_ben || 0) : 0;
  if (balEl) {{
    balEl.innerHTML = `
      <div class="balance-item">
        <div class="balance-label">Залишок ДП${{balRec && !balRec.fact_dp ? " (теор.)" : ""}} на ${{balDate}}</div>
        <div class="balance-val diesel">${{fmtN(balDp)}}<span style="font-size:13px;font-weight:400;color:var(--fg2);margin-left:4px">л</span></div>
      </div>
      <div class="balance-item">
        <div class="balance-label">Заправлено ДП ${{periodLabel}}</div>
        <div class="balance-val diesel">${{fmtN(totalDpCum)}}<span style="font-size:13px;font-weight:400;color:var(--fg2);margin-left:4px">л</span>
          ${{totalDpDay > 0 ? `<span style="font-size:11px;color:var(--accent);margin-left:6px">+${{fmtN(totalDpDay)}}л сьогодні</span>` : ''}}</div>
      </div>
      ${{balBen > 0 ? `<div class="balance-item">
        <div class="balance-label">Залишок бензину${{balRec && !balRec.fact_ben ? " (теор.)" : ""}} на ${{balDate}}</div>
        <div class="balance-val petrol">${{fmtN(balBen)}}<span style="font-size:13px;font-weight:400;color:var(--fg2);margin-left:4px">л</span></div>
      </div>` : ''}}
      ${{totalBenCum > 0 ? `<div class="balance-item">
        <div class="balance-label">Заправлено бензину ${{periodLabel}}</div>
        <div class="balance-val petrol">${{fmtN(totalBenCum)}}<span style="font-size:13px;font-weight:400;color:var(--fg2);margin-left:4px">л</span>
          ${{totalBenDay > 0 ? `<span style="font-size:11px;color:var(--accent);margin-left:6px">+${{fmtN(totalBenDay)}}л сьогодні</span>` : ''}}</div>
      </div>` : ''}}`;
  }}

  // Оновлюємо бари паливо по техніці (накопичувально) — тільки дизель
  const fuelBarsEl = document.getElementById("fuelBars");
  if (fuelBarsEl) {{
    fuelBarsEl.innerHTML = fuelCumEntries.length
      ? fuelCumEntries.map(([k,v]) => `
          <div class="fuel-row">
            <div class="fuel-name">${{k}}</div>
            <div class="fuel-bar-wrap"><div class="fuel-bar" style="width:${{Math.round(v/maxFuelCum*100)}}%"></div></div>
            <div class="fuel-val">${{fmtN(v)}} л</div>
          </div>`).join("")
      : `<div class="no-data">Немає заправок ДП ${{periodLabel}}</div>`;
  }}

  // ── Збирання за день ────────────────────────────────────────────────────────
  const hAllRecs = (DATA.harvest && DATA.harvest.records) || [];
  const hDay = hAllRecs.filter(r => r.date === iso);
  const hDaySun  = hDay.reduce((s,r) => s + (r.sun_kg||0), 0);
  const hDayCorn = hDay.reduce((s,r) => s + (r.corn_kg||0), 0);
  const hDayWht  = hDay.reduce((s,r) => s + (r.wht_kg||0), 0);
  const hDayHa   = hDay.reduce((s,r) => s + (r.ha||0), 0);

  // Наростаючий підсумок до цієї дати (включно)
  const hCum = hAllRecs.filter(r => r.date <= iso);
  const cumSun  = hCum.reduce((s,r) => s + (r.sun_kg||0), 0);
  const cumCorn = hCum.reduce((s,r) => s + (r.corn_kg||0), 0);
  const cumWht  = hCum.reduce((s,r) => s + (r.wht_kg||0), 0);
  // га по культурах (з наростаючого)
  const cumHaSun  = hCum.filter(r => r.sun_kg > 0).reduce((s,r) => s + (r.ha||0), 0);
  const cumHaCorn = hCum.filter(r => r.corn_kg > 0).reduce((s,r) => s + (r.ha||0), 0);
  const cumHaWht  = hCum.filter(r => r.wht_kg > 0).reduce((s,r) => s + (r.ha||0), 0);

  // Оновлюємо KPI (показуємо "за день / наростаючий")
  const kpiEl = document.getElementById("kpiRow");
  if (kpiEl) {{
    const hasDayHarvest = hDaySun + hDayCorn + hDayWht > 0;
    const kpis = [
      {{ label:"Соняшник", value:fmtN(cumSun/1000,1), unit:"т",  cls:"yellow",
         sub:`${{fmtN(Math.round(cumHaSun))}} га · ${{cumHaSun>0?(cumSun/cumHaSun/100).toFixed(1):0}} ц/га`,
         day: hasDayHarvest && hDaySun > 0 ? `+${{fmtN(hDaySun/1000,1)}}т сьогодні` : null }},
      {{ label:"Кукурудза", value:fmtN(cumCorn/1000,1), unit:"т", cls:"green",
         sub:`${{fmtN(Math.round(cumHaCorn))}} га · ${{cumHaCorn>0?(cumCorn/cumHaCorn/100).toFixed(1):0}} ц/га`,
         day: hasDayHarvest && hDayCorn > 0 ? `+${{fmtN(hDayCorn/1000,1)}}т сьогодні` : null }},
      {{ label:"Пшениця", value:fmtN(cumWht/1000,1), unit:"т",  cls:"accent",
         sub:`${{fmtN(Math.round(cumHaWht))}} га · ${{cumHaWht>0?(cumWht/cumHaWht/100).toFixed(1):0}} ц/га`,
         day: hasDayHarvest && hDayWht > 0 ? `+${{fmtN(hDayWht/1000,1)}}т сьогодні` : null }},
      {{ label:"Всього зібрано", value:fmtN((cumSun+cumCorn+cumWht)/1000,1), unit:"т", cls:"diesel",
         sub:`на ${{iso}}`,
         day: hasDayHarvest ? `+${{fmtN((hDaySun+hDayCorn+hDayWht)/1000,1)}}т за день` : null }},
    ];
    kpiEl.innerHTML = kpis.map(k => `
      <div class="kpi">
        <div class="kpi-label">${{k.label}}</div>
        <div class="kpi-value ${{k.cls}}">${{k.value}}<span class="kpi-unit">${{k.unit}}</span></div>
        ${{k.sub ? `<div class="kpi-sub">${{k.sub}}</div>` : ""}}
        ${{k.day ? `<div class="kpi-sub" style="color:var(--green)">${{k.day}}</div>` : ""}}
      </div>`).join("");
  }}

  // ── Хід збирання по полях ───────────────────────────────────────────────────
  const hFieldBody = document.getElementById("harvestByFieldBody");
  if (hFieldBody) {{
    // Усі поля з довідника (навіть де ще 0) + площа; культура — з плану посівної,
    // для змішаних полів («пшениця 94 га, кукурудза 25 га») — окремий рядок на культуру.
    const norm = v => String(v ?? "").trim().toLowerCase();
    const cropNorm = c => {{ c = norm(c);
      if (c.startsWith("пшен")) return "Пшениця"; if (c.startsWith("кукур")) return "Кукурудза";
      if (c.startsWith("сонях") || c.startsWith("соняш")) return "Соняшник"; return null; }};
    const planByField = {{}};
    for (const p of ((DATA.harvest && DATA.harvest.field_plan) || [])) {{
      const parts = [...String(p.crop||"").matchAll(/([А-Яа-яІіЇїЄєҐґ']+)\\s*(\\d+(?:[.,]\\d+)?)\\s*га/g)];
      planByField[norm(p.field)] = parts.length
        ? parts.map(m => ({{ crop: cropNorm(m[1]), area: parseFloat(m[2].replace(",", ".")) }})).filter(x => x.crop)
        : (cropNorm(p.crop) ? [{{ crop: cropNorm(p.crop), area: null }}] : []);
    }}
    // Фактично зібране по (поле, культура) до обраної дати
    const done = {{}};
    for (const r of hAllRecs.filter(r => r.date <= iso)) {{
      let crop = null, kg = 0;
      if ((r.sun_kg||0) > kg)  {{ crop = "Соняшник";  kg = r.sun_kg; }}
      if ((r.corn_kg||0) > kg) {{ crop = "Кукурудза"; kg = r.corn_kg; }}
      if ((r.wht_kg||0) > kg)  {{ crop = "Пшениця";   kg = r.wht_kg; }}
      if (!crop) continue;
      const k = norm(r.field) + "||" + crop;
      if (!done[k]) done[k] = {{ field: String(r.field), crop, ha: 0, kg: 0 }};
      done[k].ha += r.ha || 0; done[k].kg += kg;
    }}
    const rows = [];
    const used = new Set();
    for (const f of ((DATA.harvest && DATA.harvest.fields) || [])) {{
      const key = norm(f.field);
      let crops = planByField[key] || [];
      // культур з плану нема — беремо з фактичного збирання
      if (!crops.length) crops = Object.values(done).filter(d => norm(d.field) === key).map(d => ({{ crop: d.crop, area: null }}));
      if (!crops.length) crops = [{{ crop: null, area: null }}];
      for (const c of crops) {{
        const d = c.crop ? done[key + "||" + c.crop] : null;
        if (d) used.add(key + "||" + c.crop);
        rows.push({{ field: f.field, area: c.area != null ? c.area : f.area_ha, crop: c.crop, ha: d ? d.ha : 0, kg: d ? d.kg : 0 }});
      }}
    }}
    // Поля, яких нема в довіднику, але є у збиранні
    for (const [k, d] of Object.entries(done)) if (!used.has(k)) rows.push({{ field: d.field, area: null, crop: d.crop, ha: d.ha, kg: d.kg }});
    rows.sort((a,b) => a.field.localeCompare(b.field, "uk", {{numeric:true}}));
    if (rows.length === 0) {{
      hFieldBody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--fg3);padding:16px">Немає даних</td></tr>`;
    }} else {{
      const cropColor = {{ "Соняшник": "var(--yellow)", "Кукурудза": "var(--green)", "Пшениця": "var(--accent)" }};
      hFieldBody.innerHTML = rows.map(r => {{
        const yld = r.ha > 0 ? (r.kg / r.ha / 100) : 0;
        const col = cropColor[r.crop] || "var(--fg2)";
        const pct = r.area > 0 ? Math.min(100, Math.round(r.ha / r.area * 100)) : null;
        const dim = r.ha > 0 ? "" : "opacity:.6";
        return `<tr style="${{dim}}">
          <td style="font-weight:500">${{r.field}}</td>
          <td class="num">${{r.area != null && r.area > 0 ? fmtN(r.area,0) : "—"}}</td>
          <td style="color:${{col}}">${{r.crop || "—"}}</td>
          <td class="num">${{fmtN(r.ha,0)}}${{pct != null ? `<span style="color:var(--fg2);font-size:11px"> (${{pct}}%)</span>` : ""}}</td>
          <td class="num">${{fmtN(r.kg/1000,1)}} т</td>
          <td class="num" style="font-weight:600;color:${{col}}">${{r.ha > 0 ? yld.toFixed(1) + " ц/га" : "—"}}</td>
        </tr>`;
      }}).join("") + (() => {{
        // Підсумок: загальна площа і загальна зібрана площа
        const sArea = rows.reduce((s,r) => s + (r.area > 0 ? r.area : 0), 0);
        const sHa   = rows.reduce((s,r) => s + (r.ha || 0), 0);
        const sKg   = rows.reduce((s,r) => s + (r.kg || 0), 0);
        const sPct  = sArea > 0 ? Math.round(sHa / sArea * 100) : null;
        const bt = "border-top:2px solid var(--border);font-weight:700";
        return `<tr>
          <td style="${{bt}}">Разом</td>
          <td class="num" style="${{bt}}">${{fmtN(sArea,0)}}</td>
          <td style="${{bt}}"></td>
          <td class="num" style="${{bt}}">${{fmtN(sHa,0)}}${{sPct != null ? `<span style="color:var(--fg2);font-size:11px;font-weight:400"> (${{sPct}}%)</span>` : ""}}</td>
          <td class="num" style="${{bt}}">${{fmtN(sKg/1000,1)}} т</td>
          <td style="${{bt}}"></td>
        </tr>`;
      }})();
    }}
  }}

  // ── Л/га накопичувально з 1-го місяця по вибрану дату ─────────────────────
  // Використовуємо lha_daily_raw — Python вже правильно прив'язав заправки до видів роботи
  // (логіка: заправка дня X → найближчий попередній день з га → розподіл по видах пропорційно)
  const lhaDailyRaw = DATA.lha_daily_raw || {{}};

  // Оновлення заголовку секції л/га
  const lhaSectEl = document.getElementById("lhaSectionTitle");
  if (lhaSectEl) lhaSectEl.textContent = `Витрата л/га ${{periodLabel}} (по видах робіт)`;

  // Генерація блоків л/га
  const lhaBl = document.getElementById("lhaBlocks");
  if (lhaBl) {{
    const lhaItems = [];
    for (const [machine, dailyArr] of Object.entries(lhaDailyRaw)) {{
      // Фільтруємо daily-записи по period (monthStart..iso)
      const periodRecs = (dailyArr || []).filter(r => r.date >= monthStart && r.date <= iso);
      if (!periodRecs.length) continue;

      const totalFuel = periodRecs.reduce((s,r) => s + (r.liters||0), 0);
      const totalHa   = periodRecs.reduce((s,r) => s + (r.ha||0), 0);
      const avgLha = (totalFuel && totalHa) ? totalFuel / totalHa : null;

      // Розбивка по видах робіт — агрегуємо з daily-записів
      // кожен запис: liters → ha → work_type (вже правильно розподілено Python)
      const byWorkMap = {{}};
      for (const r of periodRecs) {{
        const wt = r.work_type || "Інше";
        if (!byWorkMap[wt]) byWorkMap[wt] = {{ha: 0, fuel: 0}};
        byWorkMap[wt].ha   += r.ha || 0;
        byWorkMap[wt].fuel += r.liters || 0;
      }}
      const byWork = Object.entries(byWorkMap).map(([wt, v]) => ({{
        wt, ha: v.ha, fuel: v.fuel,
        lha: v.ha > 0 && v.fuel > 0 ? v.fuel / v.ha : null
      }})).sort((a,b) => b.ha - a.ha);

      lhaItems.push({{machine, totalFuel, totalHa, avgLha, byWork}});
    }}
    lhaItems.sort((a,b) => b.totalFuel - a.totalFuel);

    if (lhaItems.length === 0) {{
      lhaBl.innerHTML = `<div class="no-data">Немає даних л/га за ${{periodLabel}}</div>`;
    }} else {{
      let html = "";
      for (const item of lhaItems) {{
        const lowFlag = item.avgLha && item.avgLha < 3;
        const avgColor = item.avgLha && item.avgLha > 25 ? "color:var(--red);font-weight:700"
                       : lowFlag ? "color:var(--yellow)" : "";
        html += `<div class="lha-block">
          <div class="lha-header">
            <span class="lha-machine">${{item.machine}}</span>
            <span class="lha-total">${{fmtN(item.totalFuel)}} л / ${{fmtN(item.totalHa,1)}} га</span>
            <span class="lha-avg" style="${{avgColor}}">${{item.avgLha ? item.avgLha.toFixed(2) : "—"}} л/га</span>
          </div>
          ${{lowFlag ? `<div style="font-size:11px;color:var(--yellow);margin-top:6px">⚠ Заправок замало для такого обсягу робіт — ймовірно, частину палива записано на іншу техніку</div>` : ""}}`;
        if (item.byWork.length > 1) {{
          html += `<table><thead><tr>
            <th>Вид роботи</th>
            <th style="text-align:right">Га</th>
            <th style="text-align:right">Паливо л</th>
            <th style="text-align:right">Л/га</th>
          </tr></thead><tbody>`;
          for (const wt of item.byWork) {{
            const wtColor = wt.lha && wt.lha > 25 ? "color:var(--red)" : "";
            html += `<tr>
              <td>${{wt.wt}}</td>
              <td class="num">${{fmtN(wt.ha,1)}}</td>
              <td class="num">${{fmtN(Math.round(wt.fuel))}}</td>
              <td class="num" style="${{wtColor}}"><b>${{wt.lha ? wt.lha.toFixed(2) : "—"}}</b></td>
            </tr>`;
          }}
          html += `</tbody></table>`;
        }}
        html += `</div>`;
      }}
      lhaBl.innerHTML = html;
    }}
  }}

  // ── Прогрес збирання (наростаючий до обраної дати) ─────────────────────────
  const cpEl = document.getElementById("cropProgress");
  if (cpEl) {{
    const cultMap = {{
      "Соняшник": {{ kg: cumSun, ha: cumHaSun }},
      "Кукурудза": {{ kg: cumCorn, ha: cumHaCorn }},
      "Пшениця":  {{ kg: cumWht, ha: cumHaWht }},
    }};
    let cpHtml = "";
    for (const [name, plan] of Object.entries(CULTURE_PLAN)) {{
      const actual = cultMap[name] || {{kg:0, ha:0}};
      const doneHa = actual.ha;
      const pct = plan.ha > 0 ? Math.min(100, Math.round(doneHa / plan.ha * 100)) : 0;
      const yld = (doneHa > 0 && actual.kg > 0) ? (actual.kg / doneHa / 100).toFixed(1) : null;
      cpHtml += `<div class="cp-item">
        <div class="cp-head">
          <span class="cp-name" style="color:${{plan.color}}">${{plan.icon}} ${{name}}</span>
          <span class="cp-nums">${{fmtN(doneHa)}} / ${{plan.ha}} га (${{pct}}%)</span>
        </div>
        <div class="cp-track">
          <div class="cp-fill" style="width:${{pct}}%;background:${{plan.color}}"></div>
          <span class="cp-pct">${{pct}}%</span>
        </div>
        <div class="cp-detail">
          <span class="cp-d"><strong>${{fmtN(actual.kg/1000, 1)}} т</strong></span>
          ${{yld ? `<span class="cp-d"><strong>${{yld}} ц/га</strong></span>` : ""}}
          <span class="cp-d">залишилось: <strong>${{fmtN(Math.max(0, plan.ha - doneHa))}} га</strong></span>
          <span class="cp-d" style="color:var(--fg2);font-size:10px">← станом на ${{iso}}</span>
        </div>
      </div>`;
    }}
    cpEl.innerHTML = cpHtml;
  }}
}}

// ─── ХЕЛПЕРИ ──────────────────────────────────────────────────────────────────
function fmtN(v, d=0) {{
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (isNaN(n)) return String(v);
  return d === 0 ? Math.round(n).toLocaleString("uk-UA") : n.toFixed(d);
}}

// ─── РЕНДЕР ───────────────────────────────────────────────────────────────────
function render() {{
  const d = DATA;

  // Дата header
  const runDate = new Date().toLocaleDateString("uk-UA", {{day:"numeric",month:"long",year:"numeric"}});
  const dataLabel = new Date(d.data_date + "T00:00:00").toLocaleDateString("uk-UA", {{day:"numeric",month:"long"}});
  document.getElementById("reportDateLabel").innerHTML =
    `Звіт від <b>${{runDate}}</b> <span style="color:var(--fg2);">(дані на ${{dataLabel}})</span>`;
  // Ставимо початкову дату у кнопці
  (function initDateBtn() {{
    const selDate = new Date(calState.selected + "T00:00:00");
    document.getElementById("datePickerLabel").textContent =
      selDate.toLocaleDateString("uk-UA", {{day:"numeric", month:"long"}});
  }})();

  // Прогрес збирання, KPI, паливо — рендеряться через renderDateSection
  // (викликається нижче разом з початковою датою)

  // ── Підсумок дня (всі працівники) — initial render ──────────────────────
  renderDateSection(calState.selected);

  // ── Збирання по місяцях ───────────────────────────────────────────────────
  const h = d.harvest || {{}};
  const monthly = h.monthly || {{}};
  const stock = h.stock || {{}};
  const months = Object.keys(monthly).sort();
  const MONTH_UA = {{"01":"Січ","02":"Лют","03":"Бер","04":"Квіт","05":"Трав","06":"Черв",
                     "07":"Лип","08":"Серп","09":"Вер","10":"Жовт","11":"Лист","12":"Груд"}};
  const hmEl = document.getElementById("harvestMonthly");
  if (months.length) {{
    let tbl = `<table><thead><tr><th>Культура</th>`;
    tbl += months.map(m => `<th style="text-align:right">${{MONTH_UA[m.slice(5)] || m.slice(5)}}</th>`).join("");
    tbl += `<th style="text-align:right">Всього т</th></tr></thead><tbody>`;
    const cultures = [
      {{ key:"sun",   name:"🌻 Соняшник",      color:"var(--yellow)", total:h.sun_kg,      stockKg: stock.sun_kg }},
      {{ key:"corn",  name:"🌽 Кукурудза",      color:"var(--green)",  total:h.corn_kg,     stockKg: stock.corn_kg }},
      {{ key:"wht",   name:"🌾 Пшениця",        color:"var(--accent)", total:h.wht_kg,      stockKg: stock.wht_kg }},
      {{ key:"waste", name:"🗑 Мусор соняху",   color:"var(--fg2)",   total:h.waste_sun_kg, stockKg: stock.waste_sun_kg }},
    ];
    for (const c of cultures) {{
      // Пропускаємо рядок якщо і всього і залишок = 0
      if (!(c.total > 0) && !(c.stockKg > 0)) continue;
      tbl += `<tr>`;
      tbl += `<td style="color:${{c.color}};font-weight:600">${{c.name}}</td>`;
      tbl += months.map(m => {{
        const kg = (monthly[m] && monthly[m][c.key]) || 0;
        return `<td class="num">${{kg > 0 ? fmtN(kg/1000,1)+"т" : "—"}}</td>`;
      }}).join("");
      tbl += `<td class="num"><b>${{fmtN((c.total||0)/1000,1)}} т</b></td>`;
      tbl += `</tr>`;
    }}
    tbl += `</tbody></table>`;

    // Блок залишків на складі
    const stockItems = cultures.filter(c => c.stockKg > 0);
    let stockHtml = "";
    if (stockItems.length) {{
      stockHtml = `<div style="margin-top:12px;padding:12px 16px;background:var(--bg3);border-radius:8px;border-left:3px solid var(--accent)">
        <div style="font-size:11px;color:var(--fg2);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">📦 Залишок на току</div>
        <div style="display:flex;flex-wrap:wrap;gap:16px">
          ${{stockItems.map(c => `<div><span style="color:${{c.color}};font-weight:600">${{c.name}}</span>
            <span style="margin-left:6px;font-family:'JetBrains Mono',monospace;font-size:14px">${{fmtN(c.stockKg/1000,1)}} т</span></div>`).join("")}}
        </div>
      </div>`;
    }}
    hmEl.innerHTML = tbl + stockHtml;
  }} else {{
    hmEl.innerHTML = `<div class="no-data">Немає даних</div>`;
  }}

  // посівна — прибрано

  // ── Бенчмарк ──────────────────────────────────────────────────────────────
  const maxV = Math.max(...BENCHMARK.map(r => r.ua));
  const pct = v => Math.round(v/maxV*100);
  const badge = (us, ref) => {{
    const delta = ((us-ref)/ref*100).toFixed(0);
    const cls = delta >= 0 ? "green" : delta > -15 ? "yellow" : "red";
    return `<span class="bench-badge ${{cls}}">${{delta >= 0 ? "+" : ""}}${{delta}}%</span>`;
  }};
  // Десктоп: grid
  document.getElementById("benchmarkTable").innerHTML = `
    <div class="bench-grid">
      <div class="bench-head">Культура</div>
      <div class="bench-head">🏠 Наше</div>
      <div class="bench-head">🌍 Кіровоград. обл.</div>
      <div class="bench-head">🇺🇦 Україна</div>
      ${{BENCHMARK.map((r,i) => {{
        const isLast = i === BENCHMARK.length-1;
        const bs = isLast ? "border-bottom:none" : "";
        return `
          <div class="bench-cell" style="${{bs}}">${{r.icon}} ${{r.name}}</div>
          <div class="bench-cell" style="${{bs}}">
            <div class="bench-bar-wrap">
              <div class="bench-bar-outer"><div class="bench-bar-inner" style="width:${{pct(r.us)}}%;background:${{r.color}}"></div></div>
              <span class="bench-val" style="color:${{r.color}}">${{r.us}}</span>
            </div>
            ${{badge(r.us, r.obl)}}
          </div>
          <div class="bench-cell" style="${{bs}}">
            <div class="bench-bar-wrap">
              <div class="bench-bar-outer"><div class="bench-bar-inner" style="width:${{pct(r.obl)}}%;background:${{r.color}};opacity:.7"></div></div>
              <span class="bench-val" style="color:var(--fg2)">${{r.obl}}</span>
            </div>
          </div>
          <div class="bench-cell" style="${{bs}}">
            <div class="bench-bar-wrap">
              <div class="bench-bar-outer"><div class="bench-bar-inner" style="width:${{pct(r.ua)}}%;background:${{r.color}};opacity:.45"></div></div>
              <span class="bench-val" style="color:var(--fg2)">${{r.ua}}</span>
            </div>
          </div>`;
      }}).join("")}}
    </div>`;
  // Мобільний: картки по культурах
  const cardsEl = document.getElementById("benchmarkCards");
  if (cardsEl) {{
    cardsEl.innerHTML = BENCHMARK.map(r => `
      <div class="bench-card-item">
        <div class="bench-card-title" style="color:${{r.color}}">${{r.icon}} ${{r.name}}</div>
        <div class="bench-row">
          <div class="bench-row-label">🏠 Наше господарство</div>
          <div class="bench-row-bar"><div class="bench-row-fill" style="width:${{pct(r.us)}}%;background:${{r.color}}"></div></div>
          <div class="bench-row-val" style="color:${{r.color}}">${{r.us}}</div>
          ${{badge(r.us, r.obl)}}
        </div>
        <div class="bench-row">
          <div class="bench-row-label">🌍 Кіровоград. обл.</div>
          <div class="bench-row-bar"><div class="bench-row-fill" style="width:${{pct(r.obl)}}%;background:${{r.color}};opacity:.65"></div></div>
          <div class="bench-row-val" style="color:var(--fg2)">${{r.obl}}</div>
        </div>
        <div class="bench-row">
          <div class="bench-row-label">🇺🇦 Україна</div>
          <div class="bench-row-bar"><div class="bench-row-fill" style="width:${{pct(r.ua)}}%;background:${{r.color}};opacity:.4"></div></div>
          <div class="bench-row-val" style="color:var(--fg2)">${{r.ua}}</div>
        </div>
      </div>`).join("");
  }}
}}

// ─── ПОГОДНЯ МОДЕЛЬ ───────────────────────────────────────────────────────────
function calcWorkDays(forecastArr) {{
  const result = [];
  let skipRemaining = 0;
  for (let i = 0; i < forecastArr.length; i++) {{
    const d = forecastArr[i];
    if (skipRemaining >= 1) {{
      result.push({{ date:d.date, coeff:0, status:"🌧 простій після дощу", temp:d.tempMax }});
      skipRemaining = Math.max(0, skipRemaining - 1);
      if (d.rain && d.rainMm >= 0.5) {{
        const stop = d.tempMax >= 12 ? 1.0 : d.tempMax >= 8 ? 1.5 : 2.0;
        skipRemaining = Math.max(skipRemaining, stop);
      }}
      continue;
    }}
    if (d.rain && d.rainMm >= 0.5) {{
      const stop = d.tempMax >= 12 ? 1.0 : d.tempMax >= 8 ? 1.5 : 2.0;
      skipRemaining = stop;
      result.push({{ date:d.date, coeff:0, status:`🌧 дощ ${{d.rainMm}}мм`, temp:d.tempMax }});
      continue;
    }}
    let coeff = 1.0, status = "✅ робочий";
    if (d.fog || d.cloud >= 90) {{ coeff = 0.71; status = `⚠️ хмари ${{d.cloud}}%`; }}
    result.push({{ date:d.date, coeff, status, temp:d.tempMax }});
  }}
  return result;
}}

function calcFinishDate(leftHa, pacePerDay, workDays) {{
  if (!pacePerDay || !leftHa) return null;
  let remaining = leftHa;
  let calDays = 0;
  for (const wd of workDays) {{
    remaining -= pacePerDay * wd.coeff;
    calDays++;
    if (remaining <= 0) break;
  }}
  if (remaining > 0) calDays += Math.ceil(remaining / pacePerDay);
  const fin = new Date();
  fin.setDate(fin.getDate() + calDays);
  return {{ finish:fin, calDays }};
}}

// ─── СТАРТ ────────────────────────────────────────────────────────────────────
render();
</script>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data.json")
    parser.add_argument("--output", default="index.html")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"[ERROR] {data_path}", file=sys.stderr)
        sys.exit(1)

    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    html = build_html(data)
    out_path = Path(args.output)
    out_path.write_text(html, encoding="utf-8")
    print(f"[OK] Записано {out_path} ({len(html):,} байт)")


if __name__ == "__main__":
    main()
