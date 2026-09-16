import json
import unittest
from datetime import date

from attendance.calendar_tw import DATA_PATH, calendar_month


class TaiwanCalendarTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def day(month, number, **kwargs):
        return calendar_month(2026, month, **kwargs)["days"][number - 1]

    def test_all_365_dates_are_present_once_and_government_has_120_off_days(self):
        days = [day for month in range(1, 13) for day in calendar_month(2026, month)["days"]]
        self.assertEqual(len(days), 365)
        self.assertEqual(len({entry["date"] for entry in days}), 365)
        self.assertEqual(sum(day["government_is_holiday"] for day in days), 120)
        self.assertEqual(sum(day["is_holiday"] for day in days), 114)

    def test_new_holidays_and_labor_day_are_present(self):
        self.assertEqual(len(self.data["statutory_holidays"]), 16)
        for month, number in ((5, 1), (9, 28), (12, 25)):
            self.assertEqual(self.day(month, number)["kind"], "national_holiday")
        self.assertEqual(self.day(2, 15)["statutory_holiday"], "小年夜")
        self.assertIsNotNone(self.day(10, 25)["statutory_holiday"])

    def test_weekends_preserve_labor_day_type_when_holiday_coincides(self):
        self.assertEqual(self.day(2, 28)["kind"], "rest_day")
        self.assertEqual(self.day(2, 15)["kind"], "regular_day_off")
        self.assertEqual(self.day(4, 4)["kind"], "rest_day")
        self.assertEqual(self.day(4, 5)["kind"], "regular_day_off")

    def test_government_substitutions_are_not_automatically_applied(self):
        for entry in self.data["government_calendar"]["substitutions"]:
            current = date.fromisoformat(entry["date"])
            day = self.day(current.month, current.day)
            self.assertEqual(day["kind"], "weekday")
            self.assertFalse(day["is_holiday"])
            self.assertTrue(day["government_is_holiday"])
            self.assertTrue(day["requires_agreement"])
            self.assertEqual(day["proposed_substitute_for"], entry["substitute_for"])
        self.assertEqual(calendar_month(2026, 1)["pending_substitution_count_year"], 6)

    def test_spring_festival_skips_all_intervening_holidays(self):
        proposals = calendar_month(2026, 2)["proposed_substitutions"]
        found = {entry["substitute_for"]: entry["date"] for entry in proposals}
        self.assertEqual(found["2026-02-15"], "2026-02-20")
        self.assertEqual(found["2026-02-28"], "2026-02-27")

    def test_two_april_holidays_each_receive_distinct_substitute(self):
        proposals = calendar_month(2026, 4)["proposed_substitutions"]
        self.assertEqual({entry["date"] for entry in proposals}, {"2026-04-03", "2026-04-06"})

    def test_explicit_agreement_can_choose_different_workday(self):
        agreements = {"2026-02-15": "2026-02-23"}
        day = self.day(2, 23, agreed_substitutions=agreements)
        self.assertEqual(day["kind"], "national_holiday")
        self.assertEqual(day["substitute_for"], "2026-02-15")
        self.assertFalse(day["requires_agreement"])
        self.assertEqual(self.day(2, 20, agreed_substitutions=agreements)["kind"], "weekday")
        self.assertIsNone(self.day(2, 20, agreed_substitutions=agreements)["proposed_substitute_for"])

    def test_all_agreed_proposals_have_16_national_holidays_and_120_days_off(self):
        agreements = {entry["substitute_for"]: entry["date"] for entry in self.data["government_calendar"]["substitutions"]}
        days = [day for month in range(1, 13) for day in calendar_month(2026, month, agreed_substitutions=agreements)["days"]]
        self.assertEqual(sum(day["kind"] == "national_holiday" for day in days), 16)
        self.assertEqual(sum(day["is_holiday"] for day in days), 120)

    def test_pending_proposal_skips_a_different_holidays_agreed_substitute(self):
        result = calendar_month(2026, 2, agreed_substitutions={"2026-02-28": "2026-02-20"})
        self.assertEqual(result["proposed_substitutions"][0]["date"], "2026-02-23")
        self.assertEqual(result["proposed_substitutions"][0]["substitute_for"], "2026-02-15")

    def test_invalid_duplicate_nonworking_and_out_of_year_agreements_rejected(self):
        bad_agreements = [
            {"2026-02-15": "2026-02-16"},
            {"2026-02-15": "2026-02-21"},
            {"2026-02-15": "2027-01-04"},
            {"2026-01-01": "2026-01-02"},
            {"2026-02-15": "2026-02-20", "2026-02-28": "2026-02-20"},
            {"2026-02-15": "20260220"},
            {"2026-02-15": None},
            [],
        ]
        for agreements in bad_agreements:
            with self.subTest(agreements=agreements), self.assertRaises(ValueError):
                calendar_month(2026, 2, agreed_substitutions=agreements)

    def test_unknown_year_or_invalid_month_fails_closed(self):
        for year, month in ((2025, 1), (2027, 1), (2026, 0), (2026, 13), (2026, True), (2026.0, 1)):
            with self.subTest(year=year, month=month), self.assertRaises(ValueError):
                calendar_month(year, month)

    def test_metadata_and_daily_contract(self):
        result = calendar_month(2026, 9)
        self.assertEqual(result["timezone"], "Asia/Taipei")
        self.assertEqual(result["verified_at"], "2026-09-16")
        self.assertTrue(result["warnings"])
        for entry in result["days"]:
            self.assertTrue({"date", "name", "kind", "is_holiday", "source"}.issubset(entry))
            self.assertIn(entry["kind"], {"weekday", "rest_day", "regular_day_off", "national_holiday"})


if __name__ == "__main__":
    unittest.main()
