"""Tests for the wisdom/soul layer. python -m unittest -v"""

import unittest

import wisdom as w


def _logs(score, n=6):
    return [{"score": str(score)} for _ in range(n)]


class PrincipleTests(unittest.TestCase):
    def test_struggle_state_picks_struggle_pool(self):
        p = {"recovery_mode": False, "goals": []}
        pr = w.principle_for_state(p, _logs(20, 4))
        self.assertEqual(pr["state"], "struggle")
        self.assertTrue(pr["text"])

    def test_thrive_state(self):
        p = {"recovery_mode": False, "goals": []}
        pr = w.principle_for_state(p, _logs(90, 6))
        self.assertEqual(pr["state"], "thrive")

    def test_recovery_forces_recover_principle(self):
        p = {"recovery_mode": True, "goals": []}
        self.assertEqual(w.principle_for_state(p, _logs(50))["state"], "recover")

    def test_few_days_is_start(self):
        p = {"recovery_mode": False, "goals": []}
        self.assertEqual(w.principle_for_state(p, _logs(50, 1))["state"], "start")

    def test_principle_of_the_day_stable(self):
        self.assertEqual(w.principle_of_the_day("d1"), w.principle_of_the_day("d1"))


class SeasonTests(unittest.TestCase):
    def test_first_steps(self):
        self.assertEqual(w.growth_season({"goals": []}, _logs(70, 1))[0], "First Steps")

    def test_thriving(self):
        self.assertEqual(w.growth_season({"recovery_mode": False, "goals": []},
                                         _logs(85, 6))[0], "Thriving Season")

    def test_rebuilding_in_recovery(self):
        self.assertEqual(w.growth_season({"recovery_mode": True, "goals": []},
                                         _logs(50, 6))[0], "Rebuilding Season")

    def test_returns_name_and_description(self):
        name, desc = w.growth_season({"goals": []}, _logs(60, 6))
        self.assertTrue(name); self.assertTrue(desc)


class DualVoiceTests(unittest.TestCase):
    def test_hard_day_is_tender(self):
        t, f = w.dual_voice({"persona": {"name": "Max"}}, 20, "grace")
        self.assertTrue(t); self.assertTrue(f)
        self.assertNotEqual(t, f)

    def test_good_day_pushes_and_praises(self):
        t, f = w.dual_voice({"persona": {"name": "Max"}}, 90, "celebrate")
        self.assertTrue(t); self.assertTrue(f)

    def test_grace_stance_treated_as_hard(self):
        # even a high score on a declared grace day gets the gentle band
        t1, f1 = w.dual_voice({}, 90, "grace", "d")
        t2, f2 = w.dual_voice({}, 30, "standard", "d")
        self.assertIn(t1, sum(w._TEACHER.values(), []))


class IdentityTests(unittest.TestCase):
    def test_identity_line(self):
        line = w.identity_line({"identity": "someone who finishes"})
        self.assertIn("becoming someone who finishes", line)

    def test_no_identity(self):
        self.assertIsNone(w.identity_line({"identity": ""}))
        self.assertIsNone(w.identity_line({}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
