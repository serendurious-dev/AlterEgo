"""Tests. python -m unittest -v"""

import os
import csv
import json
import time
import shutil
import tempfile
import threading
import unittest

import osutil
import alterego as ae


class CoreLogicTests(unittest.TestCase):

    def setUp(self):
        self.profile = {
            "created": "2026-01-01",
            "reminder_hour": 20,
            "goals": [
                {"name": "Study",    "unit": "hours", "target": 3.0, "weight": 3, "baseline": 1.0},
                {"name": "Sleep",    "unit": "hours", "target": 8.0, "weight": 2, "baseline": 6.0},
                {"name": "Exercise", "unit": "times", "target": 4.0, "weight": 2, "baseline": 2.0},
            ],
        }

    def test_perfect_day_scores_100(self):
        _, score, _ = ae.think(self.profile, [3.0, 8.0, 4.0])
        self.assertEqual(score, 100.0)

    def test_zero_day_scores_0(self):
        _, score, _ = ae.think(self.profile, [0.0, 0.0, 0.0])
        self.assertEqual(score, 0.0)

    def test_gap_formula_and_score(self):
        # Study 2/3 (gap 1*3=3), Sleep 1/8 (gap 7*2=14), Exercise 2/4 (gap 2*2=4)
        gaps, score, weakest = ae.think(self.profile, [2.0, 1.0, 2.0])
        self.assertEqual(gaps, [3.0, 14.0, 4.0])
        # possible = 9+16+8 = 33 ; score = (1 - 21/33)*100 = 36.4
        self.assertEqual(score, 36.4)
        self.assertEqual(weakest, 1)            # Sleep has the largest gap

    def test_overperformance_does_not_create_negative_gap(self):
        gaps, score, _ = ae.think(self.profile, [10.0, 10.0, 10.0])
        self.assertTrue(all(g == 0 for g in gaps))
        self.assertEqual(score, 100.0)

    def test_score_is_clamped_to_0_100(self):
        for actuals in ([0, 0, 0], [3, 8, 4], [100, 100, 100]):
            _, score, _ = ae.think(self.profile, actuals)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_progress_bar_bounds(self):
        self.assertIn("100%", ae._progress_bar(3, 3))
        self.assertIn("50%", ae._progress_bar(1.5, 3))
        self.assertIn("0%", ae._progress_bar(0, 3))
        # Over-target clamps to 100 %
        self.assertIn("100%", ae._progress_bar(99, 3))


class StreakTests(unittest.TestCase):

    @staticmethod
    def _rows(scores, start="2026-01-01"):
        import datetime
        d0 = datetime.date.fromisoformat(start)
        out = []
        for i, s in enumerate(scores):
            out.append({"date": (d0 + datetime.timedelta(days=i)).isoformat(),
                        "score": str(s)})
        return out

    def test_empty(self):
        self.assertEqual(ae.compute_streaks([]),
                         {"log_streak": 0, "momentum": 0, "longest_momentum": 0})

    def test_consecutive_logging_streak(self):
        s = ae.compute_streaks(self._rows([80, 80, 80, 80]))
        self.assertEqual(s["log_streak"], 4)

    def test_momentum_breaks_on_low_score(self):
        # ...good, good, BAD, good, good  -> current momentum 2, longest 2
        s = ae.compute_streaks(self._rows([90, 90, 30, 90, 90]))
        self.assertEqual(s["momentum"], 2)
        self.assertEqual(s["longest_momentum"], 2)

    def test_gap_in_dates_resets_log_streak(self):
        rows = self._rows([80, 80])
        rows.append({"date": "2026-02-01", "score": "80"})   # non-consecutive
        s = ae.compute_streaks(rows)
        self.assertEqual(s["log_streak"], 1)


class OSPrimitiveTests(unittest.TestCase):
    # locking + atomic writes

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "data.txt")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_atomic_write_roundtrip(self):
        osutil.atomic_write_text(self.path, "hello world")
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "hello world")

    def test_atomic_write_leaves_no_temp_files(self):
        osutil.atomic_write_text(self.path, "x")
        leftovers = [f for f in os.listdir(self.dir) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_filelock_is_mutually_exclusive(self):
        # 8 threads * 50 increments under the lock -> must end at 400
        counter_file = os.path.join(self.dir, "counter.txt")
        osutil.atomic_write_text(counter_file, "0")

        def increment():
            for _ in range(50):
                with osutil.FileLock(counter_file, timeout=20):
                    with open(counter_file, encoding="utf-8") as f:
                        val = int(f.read().strip())
                    osutil.atomic_write_text(counter_file, str(val + 1))

        threads = [threading.Thread(target=increment) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with open(counter_file, encoding="utf-8") as f:
            final = int(f.read().strip())
        self.assertEqual(final, 400)

    def test_filelock_blocks_second_holder(self):
        lock_a = osutil.FileLock(self.path, timeout=0.5)
        lock_a.acquire()
        try:
            with self.assertRaises(TimeoutError):
                osutil.FileLock(self.path, timeout=0.5).acquire()
        finally:
            lock_a.release()


class PersistenceTests(unittest.TestCase):
    # uses a temp cwd so we don't touch real data files

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._cwd = os.getcwd()
        os.chdir(self.dir)

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_save_and_load_profile(self):
        profile = {"created": "2026-01-01", "reminder_hour": 20, "goals": []}
        ae._save_profile(profile)
        self.assertEqual(ae._load_profile(), profile)

    def test_corrupt_profile_is_quarantined(self):
        with open(ae.PROFILE_FILE, "w", encoding="utf-8") as f:
            f.write("{ this is not valid json ")
        result = ae._load_profile_safe()
        self.assertIsNone(result)
        self.assertTrue(os.path.exists(ae.PROFILE_FILE + ".corrupt"))

    def test_log_entry_and_read_roundtrip(self):
        profile = {
            "created": "2026-01-01", "reminder_hour": 20,
            "goals": [{"name": "G", "unit": "u", "target": 1.0, "weight": 1, "baseline": 0}],
        }
        gaps, score, _ = ae.think(profile, [0.5])
        ae._log_entry("2026-01-01", [0.5], gaps, score, "do better", profile)
        rows = ae._read_logs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-01-01")
        self.assertTrue(ae._already_logged("2026-01-01"))

    def test_read_logs_skips_malformed_rows(self):
        with open(ae.LOG_FILE, "w", newline="", encoding="utf-8") as f:
            f.write("date,score,challenge\n")
            f.write("2026-01-01,80,ok\n")
            f.write(",,\n")                       # malformed row
            f.write("2026-01-02,90,ok\n")
        self.assertEqual(len(ae._read_logs()), 2)

    def test_read_logs_drops_non_numeric_scores(self):
        # a hand-edited score must not poison every float(r["score"]) downstream
        with open(ae.LOG_FILE, "w", newline="", encoding="utf-8") as f:
            f.write("date,score,challenge\n")
            f.write("2026-01-01,80,ok\n")
            f.write("2026-01-02,NOPE,bad\n")
            f.write("2026-01-03,90,ok\n")
        rows = ae._read_logs()
        self.assertEqual(len(rows), 2)
        # the analytics should run clean on the filtered data
        ae.compute_streaks(rows)

    def test_think_handles_empty_goals(self):
        profile = {"created": "2026-01-01", "reminder_hour": 20, "goals": []}
        gaps, score, weakest = ae.think(profile, [])
        self.assertEqual(gaps, [])
        self.assertEqual(score, 100.0)
        self.assertEqual(weakest, 0)


class ObstacleAndChallengeTests(unittest.TestCase):

    def setUp(self):
        self.profile = {
            "created": "2026-01-01", "reminder_hour": 20,
            "goals": [
                {"name": "Study", "unit": "hours", "target": 3.0, "weight": 3, "baseline": 1.0},
                {"name": "Sleep", "unit": "hours", "target": 8.0, "weight": 2, "baseline": 6.0},
            ],
        }

    def test_obstacle_specific_challenge_used(self):
        ch = ae.micro_challenge(self.profile, [1.0, 8.0], 0, "2026-01-01",
                                obstacle="Procrastination / phone")
        self.assertIn("phone", ch.lower())
        self.assertIn("Study", ch)

    def test_generic_challenge_when_no_obstacle(self):
        ch = ae.micro_challenge(self.profile, [1.0, 8.0], 0, "2026-01-01", obstacle=None)
        self.assertIn("Study", ch)
        # None of the obstacle-specific phrasings should leak in
        self.assertNotIn("peak-energy", ch)

    def test_unknown_obstacle_falls_back_to_generic(self):
        ch = ae.micro_challenge(self.profile, [1.0, 8.0], 0, "2026-01-01", obstacle="Other")
        self.assertIn("Study", ch)

    def test_dominant_obstacle(self):
        logs = [
            {"date": "2026-01-01", "score": "40", "obstacle_0": "Forgot"},
            {"date": "2026-01-02", "score": "40", "obstacle_0": "Forgot"},
            {"date": "2026-01-03", "score": "40", "obstacle_0": "Too tired / low energy"},
        ]
        self.assertEqual(ae.dominant_obstacle(logs, 0), "Forgot")

    def test_dominant_obstacle_none_when_empty(self):
        logs = [{"date": "2026-01-01", "score": "90", "obstacle_0": "None"}]
        self.assertIsNone(ae.dominant_obstacle(logs, 0))


class InsightTests(unittest.TestCase):

    def setUp(self):
        self.profile = {
            "created": "2026-01-01", "reminder_hour": 20,
            "goals": [
                {"name": "Study", "unit": "hours", "target": 3.0, "weight": 3, "baseline": 1.0},
                {"name": "Sleep", "unit": "hours", "target": 8.0, "weight": 2, "baseline": 6.0},
            ],
        }

    def test_insufficient_data(self):
        logs = [{"date": "2026-01-01", "score": "80"}]
        self.assertFalse(ae.insights(self.profile, logs)["enough_data"])

    def test_top_lever_detected(self):
        # study hits track scores 1:1, so its correlation should be high
        import datetime
        logs = []
        d0 = datetime.date(2026, 1, 1)
        for i in range(8):
            study = 3.0 if i % 2 == 0 else 0.0
            score = 90 if study >= 3.0 else 30
            logs.append({
                "date": (d0 + datetime.timedelta(days=i)).isoformat(),
                "score": str(score),
                "actual_0": str(study), "target_0": "3.0",
                "actual_1": "8.0", "target_1": "8.0",      # sleep always met
                "obstacle_0": "" if study >= 3 else "Forgot", "obstacle_1": "",
            })
        data = ae.insights(self.profile, logs)
        self.assertTrue(data["enough_data"])
        self.assertIsNotNone(data["top_lever"])
        self.assertEqual(data["top_lever"]["goal"], "Study")
        self.assertGreater(data["top_lever"]["corr"], 0.5)


class NotifyTests(unittest.TestCase):

    def test_notify_fallback_writes_stderr(self):
        # fake out the platform checks, the stderr fallback should fire
        import io, contextlib, unittest.mock as mock
        buf = io.StringIO()
        with mock.patch.object(osutil.os, "name", "posix"), \
             mock.patch.object(osutil.sys, "platform", "linux"), \
             mock.patch.object(osutil.shutil, "which", return_value=None), \
             contextlib.redirect_stderr(buf):
            osutil.notify("Title", "Body", blocking=True)
        self.assertIn("Title", buf.getvalue())
        self.assertIn("Body", buf.getvalue())


class RetentionTests(unittest.TestCase):
    # streak freezes + express check-in, in an isolated cwd
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self._cwd = os.getcwd(); os.chdir(self.dir)
        self.profile = {
            "created": "2026-05-01", "reminder_hour": 20,
            "persona": {"name": "Max", "voice": "warm", "traits": []},
            "chronotype": "night", "daemon_mode": "silent", "recovery_mode": False,
            "recovery_since": None, "badges": [], "personal_bests": {},
            "letters_read": [], "archived_goals": [], "last_stance": None, "xp": 0,
            "theme": "Ocean", "streak_freezes": 1, "freeze_dates": [],
            "goals": [{"name": "Study", "unit": "hours", "target": 3.0,
                       "weight": 3, "baseline": 1.0, "why": ""}],
        }
        ae._save_profile(self.profile)

    def tearDown(self):
        os.chdir(self._cwd); shutil.rmtree(self.dir, ignore_errors=True)

    def test_freeze_spent_on_one_day_gap(self):
        for d in ("2026-05-01", "2026-05-02"):
            g, s, _ = ae.think(self.profile, [3])
            ae._log_entry(d, [3], g, s, "x", self.profile, ["None"], label="Showed Up")
        froze = ae._manage_freezes(self.profile, "2026-05-04")    # missed the 3rd
        self.assertEqual(froze, "2026-05-03")
        self.assertEqual(self.profile["streak_freezes"], 0)

    def test_earn_freeze_on_7_day_momentum(self):
        self.profile["streak_freezes"] = 0
        self.assertTrue(ae._earn_freeze(self.profile, 7))
        self.assertEqual(self.profile["streak_freezes"], 1)
        self.assertFalse(ae._earn_freeze(self.profile, 5))       # not a multiple of 7

    def test_express_logs_a_day(self):
        res = ae.express_apply(self.profile, 5)
        self.assertEqual(res["score"], 100.0)
        self.assertTrue(ae._already_logged(datetime_today()))

    def test_effective_streak_counts_frozen_day(self):
        for d in ("2026-05-01", "2026-05-02", "2026-05-04"):
            g, s, _ = ae.think(self.profile, [3])
            ae._log_entry(d, [3], g, s, "x", self.profile, ["None"], label="Showed Up")
        self.profile["freeze_dates"] = ["2026-05-03"]
        self.assertEqual(ae.effective_streak(self.profile, ae._read_logs()), 4)

    def test_doctor_runs_clean(self):
        # the self-diagnostic should pass on a healthy install and leave no mess
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = ae.doctor()
        self.assertTrue(ok)
        self.assertIn("mutual exclusion", buf.getvalue())
        self.assertEqual([x for x in os.listdir(".") if x.endswith(".tmp")], [])


def datetime_today():
    import datetime
    return datetime.date.today().isoformat()


if __name__ == "__main__":
    unittest.main(verbosity=2)
