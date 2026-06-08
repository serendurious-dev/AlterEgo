"""Tests for the new intelligence/persona layer. python -m unittest -v"""

import os
import shutil
import tempfile
import datetime
import unittest

import features as fx
import alterego as ae


def _profile():
    return {
        "created": "2026-01-01", "reminder_hour": 20,
        "persona": {"name": "The Scholar", "voice": "firm",
                    "traits": ["disciplined", "focused"]},
        "chronotype": "night", "daemon_mode": "watchdog",
        "recovery_mode": False, "recovery_since": None,
        "badges": [], "personal_bests": {}, "letters_read": [], "archived_goals": [],
        "goals": [
            {"name": "Study", "unit": "hours", "target": 3.0, "weight": 3, "baseline": 1.0},
            {"name": "Sleep", "unit": "hours", "target": 8.0, "weight": 2, "baseline": 6.0},
        ],
    }


def _rows(spec, start="2026-01-01"):
    # spec: list of (score, [actuals], energy, mood, reflection)
    d0 = datetime.date.fromisoformat(start)
    out = []
    for i, (score, acts, energy, mood, refl) in enumerate(spec):
        row = {"date": (d0 + datetime.timedelta(days=i)).isoformat(),
               "score": str(score), "challenge": "x",
               "energy": str(energy), "mood": str(mood), "reflection": refl,
               "hash": fx.row_hash((d0 + datetime.timedelta(days=i)).isoformat(), str(score), "x")}
        for j, a in enumerate(acts):
            row[f"actual_{j}"] = str(a); row[f"target_{j}"] = "3.0" if j == 0 else "8.0"
        out.append(row)
    return out


class PersonaTests(unittest.TestCase):
    def test_voice_changes_message(self):
        p = _profile()
        firm = fx.persona_message(p, 90, "EXCELLENT")
        p["persona"]["voice"] = "warm"
        warm = fx.persona_message(p, 90, "EXCELLENT")
        self.assertNotEqual(firm, warm)
        self.assertIn("The Scholar", firm)

    def test_mode_overrides_tone(self):
        p = _profile()
        rec = fx.persona_message(p, 30, "ROCK BOTTOM", mode="recovery")
        self.assertIn("low", rec.lower())


class EmotionalModeTests(unittest.TestCase):
    def test_recovery(self):
        self.assertEqual(fx.emotional_mode(1, 1, 70), "recovery")
    def test_push(self):
        self.assertEqual(fx.emotional_mode(5, 3, 50), "push")
    def test_celebrate(self):
        self.assertEqual(fx.emotional_mode(3, 3, 85), "celebrate")
    def test_standard(self):
        self.assertEqual(fx.emotional_mode(3, 3, 65), "standard")


class SlumpPlateauTests(unittest.TestCase):
    def test_slump_true(self):
        logs = _rows([(30, [0, 0], 3, 3, ""), (20, [0, 0], 3, 3, ""), (10, [0, 0], 3, 3, "")])
        self.assertTrue(fx.detect_slump(logs))
    def test_slump_false(self):
        logs = _rows([(80, [3, 8], 3, 3, ""), (20, [0, 0], 3, 3, ""), (10, [0, 0], 3, 3, "")])
        self.assertFalse(fx.detect_slump(logs))
    def test_comeback(self):
        logs = _rows([(70, [3, 8], 3, 3, ""), (80, [3, 8], 3, 3, "")])
        self.assertTrue(fx.detect_comeback(logs))
    def test_plateau(self):
        logs = _rows([(65, [2, 8], 3, 3, "")] * 10)
        self.assertTrue(fx.detect_plateau(logs))
    def test_no_plateau_when_growing(self):
        logs = _rows([(s, [2, 8], 3, 3, "") for s in range(40, 100, 6)])
        self.assertFalse(fx.detect_plateau(logs))


class PersonalBestTests(unittest.TestCase):
    def test_new_pb_detected(self):
        p = _profile()
        fx.update_personal_bests(p, [2.0, 7.0])     # seeds
        new = fx.update_personal_bests(p, [4.0, 7.0])  # study beats prev
        self.assertIn("Study", new)
        self.assertNotIn("Sleep", new)
        self.assertEqual(p["personal_bests"]["Study"]["value"], 4.0)


class DayLabelTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(fx.day_label(95), "Locked In")
        self.assertEqual(fx.day_label(75), "Showed Up")
        self.assertEqual(fx.day_label(65), "Good Enough")
        self.assertEqual(fx.day_label(50), "Slipped")
        self.assertEqual(fx.day_label(20), "Ghost Day")
        self.assertEqual(fx.day_label(20, recovery_mode=True), "Rest Day")


class BadgeTests(unittest.TestCase):
    def test_perfect_and_first_week(self):
        p = _profile()
        spec = [(100, [3, 8], 4, 4, "")] + [(80, [3, 8], 4, 4, "")] * 6
        logs = _rows(spec)
        earned = fx.check_badges(p, logs)
        self.assertIn("perfect_day", earned)
        self.assertIn("first_week", earned)

    def test_comeback_badge(self):
        p = _profile()
        logs = _rows([(20, [0, 0], 3, 3, ""), (85, [3, 8], 4, 4, "")])
        self.assertIn("comeback", fx.check_badges(p, logs))

    def test_already_earned_not_repeated(self):
        p = _profile(); p["badges"] = ["perfect_day"]
        logs = _rows([(100, [3, 8], 4, 4, "")])
        self.assertNotIn("perfect_day", fx.check_badges(p, logs))


class BurnoutTests(unittest.TestCase):
    def test_reflection_keywords_trip_it(self):
        p = _profile()
        logs = _rows([(60, [2, 8], 3, 3, "")] * 3 +
                     [(60, [2, 8], 3, 3, "so exhausted"), (60, [2, 8], 3, 3, "i can't keep up")])
        risk, reason = fx.detect_burnout_risk(p, logs)
        self.assertTrue(risk)

    def test_quiet_when_fine(self):
        p = _profile()
        logs = _rows([(80, [3, 8], 3, 4, "good")] * 6)
        risk, _ = fx.detect_burnout_risk(p, logs)
        self.assertFalse(risk)


class HabitStackTests(unittest.TestCase):
    def test_stack_detected(self):
        p = _profile()
        # 14 days where hitting Sleep almost always coincides with hitting Study
        spec = [(80, [3, 8], 4, 4, "") for _ in range(14)]
        logs = _rows(spec)
        stacks = fx.habit_stack_suggestions(p, logs)
        self.assertTrue(any(s[2] >= 0.7 for s in stacks))


class IntegrityTests(unittest.TestCase):
    def test_tamper_detected(self):
        logs = _rows([(80, [3, 8], 3, 3, "")])
        self.assertEqual(fx.verify_log_integrity(logs), set())
        logs[0]["score"] = "99"           # tamper after hash was computed
        self.assertIn(logs[0]["date"], fx.verify_log_integrity(logs))


class CompareSelvesTests(unittest.TestCase):
    def test_gap_points(self):
        p = _profile()
        logs = _rows([(70, [2, 8], 3, 3, "")])
        cmp = fx.compare_selves(p, logs)
        self.assertEqual(cmp["gap_points"], 30.0)
        self.assertEqual(len(cmp["rows"]), 2)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self._cwd = os.getcwd(); os.chdir(self.dir)
    def tearDown(self):
        os.chdir(self._cwd); shutil.rmtree(self.dir, ignore_errors=True)

    def test_export_then_import_roundtrip(self):
        ae._save_profile(_profile())
        with open(ae.LOG_FILE, "w", encoding="utf-8") as f:
            f.write("date,score,challenge\n2026-01-01,80,x\n")
        zip_name = fx.export_backup(ae.PROFILE_FILE, ae.LOG_FILE)
        self.assertTrue(os.path.exists(zip_name))
        os.remove(ae.PROFILE_FILE)
        ok, _ = fx.import_backup(zip_name, ae.PROFILE_FILE)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(ae.PROFILE_FILE))


class ArchiveTests(unittest.TestCase):
    def test_archive_keeps_stats_and_removes_goal(self):
        p = _profile()
        logs = _rows([(80, [3, 8], 3, 3, ""), (80, [2, 8], 3, 3, "")])
        rec = fx.archive_goal(p, 0, logs)
        self.assertEqual(rec["name"], "Study")
        self.assertEqual(rec["days_tracked"], 2)
        self.assertEqual(len(p["goals"]), 1)
        self.assertEqual(p["archived_goals"][0]["name"], "Study")


class IntentionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self._cwd = os.getcwd(); os.chdir(self.dir)
    def tearDown(self):
        os.chdir(self._cwd); shutil.rmtree(self.dir, ignore_errors=True)

    def test_accuracy(self):
        p = _profile()
        wk = fx.week_key(datetime.date(2026, 1, 1))
        fx.save_intention(wk, {"Study": 10})
        logs = _rows([(80, [5, 8], 3, 3, ""), (80, [5, 8], 3, 3, "")], start="2026-01-01")
        rows = fx.intention_accuracy(p, logs, wk)
        self.assertEqual(rows[0]["goal"], "Study")
        self.assertEqual(rows[0]["actual"], 10.0)     # 5 + 5
        self.assertEqual(rows[0]["accuracy"], 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
