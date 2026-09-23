import unittest
from job_pipeline.domain.models import ScreeningQA, JobPosting
from job_pipeline.domain.services import ScreeningQAService


class TestScreeningQAService(unittest.TestCase):

    def test_model_creation(self):
        item = ScreeningQA(
            question="Why are you interested in this role?",
            answer="I have extensive experience building scalable RevOps architectures.",
            category="Culture"
        )
        self.assertEqual(item.question, "Why are you interested in this role?")
        self.assertEqual(item.category, "Culture")
        self.assertTrue(len(item.created_at) > 0)

    def test_questions_for_company_category(self):
        from job_pipeline.domain.models import SCREENING_CATEGORIES
        self.assertIn("Questions for Company", SCREENING_CATEGORIES)
        item = ScreeningQA(
            question="Do you have any questions for us?",
            answer="What are the highest-leverage milestones for this role during the first 90 days?",
            category="Questions for Company"
        )
        self.assertEqual(item.category, "Questions for Company")


    def test_format_screening_gdoc_text(self):
        items = [
            ScreeningQA(
                question="What is your experience with Salesforce and dbt?",
                answer="5+ years managing enterprise Salesforce instances and building core reporting models in dbt.",
                category="Technical"
            ),
            ScreeningQA(
                question="What are your compensation expectations?",
                answer="My target base compensation is $115,000 - $130,000.",
                category="Salary"
            )
        ]

        text = ScreeningQAService.format_screening_gdoc_text(
            company_name="Acme Corp",
            job_title="RevOps Analyst",
            qa_items=items,
            opportunity_id="opp-12345"
        )

        self.assertIn("APPLICATION SCREENING QUESTIONS & ANSWERS", text)
        self.assertIn("Acme Corp", text)
        self.assertIn("RevOps Analyst", text)
        self.assertIn("opp-12345", text)
        self.assertIn("QUESTION 1 [Technical]:", text)
        self.assertIn("5+ years managing enterprise Salesforce instances", text)
        self.assertIn("QUESTION 2 [Salary]:", text)

    def test_format_qa_clipboard_summary(self):
        items = [
            ScreeningQA(question="Years of SQL?", answer="4 years")
        ]
        summary = ScreeningQAService.format_qa_clipboard_summary(items)
        self.assertEqual(summary, "Q1: Years of SQL?\nA1: 4 years")


if __name__ == "__main__":
    unittest.main()
