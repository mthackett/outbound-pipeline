import os
import unittest
from job_pipeline.domain.story_bank import StoryBankService
from job_pipeline.domain.models import CanonicalStory, StoryBreadcrumb


class TestStoryBankService(unittest.TestCase):
    def setUp(self):
        self.test_stories_path = "test_stories.json"
        if os.path.exists(self.test_stories_path):
            os.remove(self.test_stories_path)

    def tearDown(self):
        if os.path.exists(self.test_stories_path):
            os.remove(self.test_stories_path)

    def test_canonical_seeds_integrity(self):
        seeds = StoryBankService.get_default_seeds()
        self.assertEqual(len(seeds), 12)

        for s in seeds:
            self.assertTrue(s.story_id.startswith("story-"))
            self.assertGreater(s.story_number, 0)
            self.assertTrue(len(s.title) > 0)
            self.assertTrue(len(s.hook) > 0)
            self.assertTrue(len(s.problem) > 0)
            self.assertTrue(len(s.turning_point) > 0)
            self.assertTrue(len(s.result) > 0)
            self.assertTrue(len(s.learning) > 0)
            self.assertGreaterEqual(len(s.breadcrumbs), 3)
            self.assertGreaterEqual(len(s.trigger_keywords), 3)
            self.assertGreaterEqual(len(s.target_question_types), 3)

    def test_persistence_save_load_reset(self):
        # 1. Load initial with auto_seed=True -> creates test file
        stories = StoryBankService.load_stories(self.test_stories_path, auto_seed=True)
        self.assertEqual(len(stories), 12)
        self.assertTrue(os.path.exists(self.test_stories_path))

        # 2. Add custom breadcrumb to story-1
        stories[0].breadcrumbs.append(
            StoryBreadcrumb(label="Custom Soundbite", content="Testing custom breadcrumb", kind="metric")
        )
        StoryBankService.save_stories(stories, self.test_stories_path)

        # 3. Reload
        reloaded = StoryBankService.load_stories(self.test_stories_path)
        self.assertEqual(len(reloaded[0].breadcrumbs), 5)
        self.assertEqual(reloaded[0].breadcrumbs[-1].label, "Custom Soundbite")

        # 4. Reset to canonical defaults
        reset_stories = StoryBankService.reset_canonical_stories(self.test_stories_path)
        self.assertEqual(len(reset_stories[0].breadcrumbs), 4)

    def test_missing_file_and_create_story_from_scratch(self):
        # 1. When file is missing and auto_seed is False, returns empty list without creating file
        empty_stories = StoryBankService.load_stories(self.test_stories_path, auto_seed=False)
        self.assertEqual(len(empty_stories), 0)
        self.assertFalse(os.path.exists(self.test_stories_path))

        # 2. Create Story 1 from scratch
        new_story = CanonicalStory(
            story_id="story-1",
            story_number=1,
            title="Custom Created Story 1",
            archetype_tags=["Process Improvement"],
            competencies=["Operations"],
            industries=["Logistics"],
            is_locked=False,
            is_canonical=True,
            hook="Saved 20% on freight costs.",
            problem="High freight rates during peak quarter.",
            turning_point="Renegotiated regional carrier contracts.",
            result="Achieved 20% cost reduction.",
            learning="Early negotiation preserves margins.",
            breadcrumbs=[
                StoryBreadcrumb(label="The Problem", content="High rates", kind="context"),
                StoryBreadcrumb(label="Action", content="Renegotiated", kind="pivot"),
                StoryBreadcrumb(label="Result", content="20% savings", kind="metric")
            ],
            trigger_keywords=["freight", "logistics", "savings"],
            target_question_types=["Tell me about a cost savings project."]
        )

        # 3. add_story saves to disk and creates the file
        success = StoryBankService.add_story(new_story, self.test_stories_path)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(self.test_stories_path))

        # 4. Reload from disk
        loaded = StoryBankService.load_stories(self.test_stories_path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].title, "Custom Created Story 1")

        # 5. Delete story
        del_success = StoryBankService.delete_story("story-1", self.test_stories_path)
        self.assertTrue(del_success)
        reloaded_after_del = StoryBankService.load_stories(self.test_stories_path)
        self.assertEqual(len(reloaded_after_del), 0)

    def test_lock_toggle_and_guardrail_protection(self):
        StoryBankService.reset_canonical_stories(self.test_stories_path)

        # Initially unlocked
        stories = StoryBankService.load_stories(self.test_stories_path)
        self.assertFalse(stories[0].is_locked)

        # Lock story-1
        toggled = StoryBankService.toggle_story_lock("story-1", self.test_stories_path)
        self.assertTrue(toggled)

        stories_after_lock = StoryBankService.load_stories(self.test_stories_path)
        self.assertTrue(stories_after_lock[0].is_locked)

        # Attempt automated update without user override -> should be rejected!
        success_sys = StoryBankService.update_story(
            "story-1",
            {"title": "Automated Overwrite Attempt"},
            is_user_override=False,
            file_path=self.test_stories_path
        )
        self.assertFalse(success_sys)

        # Story title must remain unchanged
        check_stories = StoryBankService.load_stories(self.test_stories_path)
        self.assertEqual(check_stories[0].title, "The Revenue Pipeline Black Box")

        # Intentional user override edit -> should succeed
        success_user = StoryBankService.update_story(
            "story-1",
            {"title": "The Revenue Pipeline Black Box (Polished)"},
            is_user_override=True,
            file_path=self.test_stories_path
        )
        self.assertTrue(success_user)

        check_stories2 = StoryBankService.load_stories(self.test_stories_path)
        self.assertEqual(check_stories2[0].title, "The Revenue Pipeline Black Box (Polished)")

    def test_suggest_story_cue_cards(self):
        StoryBankService.reset_canonical_stories(self.test_stories_path)
        job_text = "We are seeking a Revenue Operations Analyst to audit our lead routing SLA in Salesforce."
        req_skills = ["Salesforce", "Lead Routing", "SLA Management"]
        pain_points = "Leads are slipping through the cracks between sales and marketing."

        cards = StoryBankService.suggest_story_cue_cards(
            job_text=job_text,
            req_skills=req_skills,
            pain_points=pain_points,
            role_family="revenue_operations",
            top_k=3,
            file_path=self.test_stories_path
        )

        self.assertGreaterEqual(len(cards), 1)
        # Story 2 (Lead Routing & SLA Crisis) should be top-ranked
        self.assertEqual(cards[0].story_id, "story-2")
        self.assertIn("Lead Routing & SLA Crisis", cards[0].title)
        self.assertTrue(len(cards[0].active_breadcrumbs) >= 3)

    def test_match_behavioral_prompt(self):
        StoryBankService.reset_canonical_stories(self.test_stories_path)
        prompt = "Tell me about a time you handled conflict between marketing and sales over lead quality."
        match = StoryBankService.match_behavioral_prompt(prompt, file_path=self.test_stories_path)

        self.assertIsNotNone(match)
        # Should match Story 4 (Disputed Marketing Attribution) or Story 2
        self.assertIn(match["story"].story_id, ["story-4", "story-2"])
        self.assertTrue(len(match["turning_point"]) > 0)
        self.assertTrue(len(match["result"]) > 0)

    def test_load_example_stories(self):
        # Verify loading the 2 generic placeholder stories from stories.json.example
        examples = StoryBankService.load_example_stories(example_path="stories.json.example", file_path=self.test_stories_path)
        self.assertEqual(len(examples), 2)
        self.assertEqual(examples[0].story_id, "story-1")
        self.assertEqual(examples[1].story_id, "story-2")
        self.assertTrue(os.path.exists(self.test_stories_path))


if __name__ == "__main__":
    unittest.main()
