import unittest
from job_pipeline.domain.models import (
    CandidateProfile,
    TargetPayBounds,
    JobPosting,
    FitEvaluation,
    EMPLOYMENT_ARRANGEMENTS,
    PAY_BASES,
    WORKER_CLASSIFICATIONS
)
from job_pipeline.domain.services import (
    PayCalculatorService,
    JobQualificationService,
)
from job_pipeline.adapters.secondary.mock_adapter import MockJobStorageAdapter


class TestContractRolesAndHourlyPay(unittest.TestCase):

    def setUp(self):
        self.profile = CandidateProfile(
            full_name="Matthew Hackett",
            title="Senior Operations Analyst",
            minimum_compensation_floor=90000.0,
            target_pay_floor=120000.0,
            target_pay_ceiling=150000.0,
            max_company_applications_limit=2,
            company_application_lookback_days=90,
            auto_exclude_overqualified_roles=True
        )

    def test_constants_defined(self):
        """Verify contract constants exist with expected choices."""
        self.assertEqual(EMPLOYMENT_ARRANGEMENTS, ["Employee", "Contract"])
        self.assertEqual(PAY_BASES, ["Annual", "Hourly"])
        self.assertEqual(WORKER_CLASSIFICATIONS, ["W2", "1099", "C2C"])

    def test_pay_calculator_hourly_rates_and_annualized(self):
        """Verify hourly pay bounds are calculated with 40h/week default assumption and annualized run-rate."""
        bounds = PayCalculatorService.calculate_target_pay(
            salary_min=60.0,
            salary_max=70.0,
            pay_basis="Hourly",
            expected_hours_per_week=None,
            contract_length_months=None
        )
        self.assertEqual(bounds.pay_basis, "Hourly")
        self.assertEqual(bounds.hourly_min, 60.0)
        self.assertEqual(bounds.hourly_max, 70.0)
        self.assertEqual(bounds.expected_hours_per_week, 40.0)
        self.assertTrue(bounds.expected_hours_per_week_is_assumed)
        # Annualized = rate * 40 * 52
        self.assertEqual(bounds.annualized_min, 60.0 * 40 * 52)  # 124,800
        self.assertEqual(bounds.annualized_max, 70.0 * 40 * 52)  # 145,600
        self.assertIn("$60 - $70/hr", bounds.display_range)
        self.assertIn("124,800 - $145,600 annualized", bounds.display_range)

    def test_pay_calculator_hourly_with_custom_hours(self):
        """Verify custom expected hours per week is used and not flagged as assumed."""
        bounds = PayCalculatorService.calculate_target_pay(
            salary_min=50.0,
            salary_max=60.0,
            pay_basis="Hourly",
            expected_hours_per_week=20.0,
            contract_length_months=None
        )
        self.assertEqual(bounds.expected_hours_per_week, 20.0)
        self.assertFalse(bounds.expected_hours_per_week_is_assumed)
        self.assertEqual(bounds.annualized_min, 50.0 * 20 * 52)  # 52,000
        self.assertEqual(bounds.annualized_max, 60.0 * 20 * 52)  # 62,400

    def test_pay_calculator_contract_value_estimation(self):
        """Verify estimated contract value calculation over contract length."""
        bounds = PayCalculatorService.calculate_target_pay(
            salary_min=60.0,
            salary_max=70.0,
            pay_basis="Hourly",
            expected_hours_per_week=40.0,
            contract_length_months=6.0
        )
        # 6 months = 25 weeks (50.0 / 12.0)
        # 60 * 40 * 25 = 60,000; 70 * 40 * 25 = 70,000
        self.assertEqual(bounds.contract_value_min, 60000.0)
        self.assertEqual(bounds.contract_value_max, 70000.0)
        self.assertTrue(bounds.contract_value_is_estimated)
        self.assertIn("60,000", bounds.contract_value_display)
        self.assertIn("70,000", bounds.contract_value_display)

    def test_pay_calculator_annual_salary_never_shows_hourly(self):
        """Verify salaried roles retain annual formatting and NEVER display an hourly conversion."""
        bounds = PayCalculatorService.calculate_target_pay(
            salary_min=120000.0,
            salary_max=135000.0,
            pay_basis="Annual"
        )
        self.assertEqual(bounds.pay_basis, "Annual")
        self.assertIsNone(bounds.hourly_min)
        self.assertIsNone(bounds.hourly_max)
        self.assertIsNone(bounds.contract_value_min)
        self.assertNotIn("/ hr", bounds.display_range)
        self.assertNotIn("/hr", bounds.display_range)
        self.assertIn("$", bounds.display_range)

    def test_job_qualification_hourly_floor_comparison(self):
        """Verify hourly roles compare annualized earnings against the candidate floor, avoiding false FLAGGED_LOW_PAY."""
        # $75/hr annualized = $156,000 (> floor of $90,000) -> should NOT be FLAGGED_LOW_PAY
        eval_good = JobQualificationService.evaluate(
            company_name="Braze",
            job_title="Senior Operations Analyst",
            raw_description="Contract Senior Ops Analyst",
            salary_min=75.0,
            salary_max=80.0,
            pay_basis="Hourly",
            profile=self.profile
        )
        self.assertNotEqual(eval_good.status, "FLAGGED_LOW_PAY")
        self.assertTrue(eval_good.is_qualified)

        # $25/hr annualized = $52,000 (< floor of $90,000) -> should be FLAGGED_LOW_PAY
        eval_low = JobQualificationService.evaluate(
            company_name="Acme",
            job_title="Junior Operations Clerk",
            raw_description="Contract Junior Ops Clerk",
            salary_min=25.0,
            salary_max=30.0,
            pay_basis="Hourly",
            profile=self.profile
        )
        self.assertEqual(eval_low.status, "FLAGGED_LOW_PAY")
        self.assertFalse(eval_low.is_qualified)

    def test_acceptance_criterion_1(self):
        """
        Acceptance Criterion 1:
        6-month contract, $60-$70/hr, extension possible:
        - Annualized run-rate: $124.8k - $145.6k
        - Contract value: $60.0k - $70.0k (25 weeks)
        - 40h assumed
        - extension_possible: True
        - worker_classification: None
        """
        fe = JobQualificationService.evaluate(
            company_name="Client Co",
            job_title="Revenue Operations Analyst",
            raw_description="6-month contract for RevOps Analyst at $60-$70/hr. Extension possible based on budget.",
            salary_min=60.0,
            salary_max=70.0,
            pay_basis="Hourly",
            contract_length_months=6.0,
            profile=self.profile
        )

        pb = fe.pay_bounds
        self.assertEqual(pb.pay_basis, "Hourly")
        self.assertEqual(pb.hourly_min, 60.0)
        self.assertEqual(pb.hourly_max, 70.0)
        self.assertEqual(pb.annualized_min, 124800.0)
        self.assertEqual(pb.annualized_max, 145600.0)
        self.assertEqual(pb.contract_value_min, 60000.0)
        self.assertEqual(pb.contract_value_max, 70000.0)
        self.assertEqual(pb.expected_hours_per_week, 40.0)
        self.assertTrue(pb.expected_hours_per_week_is_assumed)

        job = JobPosting(
            opportunity_id="ac1-test",
            company_name="Client Co",
            job_title="Revenue Operations Analyst",
            title_family="revenue_operations",
            raw_description="6-month contract $60-$70/hr",
            employment_arrangement="Contract",
            worker_classification=None,
            pay_basis="Hourly",
            contract_length_months=6.0,
            contract_length_raw="6-month contract",
            extension_possible=True,
            fte_conversion_possible=None
        )
        self.assertEqual(job.employment_arrangement, "Contract")
        self.assertIsNone(job.worker_classification)
        self.assertTrue(job.extension_possible)
        self.assertIsNone(job.fte_conversion_possible)

    def test_acceptance_criterion_2(self):
        """
        Acceptance Criterion 2:
        $120k-$135k full-time salaried role:
        - Retains annual display format
        - Does NOT show an hourly conversion
        """
        fe = JobQualificationService.evaluate(
            company_name="Contoso",
            job_title="Senior Operations Analyst",
            raw_description="Permanent full-time Senior Operations Analyst, salary $120,000 - $135,000.",
            salary_min=120000.0,
            salary_max=135000.0,
            pay_basis="Annual",
            profile=self.profile
        )
        pb = fe.pay_bounds
        self.assertEqual(pb.pay_basis, "Annual")
        self.assertIsNone(pb.hourly_min)
        self.assertIsNone(pb.hourly_max)
        self.assertIsNone(pb.contract_value_min)
        self.assertNotIn("/ hr", pb.display_range)
        self.assertNotIn("/hr", pb.display_range)

    def test_acceptance_criterion_3(self):
        """
        Acceptance Criterion 3:
        $75/hr W2 through Acme Staffing supporting Contoso, 12-month contract-to-hire:
        - Worker Classification: W2
        - Staffing Agency: Acme Staffing
        - Client Company: Contoso
        - Contract Duration: 12-month
        - FTE Conversion Possible: True
        """
        job = JobPosting(
            opportunity_id="ac3-test",
            company_name="Contoso",
            job_title="GTM Systems Architect",
            title_family="gtm_engineering",
            raw_description="$75/hr W2 through Acme Staffing supporting Contoso, 12-month contract-to-hire",
            employment_arrangement="Contract",
            worker_classification="W2",
            pay_basis="Hourly",
            contract_length_months=12.0,
            contract_length_raw="12-month",
            staffing_agency="Acme Staffing",
            client_company="Contoso",
            extension_possible=None,
            fte_conversion_possible=True
        )
        self.assertEqual(job.employment_arrangement, "Contract")
        self.assertEqual(job.worker_classification, "W2")
        self.assertEqual(job.staffing_agency, "Acme Staffing")
        self.assertEqual(job.client_company, "Contoso")
        self.assertEqual(job.contract_length_raw, "12-month")
        self.assertTrue(job.fte_conversion_possible)
        self.assertIsNone(job.extension_possible)

    def test_three_state_flags(self):
        """Verify extension_possible and fte_conversion_possible handle True, False, and None accurately."""
        # True state
        j_true = JobPosting(
            opportunity_id="j1", company_name="A", job_title="B", title_family="F", raw_description="",
            extension_possible=True, fte_conversion_possible=True
        )
        self.assertIs(j_true.extension_possible, True)
        self.assertIs(j_true.fte_conversion_possible, True)

        # False state
        j_false = JobPosting(
            opportunity_id="j2", company_name="A", job_title="B", title_family="F", raw_description="",
            extension_possible=False, fte_conversion_possible=False
        )
        self.assertIs(j_false.extension_possible, False)
        self.assertIs(j_false.fte_conversion_possible, False)

        # None state
        j_none = JobPosting(
            opportunity_id="j3", company_name="A", job_title="B", title_family="F", raw_description="",
            extension_possible=None, fte_conversion_possible=None
        )
        self.assertIsNone(j_none.extension_possible)
        self.assertIsNone(j_none.fte_conversion_possible)

    def test_mock_storage_contract_roundtrip(self):
        """Verify saving and updating contract fields in MockJobStorageAdapter."""
        storage = MockJobStorageAdapter()
        job = JobPosting(
            opportunity_id="mock-contract-1",
            company_name="Apex Staffing",
            job_title="SalesOps Contractor",
            title_family="revenue_operations",
            raw_description="Contract role",
            employment_arrangement="Contract",
            worker_classification="W2",
            pay_basis="Hourly",
            contract_length_raw="6 months",
            contract_value_display="$62,400 – $72,800",
            staffing_agency="Apex Systems",
            client_company="Braze",
            extension_possible=True,
            fte_conversion_possible=False
        )
        bounds = PayCalculatorService.calculate_target_pay(
            salary_min=60.0, salary_max=70.0, pay_basis="Hourly"
        )
        fit_eval = FitEvaluation(status="Processed", reasoning="Good match", is_qualified=True, pay_bounds=bounds)

        # Save
        saved = storage.save_opportunity(job, fit_eval)
        self.assertTrue(saved)

        # Fetch
        opps = storage.fetch_all_opportunities()
        self.assertEqual(len(opps), 1)
        o = opps[0]
        self.assertEqual(o["Employment Arrangement"], "Contract")
        self.assertEqual(o["Worker Classification"], "W2")
        self.assertEqual(o["Contract Duration"], "6 months")
        self.assertEqual(o["Contract Value"], "$62,400 – $72,800")
        self.assertEqual(o["Staffing Agency"], "Apex Systems")
        self.assertEqual(o["Client Company"], "Braze")
        self.assertEqual(o["Extension Possible"], "Yes")
        self.assertEqual(o["FTE Conversion"], "No")

        # Update
        updated = storage.update_opportunity_status(
            opportunity_id="mock-contract-1",
            status="Interview Screen",
            employment_arrangement="Contract",
            worker_classification="1099",
            contract_length_raw="9 months",
            contract_value_display="$93,600 – $109,200",
            staffing_agency="Insight Global",
            client_company="Braze Enterprise",
            extension_possible=True,
            fte_conversion_possible=True
        )
        self.assertTrue(updated)

        updated_opps = storage.fetch_all_opportunities()
        u = updated_opps[0]
        self.assertEqual(u["Worker Classification"], "1099")
        self.assertEqual(u["Contract Duration"], "9 months")
        self.assertEqual(u["Contract Value"], "$93,600 – $109,200")
        self.assertEqual(u["Staffing Agency"], "Insight Global")
        self.assertEqual(u["Client Company"], "Braze Enterprise")
        self.assertEqual(u["Extension Possible"], "Yes")
        self.assertEqual(u["FTE Conversion"], "Yes")


if __name__ == "__main__":
    unittest.main()
