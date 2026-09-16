import json
import unittest
from decimal import Decimal

from attendance.labor import (
    RULE_VERSION, annual_leave_days, leave_policy, leave_types, overtime_pay,
    validate_hours,
)


class AnnualLeaveTests(unittest.TestCase):
    def test_half_year_boundary_is_calendar_months(self):
        self.assertEqual(annual_leave_days("2026-03-16", "2026-09-15"), 0)
        self.assertEqual(annual_leave_days("2026-03-16", "2026-09-16"), 3)

    def test_all_statutory_tiers_on_anniversaries(self):
        for years, expected in [(1, 7), (2, 10), (3, 14), (4, 14), (5, 15),
                                (9, 15), (10, 16), (11, 17), (23, 29), (24, 30), (30, 30)]:
            with self.subTest(years=years):
                self.assertEqual(annual_leave_days("1990-09-16", f"{1990 + years}-09-16"), expected)

    def test_not_cumulative_and_not_365_day_approximation(self):
        self.assertEqual(annual_leave_days("2023-03-01", "2024-02-29"), 3)
        self.assertEqual(annual_leave_days("2023-03-01", "2024-03-01"), 7)

    def test_project_favourable_month_end_fallback(self):
        self.assertEqual(annual_leave_days("2024-02-29", "2025-02-27"), 3)
        self.assertEqual(annual_leave_days("2024-02-29", "2025-02-28"), 7)
        self.assertEqual(annual_leave_days("2024-02-29", "2028-02-28"), 14)
        self.assertEqual(annual_leave_days("2025-08-31", "2026-02-27"), 0)
        self.assertEqual(annual_leave_days("2025-08-31", "2026-02-28"), 3)

    def test_strict_date_validation(self):
        for hire, current in [("2026-02-30", "2026-09-16"), ("20260916", "2026-09-16"),
                              ("2026-09-16", "2026-09-15"), (None, "2026-09-16")]:
            with self.subTest(hire=hire, current=current), self.assertRaises(ValueError):
                annual_leave_days(hire, current)


class OvertimeTests(unittest.TestCase):
    def test_weekday_tiers(self):
        for minutes, pay in [(0, "0.00"), (60, "200.00"), (120, "400.00"),
                             (180, "650.00"), (240, "900.00")]:
            with self.subTest(minutes=minutes):
                self.assertEqual(overtime_pay(150, minutes, "weekday")["pay"], pay)

    def test_rest_day_tiers(self):
        for minutes, pay in [(0, "0.00"), (120, "400.00"), (480, "1900.00"),
                             (540, "2300.00"), (720, "3500.00")]:
            with self.subTest(minutes=minutes):
                self.assertEqual(overtime_pay("150", minutes, "rest_day")["pay"], pay)
        self.assertEqual(overtime_pay(150, 720, "rest_day")["breakdown"][-1]["multiplier"], "8/3")

    def test_national_holiday_is_additional_full_day_then_overtime(self):
        for minutes, pay in [(0, "0.00"), (1, "1200.00"), (240, "1200.00"),
                             (480, "1200.00"), (600, "1600.00"), (720, "2100.00")]:
            with self.subTest(minutes=minutes):
                self.assertEqual(overtime_pay(150, minutes, "national_holiday")["pay"], pay)

    def test_exact_fraction_and_documented_rounding(self):
        self.assertEqual(overtime_pay(100, 1, "weekday")["pay"], "2.23")
        result = overtime_pay("123.45", 180, "weekday")
        self.assertEqual(result["pay"], "534.95")
        self.assertEqual(sum(Decimal(item["pay"]) for item in result["breakdown"]), Decimal(result["pay"]))
        self.assertEqual(result["breakdown"][0]["multiplier"], "4/3")

    def test_forbidden_and_unsupported_work_not_priced_as_normal(self):
        for minutes, day in [(0, "regular_day_off"), (480, "regular_day_off"),
                             (241, "weekday"), (721, "rest_day"),
                             (721, "national_holiday"), (60, "sunday")]:
            with self.subTest(minutes=minutes, day=day), self.assertRaises(ValueError):
                overtime_pay(150, minutes, day)

    def test_invalid_wages_and_minutes(self):
        for wage in [0, -1, True, None, "NaN", "Infinity", "wat", 10**20, "0.0000000000001"]:
            with self.subTest(wage=wage), self.assertRaises(ValueError):
                overtime_pay(wage, 60, "weekday")
        for minutes in [-1, 0.5, True, "60", None]:
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                overtime_pay(150, minutes, "weekday")

    def test_traceability_and_json_serialization(self):
        result = overtime_pay(Decimal("150.25"), 120, "weekday")
        self.assertEqual(result["rule_version"], RULE_VERSION)
        self.assertEqual(result["pay_basis"], "additional_to_monthly_base")
        self.assertTrue(result["warnings"])
        self.assertTrue(result["source_urls"])
        json.dumps(result)


class HoursTests(unittest.TestCase):
    def test_standard_boundaries(self):
        self.assertEqual(validate_hours(480, 2400, 2760), [])

    def test_daily_overtime_and_total_limit_are_different(self):
        self.assertIn("超過8小時", validate_hours(481, 2400, 2760)[0])
        self.assertNotIn("超過12小時", validate_hours(720, 2400, 2760)[0])
        self.assertIn("超過12小時", validate_hours(721, 2400, 2760)[0])

    def test_weekly_is_normal_hours_monthly_is_overtime(self):
        warnings = validate_hours(480, 2401, 2761)
        self.assertEqual(len(warnings), 2)
        self.assertIn("正常工時", warnings[0])
        self.assertIn("46小時", warnings[1])

    def test_invalid_hours_rejected(self):
        for values in [(-1, 0, 0), (0, True, 0), (0, 0, 1.5)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_hours(*values)


class LeavePolicyTests(unittest.TestCase):
    def test_2026_sick_protections(self):
        result = leave_policy("sick")
        self.assertEqual(result["annual_days"], 30)
        self.assertEqual(result["protected_days_per_year"], 10)
        self.assertEqual(result["paid_ratio"], "0.5")
        self.assertEqual(result["attendance_bonus_rule"], "proportional_deduction_only")

    def test_family_care_shares_personal_budget(self):
        family = leave_policy("family_care")
        self.assertEqual(family["annual_days"], 7)
        self.assertEqual(family["standard_annual_hours"], 56)
        self.assertEqual(family["counts_toward"], "personal")
        self.assertEqual(leave_policy("personal")["annual_days"], 14)
        self.assertTrue(leave_policy("family_care_personal")["attendance_bonus_protected"])

    def test_event_leave_is_not_annual_entitlement(self):
        for kind in ["marriage", "bereavement", "maternity", "prenatal", "paternity"]:
            self.assertIsNone(leave_policy(kind)["annual_days"])
        self.assertEqual(leave_policy("paternity")["days_per_event"], 7)
        self.assertIsNone(leave_policy("maternity")["paid_ratio"])

    def test_menstrual_monthly_and_sick_pool_rules(self):
        policy = leave_policy("menstrual")
        self.assertEqual(policy["days_per_month"], 1)
        self.assertEqual(policy["counts_toward_sick_after_days"], 3)
        self.assertTrue(policy["attendance_bonus_protected"])

    def test_returned_policy_is_not_shared_mutable_state(self):
        result = leave_policy("sick")
        result["notes"].clear()
        self.assertTrue(leave_policy("sick")["notes"])

    def test_all_policies_are_json_and_sourced(self):
        for kind in leave_types():
            policy = leave_policy(kind)
            self.assertEqual(policy["kind"], kind)
            self.assertEqual(policy["verified_on"], "2026-09-16")
            self.assertTrue(policy["source_urls"])
            json.dumps(policy)
        with self.assertRaises(ValueError):
            leave_policy("unknown")


if __name__ == "__main__":
    unittest.main()
