"""2026 Taiwan insurance estimates for ordinary full-time employees.

Rates are fractions (0.06 means 6%). Money is computed with Decimal and
returned as integer TWD. This is a full-month estimate, not a filing engine.
See docs/insurance-rules.md for the supported population and official sources.
"""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext


RULES_VERSION = "TW-INSURANCE-2026-v1"
CHECKED_ON = "2026-09-16"
VALID_FROM = "2026-01-01"
VALID_THROUGH = "2026-12-31"
MINIMUM_MONTHLY_WAGE = 29_500

# Explicit official brackets: never interpolate between missing rows.
# Ordinary full-time labor / employment insurance, BLI Files/25661.
LABOR_BRACKETS = (
    29500, 30300, 31800, 33300, 34800, 36300, 38200, 40100,
    42000, 43900, 45800,
)
# Occupational insurance, BLI Files/25664 (21 ordinary brackets).
OCCUPATIONAL_BRACKETS = (
    29500, 30300, 31800, 33300, 34800, 36300, 38200, 40100,
    42000, 43900, 45800, 48200, 50600, 53000, 55400, 57800,
    60800, 63800, 66800, 69800, 72800,
)
# Full 2026 NHI table for employed persons (58 brackets).
NHI_BRACKETS = (
    29500, 30300, 31800, 33300, 34800, 36300, 38200, 40100,
    42000, 43900, 45800, 48200, 50600, 53000, 55400, 57800,
    60800, 63800, 66800, 69800, 72800, 76500, 80200, 83900,
    87600, 92100, 96600, 101100, 105600, 110100, 115500,
    120900, 126300, 131700, 137100, 142500, 147900, 150000,
    156400, 162800, 169200, 175600, 182000, 189500, 197000,
    204500, 212000, 219500, 228200, 236900, 245600, 254300,
    263000, 273000, 283000, 293000, 303000, 313000,
)
# BLI Files/25709, rows 25-62: all brackets within this full-time scope.
# Lower rows belong to other populations / wage situations, not this API.
PENSION_BRACKETS = (
    29500, 30300, 31800, 33300, 34800, 36300, 38200, 40100,
    42000, 43900, 45800, 48200, 50600, 53000, 55400, 57800,
    60800, 63800, 66800, 69800, 72800, 76500, 80200, 83900,
    87600, 92100, 96600, 101100, 105600, 110100, 115500,
    120900, 126300, 131700, 137100, 142500, 147900, 150000,
)

SOURCES = (
    ("2026 勞工保險投保薪資分級表", "https://www.bli.gov.tw/Files/25661"),
    ("2026 職災保險投保薪資分級表", "https://www.bli.gov.tw/Files/25664"),
    ("2026 勞退月提繳分級表", "https://www.bli.gov.tw/Files/25709"),
    ("勞保費率及負擔比例", "https://www.bli.gov.tw/0005478.html"),
    ("就保月投保薪資及保險費", "https://www.bli.gov.tw/0006443.html"),
    ("各險保費負擔比例", "https://www.bli.gov.tw/Files/11372"),
    ("2026 健保受僱者保費表", "https://www.nhi.gov.tw/ch/cp-19418-9eefb-2576-1.html"),
    ("勞退條例第14條", "https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=N0030020&flno=14"),
    ("勞保局保費試算及適用說明", "https://www.bli.gov.tw/0014162.html"),
)

SCOPE = (
    "僅供 2026 年一般本國全時受僱者，全月已參加勞保、就保、職災保險、"
    "第一類受僱者健保及勞退新制的費用預估；未進行投保資格審核。"
)


def _number(value, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f"{name} 必須為有限數值")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} 必須為有限數值") from None
    if not number.is_finite():
        raise ValueError(f"{name} 必須為有限數值")
    return number


def _base(salary: Decimal, brackets: tuple[int, ...]) -> int:
    return next((amount for amount in brackets if salary <= amount), brackets[-1])


def _twd(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def estimate_insurance(
    monthly_salary: int | float | Decimal,
    dependents: int = 0,
    occupational_rate: int | float | Decimal = 0.002,
    pension_rate: int | float | Decimal = 0.06,
    as_of: str = "2026-09-16",
) -> dict:
    """Estimate one full month for the population described by ``SCOPE``.

    ``monthly_salary`` is an integer-TWD declarable monthly wage total, not
    take-home pay. ``dependents`` counts NHI dependents under this employee.
    ``occupational_rate`` is the employer's approved total occupational rate,
    including commuting coverage and any experience adjustment. The default
    0.2% is only a demonstration assumption. ``pension_rate`` is the employer
    contribution, never an employee payroll deduction.

    The caller must verify eligibility; contractors, employer-owners,
    part-time staff, retirees outside employment insurance, foreign workers,
    other NHI categories and partial-month calculations are outside scope.
    Invalid parameters or any date outside 2026 raise ValueError.
    """
    try:
        effective_date = date.fromisoformat(as_of)
    except (TypeError, ValueError):
        raise ValueError("as_of 必須為 YYYY-MM-DD 日期") from None
    if as_of != effective_date.isoformat():
        raise ValueError("as_of 必須為 YYYY-MM-DD 日期")
    if effective_date.year != 2026:
        raise ValueError("本版僅支援 2026 年保費規則，其他年度須另行更新官方表格")

    salary = _number(monthly_salary, "monthly_salary")
    if salary < MINIMUM_MONTHLY_WAGE:
        raise ValueError("僅支援一般全時全月薪資，2026 年月薪不得低於 29,500 元")
    if salary != salary.to_integral_value():
        raise ValueError("monthly_salary 請輸入已確認可申報的整數新臺幣元")
    if type(dependents) is not int or dependents < 0:
        raise ValueError("dependents 必須為非負整數")
    occupational = _number(occupational_rate, "occupational_rate")
    pension = _number(pension_rate, "pension_rate")
    if not Decimal("0") < occupational <= Decimal("1"):
        raise ValueError("occupational_rate 須為大於 0 且不超過 1 的費率比例，例如 0.002")
    if not Decimal("0.06") <= pension <= Decimal("1"):
        raise ValueError("雇主 pension_rate 不得低於 0.06，且須使用不超過 1 的費率比例")

    bases = {
        "labor_insurance": _base(salary, LABOR_BRACKETS),
        "employment_insurance": _base(salary, LABOR_BRACKETS),
        "occupational_insurance": _base(salary, OCCUPATIONAL_BRACKETS),
        "nhi": _base(salary, NHI_BRACKETS),
        "pension": _base(salary, PENSION_BRACKETS),
    }
    charged_dependents = min(dependents, 3)
    shares = {party: dict.fromkeys(bases, 0) for party in ("employee", "employer", "government")}
    # Isolate calculations from the application's Decimal context.
    with localcontext() as context:
        context.prec = max(28, len(occupational.as_tuple().digits) + 16, len(pension.as_tuple().digits) + 16)
        for item, rate in (("labor_insurance", Decimal("0.115")), ("employment_insurance", Decimal("0.01"))):
            for party, fraction in (("employee", "0.2"), ("employer", "0.7"), ("government", "0.1")):
                shares[party][item] = _twd(Decimal(bases[item]) * rate * Decimal(fraction))
        nhi_full = Decimal(bases["nhi"]) * Decimal("0.0517")
        # NHI rounds the per-person employee premium BEFORE multiplying by
        # persons. At 29,500 with three dependents this is 458 * 4 = 1,832.
        shares["employee"]["nhi"] = _twd(nhi_full * Decimal("0.3")) * (1 + charged_dependents)
        # Employer and government use the published average-dependent factor,
        # not this employee's actual dependents.
        shares["employer"]["nhi"] = _twd(nhi_full * Decimal("0.6") * Decimal("1.56"))
        shares["government"]["nhi"] = _twd(nhi_full * Decimal("0.1") * Decimal("1.56"))
        shares["employer"]["occupational_insurance"] = _twd(Decimal(bases["occupational_insurance"]) * occupational)
        shares["employer"]["pension"] = _twd(Decimal(bases["pension"]) * pension)
    for amounts in shares.values():
        amounts["total"] = sum(amounts.values())

    warnings = [
        SCOPE,
        "職災費率須填公司核定的總費率（含上下班及實績調整）；預設 0.2% 為範例，並非統一法定費率。",
        "各制度以輸入工資查表預估；實際已申報級距、生效日、加退保及補退收可能不同，請與官方帳單核對。",
        "未納入健保補充保費、個人保費補助、勞退自提、工資墊償基金、所得稅及其他薪資扣款。",
        "雇主勞退提繳全由雇主負擔；員工 pension=0 表示本試算未納入自提，不代表可免除雇主提繳。",
    ]
    if dependents > 3:
        warnings.append("健保眷屬超過 3 人，本試算僅以 3 人計費；實際補助眷屬順序未納入。")
    return {
        "as_of": as_of,
        "rules_version": RULES_VERSION,
        "checked_on": CHECKED_ON,
        "valid_from": VALID_FROM,
        "valid_through": VALID_THROUGH,
        "currency": "TWD",
        "estimate_only": True,
        "scope": SCOPE,
        "bases": bases,
        **shares,
        "dependents": {"reported": dependents, "charged": charged_dependents, "max_charged": 3},
        "rates": {
            "labor_insurance": "0.115", "employment_insurance": "0.01",
            "occupational_insurance": str(occupational), "nhi": "0.0517",
            "pension": str(pension), "nhi_average_dependents": "0.56",
        },
        "warnings": warnings,
        "sources": [{"title": title, "url": url, "checked_on": CHECKED_ON} for title, url in SOURCES],
    }
