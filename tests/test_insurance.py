import json
import unittest
from decimal import Decimal, localcontext

from attendance.insurance import estimate_insurance


class InsuranceTests(unittest.TestCase):
    def test_minimum_wage_employee_and_employer_costs_are_separate(self):
        result = estimate_insurance(29500)
        self.assertEqual(result["bases"], dict.fromkeys(("labor_insurance", "employment_insurance", "occupational_insurance", "nhi", "pension"), 29500))
        self.assertEqual(result["employee"], {"labor_insurance": 679, "employment_insurance": 59, "occupational_insurance": 0, "nhi": 458, "pension": 0, "total": 1196})
        self.assertEqual(result["employer"], {"labor_insurance": 2375, "employment_insurance": 207, "occupational_insurance": 59, "nhi": 1428, "pension": 1770, "total": 5839})
        self.assertEqual(result["government"]["total"], 607)

    def test_first_bracket_exact_boundary_and_next_dollar(self):
        self.assertEqual(estimate_insurance(30300)["bases"]["labor_insurance"], 30300)
        self.assertEqual(estimate_insurance(30301)["bases"]["labor_insurance"], 31800)
        self.assertEqual(estimate_insurance(29501)["bases"]["nhi"], 30300)

    def test_labor_cap_does_not_cap_other_schemes(self):
        result = estimate_insurance(45801)
        self.assertEqual(result["bases"]["labor_insurance"], 45800)
        self.assertEqual(result["bases"]["employment_insurance"], 45800)
        self.assertEqual(result["bases"]["occupational_insurance"], 48200)
        self.assertEqual(result["bases"]["pension"], 48200)
        self.assertEqual(result["employee"]["labor_insurance"], 1053)
        self.assertEqual(result["employee"]["employment_insurance"], 92)

    def test_occupational_cap_does_not_cap_pension_or_health(self):
        result = estimate_insurance(72801)
        self.assertEqual(result["bases"]["occupational_insurance"], 72800)
        self.assertEqual(result["bases"]["nhi"], 76500)
        self.assertEqual(result["bases"]["pension"], 76500)

    def test_high_salary_uses_distinct_caps(self):
        result = estimate_insurance(500000)
        self.assertEqual(result["bases"], {"labor_insurance": 45800, "employment_insurance": 45800, "occupational_insurance": 72800, "nhi": 313000, "pension": 150000})
        self.assertEqual(result["employee"]["nhi"], 4855)
        self.assertEqual(result["employer"]["nhi"], 15146)
        self.assertEqual(result["government"]["nhi"], 2524)
        self.assertEqual(result["employer"]["pension"], 9000)

    def test_irregular_upper_health_brackets_are_not_linear(self):
        for salary, expected in ((147900, 147900), (147901, 150000), (150001, 156400), (219501, 228200), (263001, 273000), (303001, 313000)):
            with self.subTest(salary=salary):
                self.assertEqual(estimate_insurance(salary)["bases"]["nhi"], expected)

    def test_nhi_rounds_each_person_before_family_multiplier(self):
        # Official NHI row at 29,500: 458 / 916 / 1,374 / 1,832.
        for dependents, expected in enumerate((458, 916, 1374, 1832)):
            self.assertEqual(estimate_insurance(29500, dependents)["employee"]["nhi"], expected)

    def test_dependents_capped_and_employer_average_independent(self):
        without = estimate_insurance(29500, 0)
        many = estimate_insurance(29500, 8)
        self.assertEqual(many["employee"]["nhi"], 1832)
        self.assertEqual(many["dependents"]["charged"], 3)
        self.assertEqual(many["employer"], without["employer"])
        self.assertEqual(many["government"], without["government"])

    def test_custom_rates_are_employer_cost_only(self):
        result = estimate_insurance(50000, occupational_rate=Decimal("0.003"), pension_rate=Decimal("0.08"))
        self.assertEqual(result["employer"]["occupational_insurance"], 152)
        self.assertEqual(result["employer"]["pension"], 4048)
        self.assertEqual(result["employee"]["occupational_insurance"], 0)
        self.assertEqual(result["employee"]["pension"], 0)

    def test_unsupported_years_do_not_reuse_rates(self):
        for value in ("2025-12-31", "2027-01-01", "2026-02-29", "20260101", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                estimate_insurance(40000, as_of=value)
        self.assertEqual(estimate_insurance(40000, as_of="2026-12-31")["as_of"], "2026-12-31")

    def test_invalid_salary_and_out_of_scope_salary_rejected(self):
        for salary in (0, -1, 29499, 30300.5, True, None, "NaN", float("inf"), "no"):
            with self.subTest(salary=salary), self.assertRaises(ValueError):
                estimate_insurance(salary)

    def test_invalid_dependents_rejected(self):
        for value in (-1, 1.5, True, "2", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                estimate_insurance(40000, value)

    def test_invalid_and_below_minimum_rates_rejected(self):
        for field, value in (("occupational_rate", 0), ("occupational_rate", -0.1), ("occupational_rate", 2), ("pension_rate", 0.059), ("pension_rate", 6), ("pension_rate", True), ("occupational_rate", "NaN")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                estimate_insurance(40000, **{field: value})

    def test_json_safe_and_context_independent(self):
        expected = estimate_insurance(29500)
        with localcontext() as context:
            context.prec = 4
            actual = estimate_insurance(Decimal("29500"))
        self.assertEqual(actual, expected)
        encoded = json.loads(json.dumps(actual))
        self.assertTrue(encoded["estimate_only"])
        self.assertTrue(encoded["sources"])
        self.assertTrue(encoded["warnings"])


if __name__ == "__main__":
    unittest.main()
