"""Verified Taiwan holiday dates, separated from each employee's agreed schedule.

The government calendar is reference data. Calling calendar_month() never turns
government substitute holidays into company leave without an explicit agreement.
"""

from __future__ import annotations

import calendar
import json
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "calendar-2026.json"
VERIFIED_YEARS = (2026,)


def _load_data(year: int) -> dict:
    if type(year) is not int or year not in VERIFIED_YEARS:
        raise ValueError("僅支援已核對的 2026 年行事曆；請先更新並核對年度資料。")
    with DATA_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if data["metadata"]["year"] != year:
        raise ValueError("行事曆年度資料不一致。")
    return data


def _suggest_substitutions(holidays: dict[str, dict], agreements: Mapping[str, str]) -> dict[str, str]:
    """Return original -> suggested day for the fixed Saturday/Sunday policy.

    This is a proposal, never an employee agreement. Reserve all holiday dates
    before allocating substitutes, so Lunar New Year skips its remaining days
    and two holidays cannot consume the same substitute day.
    """
    occupied = set(holidays) | set(agreements.values())
    result = {}
    for original in sorted(holidays):
        if original in agreements:
            continue
        holiday = date.fromisoformat(original)
        if holiday.weekday() < 5:
            continue
        step = timedelta(days=-1 if holiday.weekday() == 5 else 1)
        candidate = holiday + step
        while candidate.weekday() >= 5 or candidate.isoformat() in occupied:
            candidate += step
        if candidate.year != holiday.year:
            raise ValueError("補假跨至未核對的年度，需另行確認。")
        result[original] = candidate.isoformat()
        occupied.add(candidate.isoformat())
    return result


def _validate_agreements(agreements: Mapping[str, str], holidays: dict[str, dict], year: int) -> None:
    if not isinstance(agreements, Mapping):
        raise ValueError("補假設定須為原國定假日對補假日的對照表。")
    targets = set()
    for original, target in agreements.items():
        if original not in holidays or date.fromisoformat(original).weekday() < 5:
            raise ValueError("補假來源必須是本班制遇休息日或例假的國定假日。")
        try:
            target_date = date.fromisoformat(target)
        except (TypeError, ValueError) as exc:
            raise ValueError("補假日期必須為 YYYY-MM-DD。") from exc
        if target != target_date.isoformat():
            raise ValueError("補假日期必須為 YYYY-MM-DD。")
        if target_date.year != year:
            raise ValueError("補假日期超出已核對年度。")
        if target_date.weekday() >= 5 or target in holidays or target in targets:
            raise ValueError("補假須排在其他工作日，且不得與其他假日或補假重複。")
        targets.add(target)


def calendar_month(year: int, month: int, *, agreed_substitutions: Mapping[str, str] | None = None) -> dict:
    """Return a month under the fixed Mon-Fri / Sat rest / Sun regular-off plan.

    ``agreed_substitutions`` maps statutory dates to agreed substitute dates.
    The caller must verify and retain the employee agreement before supplying
    it; this pure calendar function neither obtains consent nor persists shifts.
    """
    data = _load_data(year)
    if type(month) is not int or not 1 <= month <= 12:
        raise ValueError("月份必須為 1 至 12 的整數。")
    holidays = {entry["date"]: entry for entry in data["statutory_holidays"]}
    sources = {entry["id"]: entry["url"] for entry in data["metadata"]["sources"]}
    agreements = {} if agreed_substitutions is None else agreed_substitutions
    _validate_agreements(agreements, holidays, year)
    proposed = _suggest_substitutions(holidays, agreements)
    agreed_by_target = {target: original for original, target in agreements.items()}
    proposed_by_target = {target: original for original, target in proposed.items() if original not in agreements}
    government_substitutes = {entry["date"] for entry in data["government_calendar"]["substitutions"]}
    days = []
    for number in range(1, calendar.monthrange(year, month)[1] + 1):
        current = date(year, month, number)
        key = current.isoformat()
        weekday = current.weekday()
        kind = "rest_day" if weekday == 5 else "regular_day_off" if weekday == 6 else "weekday"
        name = {"rest_day": "休息日", "regular_day_off": "例假日", "weekday": "工作日"}[kind]
        holiday = holidays.get(key)
        source = "fixed_weekend_policy"
        substitute_for = agreed_by_target.get(key)
        if holiday:
            name = holiday["name"] if weekday < 5 else f"{name}（{holiday['name']}；應另補假）"
            source = sources["mol_holidays"]
            if weekday < 5:
                kind = "national_holiday"
        elif substitute_for:
            kind = "national_holiday"
            name = f"{holidays[substitute_for]['name']}補假（已協商）"
            source = sources["mol_transfer"]
        proposed_for = proposed_by_target.get(key)
        days.append({
            "date": key,
            "name": name,
            "kind": kind,
            "is_holiday": kind != "weekday",
            "source": source,
            "statutory_holiday": holiday["name"] if holiday else None,
            "substitute_for": substitute_for,
            "requires_agreement": proposed_for is not None,
            "proposed_substitute_for": proposed_for,
            "government_is_holiday": weekday >= 5 or key in holidays or key in government_substitutes,
            "normal_working_hours": 8 if kind == "weekday" else 0,
        })
    proposals = [
        {"date": target, "name": f"{holidays[original]['name']}補假", "substitute_for": original,
         "requires_agreement": True, "source": sources["dgpa_2026"]}
        for original, target in proposed.items()
        if original not in agreements and int(target[5:7]) == month
    ]
    warnings = [
        "本表採週一至五每日 8 小時、週六休息日、週日例假的固定班制；輪班與其他合法班制應依員工實際班表判定。",
        "政府補假只作參考；民間補假須勞雇協商。建議補假在完成協商前仍標為工作日，不代表可免除補假義務。",
        "本表未自動套用原住民族歲時祭儀、具投票權者投票日、天然災害出勤措施或個別公司優於法令的假期。",
        "行事曆不直接變更排班或計薪；國定假日調移仍須明確約定日期、取得個別勞工同意並保留紀錄。",
    ]
    pending = [original for original in proposed if original not in agreements]
    return {
        "year": year, "month": month, "timezone": data["metadata"]["timezone"],
        "policy": "fixed_weekend", "verified_at": data["metadata"]["verified_at"],
        "days": days, "proposed_substitutions": proposals,
        "pending_substitution_count_year": len(pending),
        "government_calendar_is_reference_only": True,
        "warnings": warnings, "sources": data["metadata"]["sources"],
    }
