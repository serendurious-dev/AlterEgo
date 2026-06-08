"""Tests for the coaching brain. python -m unittest -v"""

import datetime
import unittest

import coaching as co


def _profile():
    return {
        "created": "2026-01-01", "reminder_hour": 20,
        "persona": {"name": "The Scholar", "voice": "warm", "traits": ["kind"]},
        "chronotype": "night", "recovery_mode": False, "last_stance": None,
        "badges": [], "personal_bests": {}, "goals": [
            {"name": "Study", "unit": "hours", "target": 3.0, "weight": 3, "baseline": 1.0},
            {"name": "Sleep", "unit": "hours", "target": 8.0, "weight": 2, "baseline": 6.0},
        ],
    }


def _logs(specs, start="2026-01-01"):
    d0 = datetime.date.fromisoformat(start)
    out = []
    for i, (score, energy, mood, refl) in enumerate(specs):
        out.append({"date": (d0 + datetime.timedelta(days=i)).isoformat(),
                    "score": str(score), "energy": str(energy), "mood": str(mood),
                    "reflection": refl, "actual_0": "2", "target_0": "3.0",
                    "actual_1": "8", "target_1": "8.0"})
    return out


_STREAK0 = {"log_streak": 1, "momentum": 0, "longest_momentum": 0}


class CapacityTests(unittest.TestCase):
    def test_capacity_scales_with_energy(self):
        self.assertGreater(co.capacity_expected(5), co.capacity_expected(1))
        self.assertEqual(co.capacity_expected(5), 80.0)
        self.assertEqual(co.capacity_expected(1), 16.0)


class EnoughTests(unittest.TestCase):
    def test_grace_always_enough(self):
        ok, basis = co.did_enough(5, 0, grace=True)
        self.assertTrue(ok); self.assertEqual(basis, "grace")

    def test_depleted_but_present_is_enough(self):
        ok, basis = co.did_enough(2, 20)        # low energy, low score, but showed up
        self.assertTrue(ok); self.assertEqual(basis, "showed_up")

    def test_capacity_beats_expectation(self):
        ok, basis = co.did_enough(3, 60)        # energy 3 expects ~48, scored 60
        self.assertTrue(ok); self.assertEqual(basis, "capacity")

    def test_streak_protective(self):
        ok, basis = co.did_enough(4, 55, streak_alive=True)  # below capacity(64) but streak alive
        self.assertTrue(ok); self.assertEqual(basis, "streak")

    def test_genuinely_short(self):
        ok, basis = co.did_enough(5, 30)        # full energy, weak day, no streak
        self.assertFalse(ok); self.assertEqual(basis, "short")


class StanceTests(unittest.TestCase):
    def test_depleted_gives_grace(self):
        c = co.coaching_state(_profile(), _logs([(20, 1, 1, "")]), 1, 1, 20, _STREAK0)
        self.assertEqual(c["stance"], "grace")
        self.assertTrue(c["enough"])

    def test_high_energy_low_score_pushes(self):
        c = co.coaching_state(_profile(), _logs([(40, 5, 4, "")]), 5, 4, 40, _STREAK0)
        self.assertEqual(c["stance"], "push")
        self.assertEqual(c["intensity"], "hard")

    def test_great_day_celebrates(self):
        c = co.coaching_state(_profile(), _logs([(90, 4, 4, "")]), 4, 4, 90, _STREAK0)
        self.assertEqual(c["stance"], "celebrate")

    def test_grace_flag_forces_grace(self):
        c = co.coaching_state(_profile(), _logs([(90, 5, 5, "")]), 5, 5, 90, _STREAK0, grace=True)
        self.assertEqual(c["stance"], "grace")

    def test_recovery_mode_recovers(self):
        p = _profile(); p["recovery_mode"] = True
        c = co.coaching_state(p, _logs([(50, 3, 3, "")]), 3, 3, 50, _STREAK0)
        self.assertEqual(c["stance"], "recover")

    def test_reasons_and_headline_present(self):
        c = co.coaching_state(_profile(), _logs([(70, 3, 3, "")]), 3, 3, 70, _STREAK0)
        self.assertTrue(c["reasons"])
        self.assertTrue(c["headline"])
        self.assertIn("The Scholar", c["headline"])

    def test_shift_detected(self):
        p = _profile(); p["last_stance"] = "steady"
        c = co.coaching_state(p, _logs([(20, 1, 1, "")]), 1, 1, 20, _STREAK0)
        self.assertTrue(c["shift"])           # steady -> grace


class ProgressNoteTests(unittest.TestCase):
    def test_growth_detected(self):
        p = _profile()
        d0 = datetime.date(2026, 1, 1)
        logs = []
        for i in range(12):
            study = 1.0 if i < 6 else 4.0     # clear growth in second half
            logs.append({"date": (d0 + datetime.timedelta(days=i)).isoformat(),
                         "score": "70", "actual_0": str(study), "target_0": "3.0",
                         "actual_1": "8", "target_1": "8.0"})
        note = co.progress_note(p, logs)
        self.assertIsNotNone(note)
        self.assertIn("Study", note)

    def test_no_note_without_data(self):
        self.assertIsNone(co.progress_note(_profile(), _logs([(70, 3, 3, "")])))


class DensityTests(unittest.TestCase):
    def _logs(self, score, energy, mood, n=4):
        return [{"score": str(score), "energy": str(energy), "mood": str(mood)}
                for _ in range(n)]

    def test_manual_override_wins(self):
        p = _profile(); p["ui_mode"] = "calm"
        self.assertEqual(co.ui_density(p, self._logs(90, 5, 5))["mode"], "calm")
        self.assertFalse(co.ui_density(p, [])["auto"])

    def test_recovery_forces_calm(self):
        p = _profile(); p["ui_mode"] = "auto"; p["recovery_mode"] = True
        self.assertEqual(co.ui_density(p, self._logs(50, 3, 3))["mode"], "calm")

    def test_low_energy_is_calm(self):
        p = _profile(); p["ui_mode"] = "auto"
        self.assertEqual(co.ui_density(p, self._logs(50, 1, 1))["mode"], "calm")

    def test_thriving_is_rich(self):
        p = _profile(); p["ui_mode"] = "auto"
        d = co.ui_density(p, self._logs(85, 5, 5))
        self.assertEqual(d["mode"], "rich")
        self.assertIsNotNone(d["suggestion"])

    def test_middle_is_standard(self):
        p = _profile(); p["ui_mode"] = "auto"
        # decent but not a 3-day-good + high-energy run
        logs = self._logs(50, 3, 3)
        self.assertEqual(co.ui_density(p, logs)["mode"], "standard")

    def test_recent_state_defaults_neutral(self):
        e, m = co.recent_state([])
        self.assertEqual((e, m), (3.0, 3.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
