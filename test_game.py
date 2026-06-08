"""Tests for the fun layer. python -m unittest -v"""

import unittest

import game as gm
import features as fx


class XPTests(unittest.TestCase):
    def test_score_drives_xp(self):
        self.assertGreater(gm.xp_for_checkin(100, 0), gm.xp_for_checkin(20, 0))

    def test_grace_still_earns(self):
        self.assertGreaterEqual(gm.xp_for_checkin(0, 0, grace=True), 20)

    def test_combo_multiplies(self):
        low = gm.xp_for_checkin(80, 0)
        high = gm.xp_for_checkin(80, 8)        # 8-day combo + streak bonus
        self.assertGreater(high, low)

    def test_draw_bonus_added(self):
        self.assertEqual(gm.xp_for_checkin(0, 0, grace=True, draw_bonus=10),
                         gm.xp_for_checkin(0, 0, grace=True) + 10)

    def test_never_negative(self):
        self.assertGreaterEqual(gm.xp_for_checkin(0, 0), 0)


class ComboTests(unittest.TestCase):
    def test_base_is_one(self):
        self.assertEqual(gm.combo_multiplier(0), 1.0)
    def test_caps_at_two(self):
        self.assertEqual(gm.combo_multiplier(50), 2.0)
    def test_scales(self):
        self.assertEqual(gm.combo_multiplier(5), 1.5)


class LevelTests(unittest.TestCase):
    def test_level_one_at_zero(self):
        lvl, title, into, need = gm.level_from_xp(0)
        self.assertEqual(lvl, 1)
        self.assertEqual(title, "Novice")
        self.assertEqual(into, 0)

    def test_levels_increase_with_xp(self):
        self.assertGreater(gm.level_from_xp(2000)[0], gm.level_from_xp(200)[0])

    def test_title_climbs(self):
        self.assertEqual(gm.title_for_level(1), "Novice")
        self.assertNotEqual(gm.title_for_level(22), "Novice")

    def test_xp_bar_has_level_and_bar(self):
        s = gm.xp_bar(120)
        self.assertIn("Lv", s)
        self.assertIn("XP", s)


class DrawTests(unittest.TestCase):
    def test_draw_is_deterministic_per_day(self):
        self.assertEqual(gm.daily_draw("2026-05-01"), gm.daily_draw("2026-05-01"))

    def test_draw_has_fields(self):
        d = gm.daily_draw("2026-05-02")
        self.assertIn("label", d); self.assertIn("flavor", d); self.assertIn("xp", d)


class MonsterTests(unittest.TestCase):
    def test_win_on_high_score(self):
        self.assertIn("slayed", gm.monster_line(90))
    def test_loss_on_low_score(self):
        self.assertIn("won today", gm.monster_line(20))
    def test_draw_in_middle(self):
        self.assertIn("draw", gm.monster_line(60).lower())


class ContentTests(unittest.TestCase):
    def test_joke_and_fortune_stable_per_day(self):
        self.assertEqual(gm.joke_of_the_day("d1"), gm.joke_of_the_day("d1"))
        self.assertEqual(gm.fortune_of_the_day("d1"), gm.fortune_of_the_day("d1"))

    def test_random_joke_returns_string(self):
        self.assertIsInstance(gm.random_joke(), str)


class PlayfulVoiceTests(unittest.TestCase):
    def test_playful_is_a_voice(self):
        self.assertIn("playful", fx.VOICES)

    def test_playful_message_differs(self):
        p = {"persona": {"name": "Max", "voice": "playful", "traits": []}}
        q = {"persona": {"name": "Max", "voice": "firm", "traits": []}}
        self.assertNotEqual(fx.persona_message(p, 30, "ROCK BOTTOM"),
                            fx.persona_message(q, 30, "ROCK BOTTOM"))


class QuoteAvatarTests(unittest.TestCase):
    def test_quote_stable_per_day(self):
        self.assertEqual(gm.quote_of_the_day("d1"), gm.quote_of_the_day("d1"))

    def test_quote_has_text_and_author(self):
        text, who = gm.quote_of_the_day("d2")
        self.assertTrue(text); self.assertTrue(who)

    def test_avatar_grows_with_level(self):
        self.assertEqual(gm.avatar_for_level(1)[1], "Seedling")
        self.assertEqual(gm.avatar_for_level(22)[1], "Legendary")

    def test_avatar_returns_glyph_and_label(self):
        glyph, label = gm.avatar_for_level(8)
        self.assertTrue(glyph); self.assertTrue(label)


class TemplateTests(unittest.TestCase):
    def test_templates_exist(self):
        self.assertIn("Student", fx.GOAL_TEMPLATES)
        self.assertEqual(len(fx.GOAL_TEMPLATES["Student"]), 3)

    def test_template_goals_well_formed(self):
        for preset in fx.GOAL_TEMPLATES.values():
            for g in preset:
                self.assertIn("name", g); self.assertIn("target", g)
                self.assertGreater(g["target"], 0)


class FunBadgeTests(unittest.TestCase):
    def _logs(self, scores):
        import datetime
        d0 = datetime.date(2026, 1, 1)
        out = []
        for i, s in enumerate(scores):
            out.append({"date": (d0 + datetime.timedelta(days=i)).isoformat(),
                        "score": str(s), "actual_0": "1", "target_0": "3"})
        return out

    def test_goblin_mode(self):
        p = {"goals": [{"name": "G"}], "badges": []}
        self.assertIn("goblin_mode", fx.check_badges(p, self._logs([0, 80])))

    def test_overachiever(self):
        p = {"goals": [{"name": "G"}], "badges": []}
        self.assertIn("overachiever", fx.check_badges(p, self._logs([100, 100, 100])))


class UnlockTests(unittest.TestCase):
    def test_essentials_unlocked_at_level_1(self):
        for s in ("Home", "Check-in", "Dashboard", "Goals", "Reminder"):
            self.assertTrue(gm.is_unlocked(s, 1))

    def test_advanced_locked_at_level_1(self):
        self.assertFalse(gm.is_unlocked("Patterns", 1))
        self.assertFalse(gm.is_unlocked("Event Log", 1))

    def test_everything_unlocks_eventually(self):
        for s in gm.SCREEN_UNLOCKS:
            self.assertTrue(gm.is_unlocked(s, 10))

    def test_next_unlock_points_forward(self):
        nu = gm.next_unlock(1)
        self.assertIsNotNone(nu)
        self.assertGreater(nu["level"], 1)

    def test_next_unlock_none_when_maxed(self):
        self.assertIsNone(gm.next_unlock(10))


class ProtectedStreakTests(unittest.TestCase):
    def test_freeze_bridges_a_gap(self):
        import datetime
        days = [datetime.date(2026, 5, 1), datetime.date(2026, 5, 2),
                datetime.date(2026, 5, 4)]
        frozen = [datetime.date(2026, 5, 3)]
        self.assertEqual(gm.protected_streak(days, frozen), 4)

    def test_unfrozen_gap_breaks(self):
        import datetime
        days = [datetime.date(2026, 5, 1), datetime.date(2026, 5, 2),
                datetime.date(2026, 5, 4)]
        self.assertEqual(gm.protected_streak(days, []), 1)

    def test_empty(self):
        self.assertEqual(gm.protected_streak([], []), 0)


class ComebackTests(unittest.TestCase):
    def test_quiet_for_recent(self):
        self.assertIsNone(gm.comeback_message("Max", 1))
        self.assertIsNone(gm.comeback_message("Max", 2))   # a freeze covers this

    def test_warm_after_a_real_gap(self):
        msg = gm.comeback_message("Max", 5)
        self.assertIsNotNone(msg)
        self.assertIn("Welcome back", msg)

    def test_days_since(self):
        import datetime
        self.assertEqual(gm.days_since_last([datetime.date(2026, 5, 1)],
                                            datetime.date(2026, 5, 4)), 3)


class MilestoneTests(unittest.TestCase):
    def test_returns_chaseable_items(self):
        profile = {"xp": 40}
        items = gm.next_milestone(profile, [])
        self.assertTrue(items)
        self.assertTrue(all("remaining" in m and "label" in m for m in items))


if __name__ == "__main__":
    unittest.main(verbosity=2)
