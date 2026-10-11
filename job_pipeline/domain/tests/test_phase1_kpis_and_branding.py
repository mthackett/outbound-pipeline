import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from job_pipeline import __version__ as APP_VERSION
from job_pipeline.domain.models import (
    PipelineInstanceConfig,
    AUTHORITATIVE_PIPELINE_STAGES,
    ACTIVE_OPPORTUNITY_STAGES,
    POSITIVE_INTEREST_STAGES,
    KPI_INTERVIEW_STAGES,
    TERMINAL_STAGES,
    SUBMITTED_STAGES,
    INTERVIEW_STAGES
)
from job_pipeline.domain.services import (
    PipelineConfigService,
    PipelineKPIService,
    PipelineSearchPaginationService
)


class TestPhase1BrandingAndInstanceConfig(unittest.TestCase):
    """Test suite for Phase 1 typed instance configuration and branding."""

    def test_version_constant(self):
        self.assertEqual(APP_VERSION, "1.4")

    def test_instance_config_defaults(self):
        cfg = PipelineInstanceConfig()
        self.assertEqual(cfg.instance_id, "job-applications")
        self.assertEqual(cfg.pipeline_type, "job_applications")
        self.assertEqual(cfg.display_name, "Job Application Pipeline")
        self.assertEqual(cfg.page_title, "More Outbound: Job Application Pipeline")
        self.assertIn("Automated Job Fit Screening", cfg.page_subtitle)
        self.assertEqual(cfg.page_icon, "🚀")
        self.assertIsNone(cfg.logo_path)
        self.assertIsNone(cfg.favicon_path)
        self.assertEqual(cfg.stale_threshold_days, 28)

    def test_custom_instance_config_via_service(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "custom_config.json"
            custom_data = {
                "instance_config": {
                    "instance_id": "b2b-outbound",
                    "pipeline_type": "b2b_sales",
                    "display_name": "B2B Sales Pipeline",
                    "page_title": "More Outbound: B2B Sales Pipeline",
                    "page_subtitle": "Lead Discovery & Outreach Intelligence",
                    "page_icon": "💼",
                    "logo_path": "assets/custom_logo.png",
                    "stale_threshold_days": 21
                }
            }
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(custom_data, f)

            loaded = PipelineConfigService.get_instance_config(str(cfg_path))
            self.assertEqual(loaded.instance_id, "b2b-outbound")
            self.assertEqual(loaded.pipeline_type, "b2b_sales")
            self.assertEqual(loaded.display_name, "B2B Sales Pipeline")
            self.assertEqual(loaded.page_title, "More Outbound: B2B Sales Pipeline")
            self.assertEqual(loaded.logo_path, "assets/custom_logo.png")
            self.assertEqual(loaded.stale_threshold_days, 21)

    def test_fallback_when_instance_config_missing_or_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "empty_config.json"
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({"sources": ["LinkedIn"]}, f)

            loaded = PipelineConfigService.get_instance_config(str(cfg_path))
            self.assertEqual(loaded.instance_id, "job-applications")
            self.assertEqual(loaded.display_name, "Job Application Pipeline")
            self.assertEqual(loaded.stale_threshold_days, 28)


class TestPhase1PipelineKPIs(unittest.TestCase):
    """Test suite for Phase 1 KPI calculations, active allowlist, and submission logic."""

    def test_authoritative_pipeline_stages_list(self):
        expected_stages = [
            "Pending", "Processed", "Applied", "Declined to Apply", "Employer Interest",
            "Application Rejected", "Recruiter Screen", "Hiring Manager",
            "Technical Screen", "Final Round", "Offer", "Withdrawn",
            "Archived", "Rejected"
        ]
        self.assertEqual(AUTHORITATIVE_PIPELINE_STAGES, expected_stages)

    def test_active_opportunities_explicit_allowlist(self):
        # Explicit allowlist: Employer Interest, Recruiter Screen, Hiring Manager, Technical Screen, Final Round, Offer
        expected_allowlist = {
            "Employer Interest", "Recruiter Screen", "Hiring Manager",
            "Technical Screen", "Final Round", "Offer"
        }
        self.assertEqual(ACTIVE_OPPORTUNITY_STAGES, expected_allowlist)

        for stage in expected_allowlist:
            opp = {"Status": stage}
            self.assertTrue(
                PipelineKPIService.is_active(opp),
                f"Stage '{stage}' must be recognized as Active Opportunity"
            )

        # Confirm that Applied and other stages are NOT in Active Opportunities
        non_active = [
            "Applied", "Pending", "Processed", "Declined to Apply",
            "Application Rejected", "Rejected", "Withdrawn", "Archived"
        ]
        for stage in non_active:
            opp = {"Status": stage}
            self.assertFalse(
                PipelineKPIService.is_active(opp),
                f"Stage '{stage}' must NOT be counted in Active Opportunities"
            )

    def test_applied_submission_detection(self):
        # 1. Non-submitted stages
        self.assertFalse(PipelineKPIService.is_submitted({"Status": "Declined to Apply"}))
        self.assertFalse(PipelineKPIService.is_submitted({"Status": "Processed"}))
        self.assertFalse(PipelineKPIService.is_submitted({"Status": "Pending"}))

        # 2. Submitted stages (current status)
        self.assertTrue(PipelineKPIService.is_submitted({"Status": "Applied"}))
        self.assertTrue(PipelineKPIService.is_submitted({"Status": "Recruiter Screen"}))
        self.assertTrue(PipelineKPIService.is_submitted({"Status": "Employer Interest"}))
        self.assertTrue(PipelineKPIService.is_submitted({"Status": "Application Rejected"}))

        # 3. Progressed/Rejected/Withdrawn with stage history proving submission
        self.assertTrue(PipelineKPIService.is_submitted({
            "Status": "Rejected",
            "stage_history": [{"stage": "Applied"}, {"stage": "Rejected"}]
        }))
        self.assertTrue(PipelineKPIService.is_submitted({
            "Status": "Withdrawn",
            "stage_history": [{"stage": "Processed"}, {"stage": "Applied"}, {"stage": "Withdrawn"}]
        }))

        # 4. Rejected/Withdrawn without submission history
        self.assertFalse(PipelineKPIService.is_submitted({
            "Status": "Rejected",
            "stage_history": [{"stage": "Processed"}, {"stage": "Rejected"}]
        }))
        self.assertFalse(PipelineKPIService.is_submitted({
            "Status": "Withdrawn",
            "stage_history": []
        }))

    def test_applications_per_interview_calculation(self):
        # 50 submitted applications: 48 at Applied, 2 at interview stages
        opps = []
        for i in range(48):
            opps.append({
                "Opportunity ID": f"opp-{i}",
                "Status": "Applied",
                "Selected Resume": "Candidate RevOps Analyst Resume"
            })
        opps.append({
            "Opportunity ID": "opp-int-1",
            "Status": "Recruiter Screen",
            "Selected Resume": "Candidate RevOps Analyst Resume",
            "stage_history": [{"stage": "Applied"}, {"stage": "Recruiter Screen"}]
        })
        opps.append({
            "Opportunity ID": "opp-int-2",
            "Status": "Technical Screen",
            "Selected Resume": "Candidate RevOps Analyst Resume",
            "stage_history": [{"stage": "Applied"}, {"stage": "Recruiter Screen"}, {"stage": "Technical Screen"}]
        })

        kpis = PipelineKPIService.calculate_kpis(opps)
        self.assertEqual(kpis["total_tracked"], 50)
        self.assertEqual(kpis["total_applied"], 50)
        self.assertEqual(kpis["total_active_opportunities"], 2)
        self.assertEqual(kpis["total_active"], 2)
        self.assertEqual(kpis["total_interviewed"], 2)
        self.assertEqual(kpis["apps_per_interview"], "1:25")

    def test_distinct_interview_counting_across_multiple_rounds(self):
        # 1 application progressing through Recruiter Screen, Technical Screen, and Final Round
        # must count as exactly 1 interviewed application
        opp = {
            "Opportunity ID": "opp-multi-round",
            "Status": "Final Round",
            "Selected Resume": "Candidate RevOps Analyst Resume",
            "stage_history": [
                {"stage": "Applied"},
                {"stage": "Recruiter Screen"},
                {"stage": "Hiring Manager"},
                {"stage": "Technical Screen"},
                {"stage": "Final Round"}
            ]
        }
        kpis = PipelineKPIService.calculate_kpis([opp])
        self.assertEqual(kpis["total_interviewed"], 1)
        self.assertEqual(kpis["total_active_opportunities"], 1)
        self.assertEqual(kpis["apps_per_interview"], "1:1")

    def test_historical_interview_counted_after_terminal_stage(self):
        # Application was interviewed but later rejected
        opp = {
            "Opportunity ID": "opp-rejected-after-interview",
            "Status": "Application Rejected",
            "Selected Resume": "Candidate RevOps Analyst Resume",
            "stage_history": [
                {"stage": "Applied"},
                {"stage": "Recruiter Screen"},
                {"stage": "Application Rejected"}
            ]
        }
        kpis = PipelineKPIService.calculate_kpis([opp])
        self.assertEqual(kpis["total_applied"], 1)
        self.assertEqual(kpis["total_interviewed"], 1)
        self.assertEqual(kpis["total_active_opportunities"], 0)
        self.assertEqual(kpis["apps_per_interview"], "1:1")

    def test_zero_interviews_returns_dash(self):
        opps = [
            {"Opportunity ID": "opp-1", "Status": "Applied", "Selected Resume": "RevOps Analyst"},
            {"Opportunity ID": "opp-2", "Status": "Applied", "Selected Resume": "RevOps Analyst"}
        ]
        kpis = PipelineKPIService.calculate_kpis(opps)
        self.assertEqual(kpis["total_applied"], 2)
        self.assertEqual(kpis["total_interviewed"], 0)
        self.assertEqual(kpis["apps_per_interview"], "—")

    def test_zero_submitted_returns_dash(self):
        opps = [
            {"Opportunity ID": "opp-1", "Status": "Pending", "Selected Resume": "RevOps Analyst"},
            {"Opportunity ID": "opp-2", "Status": "Processed", "Selected Resume": "RevOps Analyst"}
        ]
        kpis = PipelineKPIService.calculate_kpis(opps)
        self.assertEqual(kpis["total_applied"], 0)
        self.assertEqual(kpis["total_interviewed"], 0)
        self.assertEqual(kpis["apps_per_interview"], "—")
        self.assertEqual(kpis["apps_per_interest"], "—")

    def test_positive_interest_stages_and_conversion_metrics(self):
        expected = {
            "Employer Interest", "Recruiter Screen", "Hiring Manager",
            "Technical Screen", "Final Round", "Offer"
        }
        self.assertEqual(POSITIVE_INTEREST_STAGES, expected)

        # 1. Employer Interest qualifies for positive interest, but NOT interview
        opp_ei = {
            "Opportunity ID": "opp-ei",
            "Status": "Employer Interest",
            "stage_history": [{"stage": "Applied"}, {"stage": "Employer Interest"}]
        }
        self.assertTrue(PipelineKPIService.has_positive_interest(opp_ei))
        self.assertFalse(PipelineKPIService.has_interviewed(opp_ei))

        # 2. Offer without interview history qualifies for positive interest, but NOT interview
        opp_offer_only = {
            "Opportunity ID": "opp-offer",
            "Status": "Offer",
            "stage_history": [{"stage": "Applied"}, {"stage": "Offer"}]
        }
        self.assertTrue(PipelineKPIService.has_positive_interest(opp_offer_only))
        self.assertFalse(PipelineKPIService.has_interviewed(opp_offer_only))

        # 3. Offer WITH interview history qualifies for both
        opp_offer_int = {
            "Opportunity ID": "opp-offer-int",
            "Status": "Offer",
            "stage_history": [{"stage": "Applied"}, {"stage": "Recruiter Screen"}, {"stage": "Offer"}]
        }
        self.assertTrue(PipelineKPIService.has_positive_interest(opp_offer_int))
        self.assertTrue(PipelineKPIService.has_interviewed(opp_offer_int))

        # 4. Recruiter Screen qualifies for both
        opp_rs = {
            "Opportunity ID": "opp-rs",
            "Status": "Recruiter Screen",
            "stage_history": [{"stage": "Applied"}, {"stage": "Recruiter Screen"}]
        }
        self.assertTrue(PipelineKPIService.has_positive_interest(opp_rs))
        self.assertTrue(PipelineKPIService.has_interviewed(opp_rs))

        # 5. Rejected after interview qualifies for both historically
        opp_rej_int = {
            "Opportunity ID": "opp-rej-int",
            "Status": "Application Rejected",
            "stage_history": [{"stage": "Applied"}, {"stage": "Recruiter Screen"}, {"stage": "Application Rejected"}]
        }
        self.assertTrue(PipelineKPIService.has_positive_interest(opp_rej_int))
        self.assertTrue(PipelineKPIService.has_interviewed(opp_rej_int))

        # 6. Aggregate calculation with 50 submitted applications:
        # - 45 standard Applied
        # - 3 Employer Interest only
        # - 2 Recruiter Screen (interview)
        opps = []
        for i in range(45):
            opps.append({"Opportunity ID": f"app-{i}", "Status": "Applied"})
        for i in range(3):
            opps.append({
                "Opportunity ID": f"ei-{i}",
                "Status": "Employer Interest",
                "stage_history": [{"stage": "Applied"}, {"stage": "Employer Interest"}]
            })
        for i in range(2):
            opps.append({
                "Opportunity ID": f"rs-{i}",
                "Status": "Recruiter Screen",
                "stage_history": [{"stage": "Applied"}, {"stage": "Recruiter Screen"}]
            })

        kpis = PipelineKPIService.calculate_kpis(opps)
        self.assertEqual(kpis["total_applied"], 50)
        self.assertEqual(kpis["total_positive_interest"], 5)
        self.assertEqual(kpis["total_interviewed"], 2)
        self.assertEqual(kpis["apps_per_interest"], "1:10")
        self.assertEqual(kpis["apps_per_interview"], "1:25")

    def test_submitted_applications_by_strategy_breakdown(self):
        # 10 records total: 7 submitted, 3 unsubmitted
        opps = [
            {"Opportunity ID": "sub-1", "Status": "Applied", "Category": "Target"},
            {"Opportunity ID": "sub-2", "Status": "Applied", "Category": "Target"},
            {"Opportunity ID": "sub-3", "Status": "Recruiter Screen", "Category": "Target"},
            {"Opportunity ID": "sub-4", "Status": "Applied", "Category": "Stretch"},
            {"Opportunity ID": "sub-5", "Status": "Application Rejected", "Category": "Stretch", "stage_history": [{"stage": "Applied"}, {"stage": "Application Rejected"}]},
            {"Opportunity ID": "sub-6", "Status": "Applied", "Category": "Practice"},
            {"Opportunity ID": "sub-7", "Status": "Applied", "Category": "CustomRandomCat"},  # unassigned
            # Unsubmitted:
            {"Opportunity ID": "unsub-1", "Status": "Pending", "Category": "Target"},
            {"Opportunity ID": "unsub-2", "Status": "Processed", "Category": "Stretch"},
            {"Opportunity ID": "unsub-3", "Status": "Declined to Apply", "Category": "Target"},
        ]
        kpis = PipelineKPIService.calculate_kpis(opps)
        self.assertEqual(kpis["total_tracked"], 10)
        self.assertEqual(kpis["total_applied"], 7)

        cats = kpis["submitted_categories"]
        self.assertEqual(cats["Target"], 3)
        self.assertEqual(cats["Stretch"], 2)
        self.assertEqual(cats["Practice"], 1)
        self.assertEqual(cats["Opportunistic"], 0)
        self.assertEqual(cats["Fallback"], 0)
        self.assertEqual(cats["Unassigned"], 1)
        self.assertEqual(sum(cats.values()), 7)
        self.assertEqual(sum(cats.values()), kpis["total_applied"])

    def test_canonical_resume_variant_normalization_and_unassigned(self):
        # RevOps variants (dict and string)
        self.assertEqual(
            PipelineKPIService.get_canonical_resume_variant({"Selected Resume": "Candidate RevOps Analyst Resume"}),
            "RevOps Analyst"
        )
        self.assertEqual(
            PipelineKPIService.get_canonical_resume_variant("Matt Hackett - RevOps Analyst Resume.docx"),
            "RevOps Analyst"
        )
        self.assertEqual(
            PipelineKPIService.get_canonical_resume_variant({"Selected Resume": "Revenue Operations Analyst"}),
            "RevOps Analyst"
        )
        # GTM variants
        self.assertEqual(
            PipelineKPIService.get_canonical_resume_variant({"Selected Resume": "Candidate GTM Engineer Resume"}),
            "GTM Engineer"
        )
        # Unassigned / empty
        self.assertEqual(
            PipelineKPIService.get_canonical_resume_variant({}),
            "Unassigned"
        )
        self.assertEqual(
            PipelineKPIService.get_canonical_resume_variant(""),
            "Unassigned"
        )

    def test_resume_breakdown_table_and_aggregate_totals_row(self):
        opps = []
        for i in range(25):
            opps.append({"Opportunity ID": f"rev-{i}", "Status": "Applied", "Selected Resume": "RevOps Analyst"})
        opps.append({
            "Opportunity ID": "rev-int",
            "Status": "Recruiter Screen",
            "Selected Resume": "RevOps Analyst",
            "stage_history": [{"stage": "Applied"}, {"stage": "Recruiter Screen"}]
        })

        for i in range(9):
            opps.append({"Opportunity ID": f"gtm-{i}", "Status": "Applied", "Selected Resume": "GTM Engineer"})
        opps.append({
            "Opportunity ID": "gtm-int",
            "Status": "Technical Screen",
            "Selected Resume": "GTM Engineer",
            "stage_history": [{"stage": "Applied"}, {"stage": "Technical Screen"}]
        })

        kpis = PipelineKPIService.calculate_kpis(opps)
        rows = {r["variant"]: r for r in kpis["variant_rows"]}

        self.assertIn("RevOps Analyst", rows)
        self.assertIn("GTM Engineer", rows)
        self.assertEqual(rows["RevOps Analyst"]["applied"], 26)
        self.assertEqual(rows["RevOps Analyst"]["active"], 1)
        self.assertEqual(rows["RevOps Analyst"]["apps_per_interest"], "1:26")
        self.assertEqual(rows["RevOps Analyst"]["apps_per_interview"], "1:26")
        self.assertEqual(rows["GTM Engineer"]["applied"], 10)
        self.assertEqual(rows["GTM Engineer"]["active"], 1)
        self.assertEqual(rows["GTM Engineer"]["apps_per_interest"], "1:10")
        self.assertEqual(rows["GTM Engineer"]["apps_per_interview"], "1:10")

        # Aggregate totals row
        tot = kpis["totals_row"]
        self.assertEqual(tot["applied"], 36)
        self.assertEqual(tot["active"], 2)
        self.assertEqual(tot["interest"], 2)
        self.assertEqual(tot["interviewed"], 2)
        self.assertEqual(tot["apps_per_interest"], "1:18")
        self.assertEqual(tot["apps_per_interview"], "1:18")


class TestPhase1StalenessAndFreshness(unittest.TestCase):
    """Test suite for derived staleness indicators, boundary conditions, and fallbacks."""

    def setUp(self):
        self.ref_now = datetime(2026, 10, 11, 12, 0, 0)

    def test_staleness_boundary_conditions(self):
        threshold = 28
        # Exactly 28.0 days ago -> Stale
        t_28d = self.ref_now - timedelta(days=28)
        opp_exact = {
            "Status": "Applied",
            "stage_history": [{"stage": "Applied", "entered_at": t_28d.isoformat()}]
        }
        self.assertTrue(PipelineKPIService.is_stale(opp_exact, threshold_days=threshold, reference_date=self.ref_now))

        # 27.9 days ago -> Fresh (not stale)
        t_27_9d = self.ref_now - timedelta(days=27, hours=21, minutes=36)
        opp_fresh = {
            "Status": "Applied",
            "stage_history": [{"stage": "Applied", "entered_at": t_27_9d.isoformat()}]
        }
        self.assertFalse(PipelineKPIService.is_stale(opp_fresh, threshold_days=threshold, reference_date=self.ref_now))

        # 28.1 days ago -> Stale
        t_28_1d = self.ref_now - timedelta(days=28, hours=2, minutes=24)
        opp_stale = {
            "Status": "Applied",
            "stage_history": [{"stage": "Applied", "entered_at": t_28_1d.isoformat()}]
        }
        self.assertTrue(PipelineKPIService.is_stale(opp_stale, threshold_days=threshold, reference_date=self.ref_now))

    def test_terminal_stages_excluded_from_staleness(self):
        # Terminal records must NEVER be marked stale even if 100 days old
        old_time = (self.ref_now - timedelta(days=100)).isoformat()
        terminal_stages = ["Declined to Apply", "Application Rejected", "Rejected", "Withdrawn", "Archived"]

        for stage in terminal_stages:
            opp = {
                "Status": stage,
                "stage_history": [{"stage": "Applied"}, {"stage": stage, "entered_at": old_time}]
            }
            self.assertFalse(
                PipelineKPIService.is_stale(opp, threshold_days=28, reference_date=self.ref_now),
                f"Terminal stage '{stage}' must be excluded from staleness monitoring"
            )

    def test_unsubmitted_stages_excluded_from_staleness(self):
        # Pending and Processed are not submitted, so excluded from staleness
        old_time = (self.ref_now - timedelta(days=60)).isoformat()
        for unsubmitted_stage in ["Pending", "Processed"]:
            opp = {
                "Status": unsubmitted_stage,
                "stage_history": [{"stage": unsubmitted_stage, "entered_at": old_time}]
            }
            self.assertFalse(
                PipelineKPIService.is_stale(opp, threshold_days=28, reference_date=self.ref_now),
                f"Unsubmitted stage '{unsubmitted_stage}' must be excluded from staleness"
            )

    def test_missing_timestamps_fallback(self):
        # 1. Fallback to Date Created when stage history has no timestamps
        old_created = (self.ref_now - timedelta(days=35)).strftime("%Y-%m-%d")
        opp_fallback = {
            "Status": "Applied",
            "Date Created": old_created,
            "stage_history": [{"stage": "Applied"}]
        }
        dt, src = PipelineKPIService.get_last_stage_transition_date(opp_fallback)
        self.assertEqual(src, "date_created")
        self.assertTrue(PipelineKPIService.is_stale(opp_fallback, threshold_days=28, reference_date=self.ref_now))

        # 2. Both stage_history timestamps and Date Created missing -> gracefully returns False
        opp_no_dates = {
            "Status": "Applied",
            "stage_history": []
        }
        dt_missing, src_missing = PipelineKPIService.get_last_stage_transition_date(opp_no_dates)
        self.assertIsNone(dt_missing)
        self.assertEqual(src_missing, "missing")
        self.assertFalse(PipelineKPIService.is_stale(opp_no_dates, threshold_days=28, reference_date=self.ref_now))

    def test_active_but_stale_applications(self):
        # An application at Recruiter Screen that has had no stage update for 35 days
        old_time = (self.ref_now - timedelta(days=35)).isoformat()
        opp = {
            "Opportunity ID": "opp-active-stale",
            "Company Name": "CloudScale",
            "Status": "Recruiter Screen",
            "stage_history": [
                {"stage": "Applied", "entered_at": (self.ref_now - timedelta(days=45)).isoformat()},
                {"stage": "Recruiter Screen", "entered_at": old_time}
            ]
        }
        # 1. Stale must be True
        self.assertTrue(PipelineKPIService.is_stale(opp, threshold_days=28, reference_date=self.ref_now))
        # 2. Must NOT remove application from Active Opportunities
        self.assertTrue(PipelineKPIService.is_active(opp))

        # 3. calculate_kpis reflects both
        kpis = PipelineKPIService.calculate_kpis([opp], stale_threshold_days=28, reference_date=self.ref_now)
        self.assertEqual(kpis["total_active_opportunities"], 1)
        self.assertEqual(kpis["total_stale"], 1)

    def test_non_stage_edits_do_not_reset_freshness(self):
        # Record with recent notes and recent Last Modified, but stage transition was 35 days ago
        stg_time = (self.ref_now - timedelta(days=35)).isoformat()
        opp = {
            "Status": "Applied",
            "Notes": "Spoke with recruiter yesterday on LinkedIn",
            "Last Modified": self.ref_now.strftime("%Y-%m-%d %H:%M:%S"),
            "stage_history": [{"stage": "Applied", "entered_at": stg_time}]
        }
        self.assertTrue(
            PipelineKPIService.is_stale(opp, threshold_days=28, reference_date=self.ref_now),
            "Non-stage updates (notes, last modified) must not reset stage transition staleness"
        )

    def test_meaningful_activity_resets_staleness(self):
        old_stage_time = (self.ref_now - timedelta(days=40)).isoformat()
        recent_activity_time = (self.ref_now - timedelta(days=5)).isoformat()

        # 1. Structured interaction / touchpoint resets stale clock
        opp_touchpoint = {
            "Opportunity ID": "opp-tp",
            "Status": "Applied",
            "stage_history": [{"stage": "Applied", "entered_at": old_stage_time}],
            "interactions": [{"timestamp": recent_activity_time, "type": "recruiter_screen_invite"}]
        }
        self.assertFalse(PipelineKPIService.is_stale(opp_touchpoint, threshold_days=28, reference_date=self.ref_now))
        dt, src = PipelineKPIService.get_last_meaningful_activity_date(opp_touchpoint)
        self.assertEqual(src, "interaction")

        # 2. Role Intelligence Generated At resets stale clock
        opp_ri = {
            "Opportunity ID": "opp-ri",
            "Status": "Recruiter Screen",
            "stage_history": [{"stage": "Applied", "entered_at": old_stage_time}],
            "Role Intelligence Generated At": recent_activity_time
        }
        self.assertFalse(PipelineKPIService.is_stale(opp_ri, threshold_days=28, reference_date=self.ref_now))
        dt, src = PipelineKPIService.get_last_meaningful_activity_date(opp_ri)
        self.assertEqual(src, "role_intelligence")

        # 3. Reliably timestamped note entry resets stale clock
        recent_date_str = (self.ref_now - timedelta(days=4)).strftime("%Y-%m-%d")
        opp_ts_note = {
            "Opportunity ID": "opp-note",
            "Status": "Applied",
            "stage_history": [{"stage": "Applied", "entered_at": old_stage_time}],
            "Notes": f"[{recent_date_str}] Followed up with hiring manager on email."
        }
        self.assertFalse(PipelineKPIService.is_stale(opp_ts_note, threshold_days=28, reference_date=self.ref_now))
        dt, src = PipelineKPIService.get_last_meaningful_activity_date(opp_ts_note)
        self.assertEqual(src, "timestamped_note")

    def test_configurable_stale_threshold(self):
        # Record 20 days old
        t_20d = (self.ref_now - timedelta(days=20)).isoformat()
        opp = {
            "Status": "Applied",
            "stage_history": [{"stage": "Applied", "entered_at": t_20d}]
        }
        # Threshold 14 -> Stale
        self.assertTrue(PipelineKPIService.is_stale(opp, threshold_days=14, reference_date=self.ref_now))
        # Threshold 28 -> Fresh
        self.assertFalse(PipelineKPIService.is_stale(opp, threshold_days=28, reference_date=self.ref_now))
        # Threshold 45 -> Fresh
        self.assertFalse(PipelineKPIService.is_stale(opp, threshold_days=45, reference_date=self.ref_now))

    def test_filter_opportunities_by_freshness(self):
        fresh_time = (self.ref_now - timedelta(days=5)).isoformat()
        stale_time = (self.ref_now - timedelta(days=35)).isoformat()

        opp_fresh = {
            "Opportunity ID": "o-1",
            "Status": "Applied",
            "stage_history": [{"stage": "Applied", "entered_at": fresh_time}]
        }
        opp_stale = {
            "Opportunity ID": "o-2",
            "Status": "Applied",
            "stage_history": [{"stage": "Applied", "entered_at": stale_time}]
        }
        opps = [opp_fresh, opp_stale]

        # 1. All Freshness
        all_res = PipelineSearchPaginationService.filter_opportunities(
            opps, freshness_filter="All Freshness", reference_date=self.ref_now
        )
        self.assertEqual(len(all_res), 2)

        # 2. Stale Only
        stale_res = PipelineSearchPaginationService.filter_opportunities(
            opps, freshness_filter="Stale Only (≥28d)", reference_date=self.ref_now
        )
        self.assertEqual(len(stale_res), 1)
        self.assertEqual(stale_res[0]["Opportunity ID"], "o-2")

        # 3. Fresh Only
        fresh_res = PipelineSearchPaginationService.filter_opportunities(
            opps, freshness_filter="Fresh Only (<28d)", reference_date=self.ref_now
        )
        self.assertEqual(len(fresh_res), 1)
        self.assertEqual(fresh_res[0]["Opportunity ID"], "o-1")


if __name__ == "__main__":
    unittest.main()
