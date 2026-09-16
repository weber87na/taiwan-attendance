"""Taiwan's ordinary working-hours rules, verified against official sources.

These helpers cover the standard 8-hour/40-hour monthly salaried arrangement.
They deliberately do not authorize overtime, special schedules, or payroll.
See docs/labor-rules.md for scope, assumptions, and the source review register.
"""

from calendar import monthrange
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
import re


RULE_VERSION = "TW-LSA-2026-09-16"
VERIFIED_ON = "2026-09-16"
SOURCE_URLS = {
    "lsa": "https://laws.gov.taipei/Law/LawSearch/LawArticleContent/FL014930",
    "overtime": "https://calcr2.mol.gov.tw/Monthly",
    "multipliers": "https://www.mol.gov.tw/1607/28162/28166/28180/28198/28202/",
    "annual": "https://calcr2.mol.gov.tw/RestDays",
    "leave": "https://laws.mol.gov.tw/FLAW/PrintFLAWDAT0202.aspx?id=FL014935&ldate=20251209",
    "sick_2026": "https://www.mol.gov.tw/1607/28162/28166/28218/86988/87100/post",
    "equality": "https://www.mol.gov.tw/1607/28162/28166/28284/48173/33616/",
    "menstrual": "https://www.mol.gov.tw/1607/1632/1640/32923/post",
    "family_2026": "https://www.mol.gov.tw/1607/28162/28166/28284/28294/84873/post",
}


def _date(value: str, name: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{name} 必須為 YYYY-MM-DD 日期")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} 不是有效日期") from exc


def _minutes(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} 必須為非負整數分鐘")
    return value


def _anniversary(start: date, months: int) -> date:
    """Calendar anniversary, with an employee-favourable last-day fallback."""
    offset = start.year * 12 + start.month - 1 + months
    year, month0 = divmod(offset, 12)
    month = month0 + 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def annual_leave_days(hire_date: str, as_of: str) -> int:
    """Current anniversary-period grant, not cumulative or unused balance.

    Service must be continuous and fully countable. When a target month has
    no corresponding date, this project's favourable policy grants at month
    end (e.g. February 29 -> February 28), not a 365-day approximation.
    """
    hired, current = _date(hire_date, "hire_date"), _date(as_of, "as_of")
    if current < hired:
        raise ValueError("as_of 不得早於到職日")
    # Avoid overflowing date.max for a future six-month anniversary.
    elapsed_months = (current.year - hired.year) * 12 + current.month - hired.month
    if elapsed_months < 6:
        return 0
    if current < _anniversary(hired, 6):
        return 0
    years = current.year - hired.year
    if current < _anniversary(hired, years * 12):
        years -= 1
    if years == 0:
        return 3
    if years == 1:
        return 7
    if years == 2:
        return 10
    if years < 5:
        return 14
    if years < 10:
        return 15
    return min(30, years + 6)


def overtime_pay(hourly_wage, minutes: int, day_type: str) -> dict:
    """Additional pay for a standard 8-hour monthly salaried workday.

    weekday minutes exclude the regular eight hours. rest_day and
    national_holiday minutes include all hours worked on that day. Monthly
    base salary already covers the paid holiday/rest-day normal wage.
    Each tier rounds upwards to cents, a conservative project policy, and
    tier amounts sum exactly to pay. Invalid/unsupported cases raise ValueError.
    """
    valid_days = {"weekday", "rest_day", "national_holiday", "regular_day_off"}
    if not isinstance(day_type, str) or day_type not in valid_days:
        raise ValueError("不支援的 day_type")
    duration = _minutes(minutes, "minutes")
    if isinstance(hourly_wage, bool) or not isinstance(hourly_wage, (str, int, float, Decimal)):
        raise ValueError("hourly_wage 必須為正數")
    try:
        wage = Decimal(str(hourly_wage))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("hourly_wage 必須為有效正數") from exc
    if not wage.is_finite() or wage <= 0 or wage > Decimal("1000000000"):
        raise ValueError("hourly_wage 必須大於 0 且不超過 1000000000")
    if wage.as_tuple().exponent < -12:
        raise ValueError("hourly_wage 最多支援 12 位小數")
    if day_type == "regular_day_off":
        raise ValueError("例假原則禁止出勤；天災、事變或突發事件須另依勞基法第40條處理，非一般加班試算範圍")
    limit = 240 if day_type == "weekday" else 720
    if duration > limit:
        raise ValueError(f"本一般工時試算不支援 {day_type} 超過 {limit} 分鐘；不代表免除已工作時間的工資義務")

    segments = []
    if day_type == "weekday":
        segments = [(min(duration, 120), 4, 3, "平日前2小時"),
                    (max(0, duration - 120), 5, 3, "平日第3至4小時")]
    elif day_type == "rest_day":
        segments = [(min(duration, 120), 4, 3, "休息日前2小時"),
                    (min(max(0, duration - 120), 360), 5, 3, "休息日第3至8小時"),
                    (max(0, duration - 480), 8, 3, "休息日第9至12小時")]
    elif duration:
        segments = [(480, 1, 1, "國定假日8小時內出勤，另加一日工資"),
                    (min(max(0, duration - 480), 120), 4, 3, "國定假日第9至10小時"),
                    (max(0, duration - 600), 5, 3, "國定假日第11至12小時")]
    breakdown = []
    with localcontext() as context:
        context.prec = 48
        total = Decimal("0.00")
        for count, numerator, denominator, label in segments:
            if not count:
                continue
            amount = (wage * count * numerator / (60 * denominator)).quantize(
                Decimal("0.01"), rounding=ROUND_CEILING
            )
            total += amount
            breakdown.append({"label": label, "minutes": count,
                              "multiplier": f"{numerator}/{denominator}",
                              "pay": format(amount, ".2f")})
    warnings = [
        "適用月薪已含例假、休息日及休假日原工資、每日正常8小時的一般制度；時薪制、部分工時、彈性工時不適用。",
        "試算不表示加班已獲合法同意；須另檢查工會或勞資會議程序、個別同意、工時與休息。",
        "各級距以精確分數運算後無條件進位至小數第2位，屬避免低估的系統試算政策。",
    ]
    if day_type == "national_holiday":
        warnings.append("國定假日須為原排定工作日且未合法調移；出勤未滿8小時仍另加8小時工資，須先取得勞工同意。")
    if day_type == "rest_day":
        warnings.append("休息日的實際工作分鐘須計入每月延長工時；星期六不當然是休息日。")
    return {"day_type": day_type, "minutes": duration,
            "hourly_wage": format(wage, "f"), "pay": format(total, ".2f"),
            "currency": "TWD", "pay_basis": "additional_to_monthly_base",
            "breakdown": breakdown, "warnings": warnings,
            "rule_version": RULE_VERSION, "verified_on": VERIFIED_ON,
            "source_urls": [SOURCE_URLS["lsa"], SOURCE_URLS["overtime"], SOURCE_URLS["multipliers"]]}


def validate_hours(daily_minutes: int, weekly_minutes: int, monthly_overtime_minutes: int) -> list[str]:
    """Warnings only: daily TOTAL, weekly NORMAL, monthly OVERTIME minutes.

    A clean result is not a compliance certification: this signature cannot
    inspect rests, consecutive shifts/days, overtime authorization, or rolling
    three-month totals. The optional 54h/138h arrangement is not enabled.
    """
    daily = _minutes(daily_minutes, "daily_minutes")
    weekly = _minutes(weekly_minutes, "weekly_minutes")
    monthly = _minutes(monthly_overtime_minutes, "monthly_overtime_minutes")
    messages = []
    if daily > 720:
        messages.append("每日正常及延長工時合計超過12小時，不符一般制度上限。")
    elif daily > 480:
        messages.append("每日總工時超過8小時，應區分延長工時並檢查加班費與同意程序。")
    if weekly > 2400:
        messages.append("每週正常工時超過40小時，不符一般制度；不得把加班算為正常工時。")
    if monthly > 2760:
        messages.append("每月延長工時超過46小時；本系統未啟用須另經法定程序的54小時／3個月138小時例外。")
    return messages


_LEAVE_POLICIES = {
    "annual": {
        "label": "特別休假", "annual_days": None, "period": "employment_anniversary",
        "paid_ratio": "1", "attendance_bonus_protected": True,
        "notes": ["依 annual_leave_days 計算本期給假額度；須另扣已休、保留遞延與結清紀錄。", "滿半年3日、1年7日、2年10日、3至4年14日、5至9年15日、10年16日，逐年加1至30日。", "原則由勞工排定；未休結清、遞延與契約終止須另處理。"], "sources": ["lsa", "annual"],
    },
    "personal": {
        "label": "事假", "annual_days": 14, "period": "year", "paid_ratio": "0",
        "attendance_bonus_protected": False,
        "notes": ["因個人事故必須親自處理；家庭照顧假與照顧家人事假均併入本14日額度。", "照顧家人事假應選 family_care_personal，不能套一般事假的全勤處理。"], "sources": ["leave"],
    },
    "sick": {
        "label": "普通傷病假（未住院）", "annual_days": 30, "period": "year", "paid_ratio": "0.5",
        "protected_days_per_year": 10, "attendance_bonus_protected": False,
        "attendance_bonus_rule": "proportional_deduction_only",
        "notes": ["一年30日內半薪；領有勞保普通傷病給付未達半薪者，由雇主補足。", "未住院年30日；住院與未住院合計2年不得超過1年，住院額度需另行審查。", "2026年起普通傷病假一年未超過10日不得因病假不利處分；超過也不得僅以病假日數考核。", "全勤獎金只得按病假日數比例扣發；妊娠未滿3個月流產未請產假而請病假時不得影響全勤。", "癌症含原位癌門診及醫囑安胎休養併入住院病假；本類別不自動處理。"], "sources": ["leave", "sick_2026"],
    },
    "menstrual": {
        "label": "生理假", "annual_days": None, "days_per_month": 1, "period": "month",
        "paid_ratio": "0.5", "attendance_bonus_protected": True, "counts_toward_sick_after_days": 3,
        "notes": ["每月1日；全年前3日不計病假，其餘併入病假額度。", "通常半薪；年度病假與額外3日半薪額度用畢後，仍可請生理假但雇主得不給薪。", "無須提出證明；不得以缺勤影響全勤、考績或作其他不利處分。"], "sources": ["equality", "menstrual"],
    },
    "marriage": {
        "label": "婚假", "annual_days": None, "days_per_event": 8, "period": "event", "paid_ratio": "1",
        "attendance_bonus_protected": True,
        "notes": ["每次依法結婚8日；須另檢查結婚事件與適用請休期間。"], "sources": ["leave"],
    },
    "bereavement": {
        "label": "喪假", "annual_days": None, "period": "event", "paid_ratio": "1",
        "attendance_bonus_protected": True,
        "days_by_relationship": {"parent_or_adoptive_or_step_parent_or_spouse": 8, "grandparent_or_child_or_spouse_parent": 6, "great_grandparent_or_sibling_or_spouse_grandparent": 3},
        "notes": ["8日：父母、養父母、繼父母、配偶。", "6日：祖父母、子女、配偶父母（含養父母、繼父母）。", "3日：曾祖父母、兄弟姊妹、配偶祖父母；關係與事件須另審查。"], "sources": ["leave"],
    },
    "maternity": {
        "label": "產假", "annual_days": None, "days_per_event": 56, "period": "event_calendar_days",
        "paid_ratio": None, "attendance_bonus_protected": True,
        "paid_ratio_by_tenure": {"at_least_6_months": "1", "under_6_months": "0.5"},
        "notes": ["一般分娩8星期按曆連續計；勞基法適用者滿6個月全薪、未滿6個月半薪。", "流產另依妊娠期間給4星期、1星期或5日；未滿3個月流產不直接套用本薪資比例，須另審查。", "此處工資與勞保生育給付為不同制度，不自動申請或核算保險給付。"], "sources": ["lsa", "equality"],
    },
    "paternity": {
        "label": "陪產檢及陪產假", "annual_days": None, "days_per_event": 7, "period": "pregnancy_event",
        "paid_ratio": "1", "attendance_bonus_protected": True,
        "notes": ["配偶產檢及分娩合計7日，不能各給7日；陪產在分娩當日及其前後合計15日內請休。", "可選日、半日或小時，單位選定後不得變更；額度依約定正常工時計。"], "sources": ["equality"],
    },
    "prenatal": {
        "label": "產檢假", "annual_days": None, "days_per_event": 7, "period": "pregnancy_event",
        "paid_ratio": "1", "attendance_bonus_protected": True,
        "notes": ["妊娠期間合計7日；可選日、半日或小時，單位選定後不得變更。"], "sources": ["equality"],
    },
    "family_care": {
        "label": "家庭照顧假", "annual_days": 7, "period": "year", "paid_ratio": "0",
        "attendance_bonus_protected": True, "counts_toward": "personal",
        "standard_annual_hours": 56, "hourly_allowed": True,
        "notes": ["家庭成員預防接種、嚴重疾病或重大事故需親自照顧；併入事假14日額度。", "2026年起可按小時；每日正常8小時為56小時，其他約定工時須調整；選定小時單位後不得變更。", "不得因請本假影響全勤、考績；用完後可按符合條件的照顧家人事假處理。"], "sources": ["family_2026", "equality"],
    },
    "family_care_personal": {
        "label": "照顧家人事假", "annual_days": None, "period": "year", "paid_ratio": "0",
        "attendance_bonus_protected": True, "counts_toward": "personal", "hourly_allowed": True,
        "notes": ["2026年起親自照顧家庭成員可依事假規定按小時請假，使用剩餘事假14日共享額度。", "不得扣全勤；考核保護與性別平等工作法家庭照顧假不同，不能混為相同假別。"], "sources": ["leave", "family_2026"],
    },
    "public": {
        "label": "公假", "annual_days": None, "period": "actual_need", "paid_ratio": "1",
        "attendance_bonus_protected": True,
        "notes": ["須有法令依據，依實際需要核給，不能自設全年固定上限。"], "sources": ["leave"],
    },
    "occupational_injury": {
        "label": "公傷病假", "annual_days": None, "period": "treatment_and_recovery", "paid_ratio": None,
        "attendance_bonus_protected": True,
        "notes": ["職災治療及休養期間給假；原領工資補償與保險抵充應依勞基法59條及個案另處理。", "不套用普通病假30日或半薪規則。"], "sources": ["leave", "lsa"],
    },
}


def leave_policy(kind: str) -> dict:
    """Return descriptive minimum rules, not an approval/benefit decision."""
    if not isinstance(kind, str) or kind not in _LEAVE_POLICIES:
        raise ValueError("不支援的假別")
    policy = deepcopy(_LEAVE_POLICIES[kind])
    policy.update(kind=kind, rule_version=RULE_VERSION, verified_on=VERIFIED_ON)
    policy["source_urls"] = [SOURCE_URLS[key] for key in policy.pop("sources")]
    return policy


def leave_types() -> list[str]:
    """Stable supported leave identifiers for clients."""
    return list(_LEAVE_POLICIES)
