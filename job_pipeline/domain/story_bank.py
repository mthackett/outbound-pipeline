import os
import json
import re
from typing import List, Dict, Any, Optional
from job_pipeline.domain.models import CanonicalStory, StoryBreadcrumb, StoryCueCard


class StoryBankService:
    """
    Service for managing the Global Professional Story Bank.
    Maintains 12 canonical behavioral stories with modular breadcrumbs,
    lock/unlock guardrails, story cue card generation, and interview transition mapping.
    """

    DEFAULT_STORIES_PATH = "stories.json"

    CANONICAL_SEEDS_PATH = os.path.join(os.path.dirname(__file__), "canonical_stories.json")

    @staticmethod
    def _deserialize_story_list(data: List[Dict[str, Any]]) -> List[CanonicalStory]:
        """Deserializes a list of dictionaries into validated CanonicalStory instances."""
        stories = []
        for item in data:
            b_items = [StoryBreadcrumb(**b) if isinstance(b, dict) else b for b in item.get("breadcrumbs", [])]
            item_copy = dict(item)
            item_copy["breadcrumbs"] = b_items
            stories.append(CanonicalStory(**item_copy))
        return stories

    @classmethod
    def get_default_seeds(cls, seed_path: Optional[str] = None) -> List[CanonicalStory]:
        """Returns clean instances of the 12 canonical seed stories from the seed JSON file."""
        path = seed_path or cls.CANONICAL_SEEDS_PATH
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return cls._deserialize_story_list(data)
            except Exception as e:
                print(f"Error reading canonical seeds from {path}: {e}")
        return []

    @classmethod
    def load_stories(cls, file_path: str = DEFAULT_STORIES_PATH, auto_seed: bool = False) -> List[CanonicalStory]:
        """
        Loads canonical stories from persistent storage.
        If file does not exist and auto_seed is False, returns empty list without creating file on disk.
        """
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return cls._deserialize_story_list(data)
            except Exception as e:
                print(f"Error loading {file_path}: {e}.")

        if auto_seed:
            seeds = cls.get_default_seeds()
            cls.save_stories(seeds, file_path)
            return seeds

        return []

    @classmethod
    def save_stories(cls, stories: List[CanonicalStory], file_path: str = DEFAULT_STORIES_PATH) -> bool:
        """Saves stories to persistent JSON file on disk, creating parent directories and file if needed."""
        try:
            serialized = [s.model_dump() for s in stories]
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(serialized, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving {file_path}: {e}")
            return False

    @classmethod
    def add_story(cls, story: CanonicalStory, file_path: str = DEFAULT_STORIES_PATH) -> bool:
        """Appends a new story to the bank and saves to disk, creating the file if it does not exist."""
        stories = cls.load_stories(file_path, auto_seed=False)
        # Avoid duplicate story_id
        for s in stories:
            if s.story_id == story.story_id:
                return False
        stories.append(story)
        return cls.save_stories(stories, file_path)

    @classmethod
    def delete_story(cls, story_id: str, file_path: str = DEFAULT_STORIES_PATH) -> bool:
        """Deletes a story by story_id and saves to disk."""
        stories = cls.load_stories(file_path, auto_seed=False)
        filtered = [s for s in stories if s.story_id != story_id]
        if len(filtered) < len(stories):
            return cls.save_stories(filtered, file_path)
        return False

    @classmethod
    def load_example_stories(cls, example_path: str = "stories.json.example", file_path: str = DEFAULT_STORIES_PATH) -> List[CanonicalStory]:
        """Loads stories from stories.json.example and writes them to file_path."""
        if os.path.exists(example_path):
            try:
                with open(example_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        stories = cls._deserialize_story_list(data)
                        cls.save_stories(stories, file_path)
                        return stories
            except Exception as e:
                print(f"Error loading {example_path}: {e}")
        return []

    @classmethod
    def reset_canonical_stories(cls, file_path: str = DEFAULT_STORIES_PATH) -> List[CanonicalStory]:
        """Resets the story bank back to the 12 pristine canonical seeds."""
        seeds = cls.get_default_seeds()
        cls.save_stories(seeds, file_path)
        return seeds

    @classmethod
    def toggle_story_lock(cls, story_id: str, file_path: str = DEFAULT_STORIES_PATH) -> bool:
        """Toggles the lock status of a canonical story."""
        stories = cls.load_stories(file_path)
        found = False
        for s in stories:
            if s.story_id == story_id:
                s.is_locked = not s.is_locked
                found = True
                break
        if found:
            cls.save_stories(stories, file_path)
        return found

    @classmethod
    def update_story(
        cls,
        story_id: str,
        updated_data: Dict[str, Any],
        is_user_override: bool = False,
        file_path: str = DEFAULT_STORIES_PATH
    ) -> bool:
        """
        Updates a story in the bank.
        Guardrail: If the story is locked and not explicitly an intentional user override, rejects the update!
        """
        stories = cls.load_stories(file_path)
        for idx, s in enumerate(stories):
            if s.story_id == story_id:
                if s.is_locked and not is_user_override:
                    # Guardrail: Rejection of automated / system overwrite on locked story
                    return False
                
                # Apply updates
                dump = s.model_dump()
                dump.update(updated_data)
                
                # Ensure breadcrumbs are properly cast
                if "breadcrumbs" in dump and isinstance(dump["breadcrumbs"], list):
                    dump["breadcrumbs"] = [
                        StoryBreadcrumb(**b) if isinstance(b, dict) else b for b in dump["breadcrumbs"]
                    ]

                stories[idx] = CanonicalStory(**dump)
                cls.save_stories(stories, file_path)
                return True

        return False

    @classmethod
    def suggest_story_cue_cards(
        cls,
        job_text: str = "",
        req_skills: Optional[List[str]] = None,
        pain_points: str = "",
        role_family: str = "",
        top_k: int = 4,
        file_path: str = DEFAULT_STORIES_PATH
    ) -> List[StoryCueCard]:
        """
        Dynamically analyzes a job description's tech stack, pain points, and role family,
        and generates ranked Story Cue Cards linking to the best-fit global canonical stories.
        """
        stories = cls.load_stories(file_path)
        req_skills = req_skills or []
        combined_text = f"{job_text} {' '.join(req_skills)} {pain_points} {role_family}".lower()

        scored_stories = []
        for s in stories:
            score = 0.0
            reasons = []

            # Match competencies & required skills
            for comp in s.competencies:
                c_lower = comp.lower()
                if c_lower in combined_text:
                    score += 2.0
                    reasons.append(f"Matched skill/tool: {comp}")

            # Match trigger keywords
            for kw in s.trigger_keywords:
                if re.search(r'\b' + re.escape(kw.lower()) + r'\b', combined_text):
                    score += 1.5
                    reasons.append(f"Matched keyword: '{kw}'")

            # Match archetype tags
            for arch in s.archetype_tags:
                if arch.lower() in combined_text:
                    score += 1.0

            # Default baseline so every story has some rank
            score += 0.1

            scored_stories.append((s, score, "; ".join(reasons[:2]) if reasons else "Core operational fit"))

        # Sort by score descending
        scored_stories.sort(key=lambda x: x[1], reverse=True)

        cue_cards = []
        for s, score, reason in scored_stories[:top_k]:
            # Determine recommended angle
            angle = s.archetype_tags[0] + " Angle" if s.archetype_tags else "Impact Angle"
            cue_cards.append(StoryCueCard(
                story_id=s.story_id,
                story_number=s.story_number,
                title=s.title,
                keywords=s.trigger_keywords[:5],
                turning_point=s.turning_point,
                result=s.result,
                target_question_types=s.target_question_types,
                recommended_angle=angle,
                relevance_reason=reason,
                active_breadcrumbs=s.breadcrumbs
            ))

        return cue_cards

    @classmethod
    def match_behavioral_prompt(
        cls,
        prompt: str,
        file_path: str = DEFAULT_STORIES_PATH
    ) -> Optional[Dict[str, Any]]:
        """
        Takes any interview prompt and instantly routes it to the matching canonical story,
        recommended angle, and cue card triggers.
        """
        if not prompt or not prompt.strip():
            return None

        stories = cls.load_stories(file_path)
        prompt_lower = prompt.lower()

        best_story = None
        best_score = -1.0
        best_match_q = ""

        for s in stories:
            score = 0.0
            # 1. Exact or high match with target question types
            for tq in s.target_question_types:
                tq_words = set(re.findall(r'\w+', tq.lower()))
                p_words = set(re.findall(r'\w+', prompt_lower))
                overlap = tq_words.intersection(p_words)
                if overlap:
                    curr_score = len(overlap) / len(tq_words.union(p_words))
                    if curr_score > score:
                        score = curr_score * 3.0
                        best_match_q = tq

            # 2. Trigger keywords
            for kw in s.trigger_keywords:
                if re.search(r'\b' + re.escape(kw.lower()) + r'\b', prompt_lower):
                    score += 1.5

            # 3. Archetype tags
            for arch in s.archetype_tags:
                if arch.lower() in prompt_lower:
                    score += 1.0

            if score > best_score:
                best_score = score
                best_story = s

        if best_story:
            return {
                "story": best_story,
                "score": round(best_score, 2),
                "matched_sample_question": best_match_q or best_story.target_question_types[0],
                "recommended_angle": f"{best_story.archetype_tags[0]} / {best_story.archetype_tags[1] if len(best_story.archetype_tags) > 1 else 'Impact'} Angle",
                "turning_point": best_story.turning_point,
                "result": best_story.result,
                "breadcrumbs": best_story.breadcrumbs,
                "keywords": best_story.trigger_keywords
            }

        return None
