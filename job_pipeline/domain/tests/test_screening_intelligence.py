import unittest
from job_pipeline.domain.screening_intelligence import ScreeningIntelligenceService
from job_pipeline.domain.models import SCREENING_ARCHETYPES


class TestScreeningIntelligenceService(unittest.TestCase):
    def test_classify_archetype(self):
        # Compensation
        self.assertEqual(
            ScreeningIntelligenceService.classify_archetype("What are your salary expectations for this role?"),
            "COMPENSATION"
        )
        self.assertEqual(
            ScreeningIntelligenceService.classify_archetype("What is your expected hourly rate?"),
            "COMPENSATION"
        )

        # Work Auth
        self.assertEqual(
            ScreeningIntelligenceService.classify_archetype("Will you now or in the future require visa sponsorship?"),
            "WORK_AUTHORIZATION"
        )
        self.assertEqual(
            ScreeningIntelligenceService.classify_archetype("Are you authorized to work in the United States?"),
            "WORK_AUTHORIZATION"
        )

        # Technical Stack
        self.assertEqual(
            ScreeningIntelligenceService.classify_archetype("How many years of experience do you have with SQL and dbt?"),
            "TECHNICAL_STACK"
        )
        self.assertEqual(
            ScreeningIntelligenceService.classify_archetype("Describe your experience configuring Salesforce CPQ."),
            "TECHNICAL_STACK"
        )

        # Remote / Location
        self.assertEqual(
            ScreeningIntelligenceService.classify_archetype("Are you comfortable working in a 100% remote setting?"),
            "REMOTE_LOCATION"
        )

        # Leadership / Conflict
        self.assertEqual(
            ScreeningIntelligenceService.classify_archetype("Tell me about a time you handled stakeholder conflict."),
            "LEADERSHIP_CONFLICT"
        )

    def test_extract_competency_signals(self):
        signals = ScreeningIntelligenceService.extract_competency_signals(
            "Describe your hands-on experience with SQL, dbt, and building Salesforce data models."
        )
        self.assertIn("SQL", signals)
        self.assertIn("dbt", signals)
        self.assertIn("Salesforce", signals)
        self.assertIn("Data Modeling", signals)

    def test_similarity_scoring_and_recall(self):
        q1 = "What are your salary expectations for this role?"
        q2 = "What is your target salary or compensation range?"
        q3 = "How many years of SQL do you have?"

        score_similar = ScreeningIntelligenceService.calculate_similarity(q1, q2)
        score_different = ScreeningIntelligenceService.calculate_similarity(q1, q3)

        self.assertGreater(score_similar, 0.40)
        self.assertLess(score_different, 0.35)

        # Prior answer recall test
        history = [
            {
                "question": "What is your desired salary range?",
                "answer": "$125,000 - $135,000 base",
                "company_name": "Planful",
                "timestamp": "2026-09-20"
            },
            {
                "question": "How many years of experience with dbt and Snowflake?",
                "answer": "3+ years production dbt modeling",
                "company_name": "Fivetran",
                "timestamp": "2026-09-18"
            }
        ]

        matches = ScreeningIntelligenceService.find_similar_questions(
            query="What are your salary expectations?",
            history=history,
            threshold=0.35
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].company_name, "Planful")
        self.assertEqual(matches[0].matched_answer, "$125,000 - $135,000 base")
        self.assertEqual(matches[0].archetype, "COMPENSATION")

    def test_group_by_archetype(self):
        qa_list = [
            {"question": "Expected salary?", "answer": "$130k"},
            {"question": "Do you need sponsorship?", "answer": "No"},
            {"question": "Years with Salesforce?", "answer": "5 years"}
        ]
        grouped = ScreeningIntelligenceService.group_by_archetype(qa_list)
        self.assertEqual(len(grouped["COMPENSATION"]), 1)
        self.assertEqual(len(grouped["WORK_AUTHORIZATION"]), 1)
        self.assertEqual(len(grouped["TECHNICAL_STACK"]), 1)


if __name__ == "__main__":
    unittest.main()
