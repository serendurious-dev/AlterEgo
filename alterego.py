"""AlterEgo Agent. Main module: terminal app, menu, CLI, reminder daemon."""

import os
import io
import sys
import csv
import json
import time
import signal
import argparse
import datetime
import statistics
import subprocess

import osutil

# pull the helper functions into this namespace so the GUI, CLI and tests can
# all reach them as alterego.something()
from features import (
    get_persona, persona_message, emotional_mode,
    detect_slump, detect_comeback, recovery_targets,
    update_personal_bests, detect_plateau, day_label, chronotype_advice,
    smart_greeting, check_badges, badge_label, BADGES,
    detect_burnout_risk, habit_stack_suggestions, compare_selves,
    behavioral_patterns, generate_weekly_letter, write_weekly_letter,
    latest_letter, export_scorecard, audit_state, verify_log_integrity,
    export_backup, import_backup, plot_heatmap, row_hash, archive_goal,
    load_intentions, save_intention, week_key, intention_accuracy,
    VOICES, CHRONOTYPES, GOAL_TEMPLATES,
)
from coaching import (coaching_state, did_enough, capacity_expected, progress_note,
                      ui_density, recent_state)
from wisdom import (principle_for_state, principle_of_the_day, growth_season,
                    dual_voice, identity_line)
from game import (
    xp_for_checkin, level_from_xp, title_for_level, xp_bar, combo_multiplier,
    daily_draw, monster_line, joke_of_the_day, fortune_of_the_day, random_joke,
    quote_of_the_day, avatar_for_level,
    SCREEN_UNLOCKS, is_unlocked, newly_unlocked, next_unlock,
    protected_streak, days_since_last, comeback_message, next_milestone,
)

PROFILE_FILE  = "alterego_profile.json"
LOG_FILE      = "alterego_log.csv"
EVENT_LOG     = "alterego_events.log"
CHART_FILE    = "alterego_trend.png"

DAEMON_PID    = "alterego_daemon.pid"
DAEMON_STATUS = "alterego_daemon.status"
DAEMON_STOP   = "alterego_daemon.stop"
DAEMON_LOG    = "alterego_daemon.log"

DEFAULT_REMINDER_HOUR = 20    # 8 pm
DAEMON_INTERVAL       = 60    # daemon loop tick
HEARTBEAT_TTL         = 180   # daemon "alive" cutoff

log = osutil.get_logger("alterego", EVENT_LOG)

BANNER = """
============================================================
            A L T E R E G O   A G E N T
   meet the version of you that actually shows up
============================================================
"""


# little input/output helpers

def _clear():
    os.system("cls" if os.name == "nt" else "clear")


def _divider(char="-", width=60):
    return char * width


def _input_float(prompt, lo=0.0, hi=None):
    while True:
        try:
            v = float(input(prompt))
            if v < lo:
                print(f"    ! Must be >= {lo}")
                continue
            if hi is not None and v > hi:
                print(f"    ! Must be <= {hi}")
                continue
            return v
        except ValueError:
            print("    ! Please enter a number.")


def _input_int(prompt, lo=1, hi=None):
    while True:
        try:
            v = int(input(prompt))
            if v < lo:
                print(f"    ! Must be >= {lo}")
                continue
            if hi is not None and v > hi:
                print(f"    ! Must be <= {hi}")
                continue
            return v
        except ValueError:
            print("    ! Please enter a whole number.")


def _progress_bar(value, target, width=10):
    # text progress bar like [#####-----] 50%
    pct = 100.0 if target <= 0 else max(0.0, min(100.0, value / target * 100.0))
    filled = int(round(pct / 100.0 * width))
    return "[" + "#" * filled + "-" * (width - filled) + f"] {pct:5.0f}%"


# profile + log persistence

def _save_profile(profile):
    # locked + atomic
    with osutil.FileLock(PROFILE_FILE):
        osutil.atomic_write_text(PROFILE_FILE, json.dumps(profile, indent=2))


def _load_profile():
    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_profile_safe():
    # if the json is busted, rename it out of the way and start over
    try:
        return _load_profile()
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        backup = PROFILE_FILE + ".corrupt"
        try:
            os.replace(PROFILE_FILE, backup)
        except OSError:
            pass
        log.error("Corrupt profile quarantined to %s: %s", backup, exc)
        print(f"\n  ! Profile file was corrupted. Backed up to '{backup}'.")
        print("    A new profile will be created.\n")
        return None


def _migrate_profile(profile):
    # fill in any fields added after this profile was first created
    defaults = {
        "persona": {"name": "The Scholar", "voice": "firm",
                    "traits": ["disciplined", "focused", "steady"]},
        "chronotype": "morning", "daemon_mode": "watchdog",
        "recovery_mode": False, "recovery_since": None,
        "badges": [], "personal_bests": {}, "letters_read": [],
        "archived_goals": [], "xp": 0, "last_stance": None, "theme": "Ocean",
        "streak_freezes": 0, "freeze_dates": [], "ui_mode": "auto", "identity": "",
    }
    changed = False
    for k, v in defaults.items():
        if k not in profile:
            profile[k] = v
            changed = True
    return changed


def _log_entry(date, actuals, gaps, score, challenge, profile, obstacles=None,
               energy="", mood="", reflection="", focus_sessions="", label="", grace=""):
    # rewrite the whole csv each time. log is small, this way we get atomic
    # writes for free and new columns slot in without breaking old files.
    goals = profile["goals"]
    n = len(goals)
    obstacles = obstacles or [""] * n

    fieldnames = ["date", "score", "challenge", "energy", "mood",
                  "reflection", "focus_sessions", "day_label", "grace", "hash"]
    for i in range(n):
        fieldnames += [f"goal_{i}", f"target_{i}", f"actual_{i}", f"gap_{i}", f"obstacle_{i}"]

    row = {"date": date, "score": score, "challenge": challenge,
           "energy": energy, "mood": mood, "reflection": reflection,
           "focus_sessions": focus_sessions, "day_label": label, "grace": grace,
           "hash": row_hash(date, score, challenge)}
    for i, g in enumerate(goals):
        row[f"goal_{i}"]     = g["name"]
        row[f"target_{i}"]   = g["target"]
        row[f"actual_{i}"]   = actuals[i]
        row[f"gap_{i}"]      = round(gaps[i], 4)
        row[f"obstacle_{i}"] = obstacles[i] or ""

    with osutil.FileLock(LOG_FILE):
        existing = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", newline="", encoding="utf-8") as f:
                existing = [r for r in csv.DictReader(f) if r.get("date")]
        all_fields = list(fieldnames)
        for r in existing:                       # preserve any legacy-only columns
            for k in r:
                if k not in all_fields:
                    all_fields.append(k)
        existing.append(row)

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=all_fields, restval="",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing)
        osutil.atomic_write_text(LOG_FILE, buf.getvalue())
    log.info("Check-in logged for %s: score=%s", date, score)


def _read_logs():
    # only return rows with a date and a numeric score. this single gate keeps
    # every downstream float(r["score"]) from crashing on a hand-edited file.
    if not os.path.exists(LOG_FILE):
        return []
    rows = []
    try:
        with open(LOG_FILE, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not row.get("date") or not row.get("score"):
                    continue
                try:
                    float(row["score"])
                except (TypeError, ValueError):
                    continue
                rows.append(row)
    except OSError as exc:
        log.error("Failed reading log: %s", exc)
    return rows


def _already_logged(date):
    return any(r.get("date") == date for r in _read_logs())


def _safe_date(row):
    try:
        return datetime.date.fromisoformat(row["date"])
    except (ValueError, KeyError):
        return None


# phase 1: setup

def setup_persona():
    # ask the user to name and shape their ideal self
    print("\n  " + _divider())
    print("  Build your AlterEgo (your ideal self)")
    print("  " + _divider())
    name = input("  Name your AlterEgo (e.g. The Scholar): ").strip() or "The Scholar"
    print("  Three words that describe them (comma separated):")
    raw = input("  e.g. disciplined, focused, calm: ").strip()
    traits = [t.strip() for t in raw.split(",") if t.strip()][:3] or ["disciplined"]
    print("  Voice:  1) firm   2) warm   3) fierce")
    v = _input_int("  Choose voice: ", lo=1, hi=3)
    voice = VOICES[v - 1]
    print("  When do you work best?  1) morning  2) afternoon  3) night")
    c = _input_int("  Choose: ", lo=1, hi=3)
    chronotype = CHRONOTYPES[c - 1]
    return {"name": name, "voice": voice, "traits": traits}, chronotype


def setup_profile():
    # first run, ask for 3 goals + persona + reminder hour
    print("  First launch detected. Let's build your AlterEgo profile.")
    print("  You will define 3 core life goals.\n")

    goals = []
    for i in range(1, 4):
        print(_divider())
        print(f"  Goal {i}")
        print(_divider())
        name    = input("  Goal description   : ").strip() or f"Goal {i}"
        unit    = input("  Unit (hours/times) : ").strip() or "units"
        target  = _input_float(f"  Daily target ({unit}): ", lo=0.1)
        weight  = _input_int(  "  Priority weight   (1=low  2=medium  3=high): ",
                               lo=1, hi=3)
        baseline = _input_float(
            f"  Current baseline   (0 - {target} {unit}): ",
            lo=0, hi=target
        )
        why = input("  Why does this matter to you? (optional): ").strip()
        goals.append({
            "name": name, "unit": unit, "target": target,
            "weight": weight, "baseline": baseline, "why": why,
        })
        print()

    persona, chronotype = setup_persona()

    print("\n" + _divider())
    print("  One last thing. Finish this sentence (optional):")
    identity = input("  I am becoming someone who... ").strip()

    print(_divider())
    reminder_hour = _input_int(
        "  Daily reminder hour (0-23, e.g. 20 for 8 PM): ", lo=0, hi=23)

    profile = {
        "created":       datetime.date.today().isoformat(),
        "reminder_hour": reminder_hour,
        "goals":         goals,
        "persona":       persona,
        "chronotype":    chronotype,
        "daemon_mode":   "watchdog",
        "recovery_mode": False,
        "recovery_since": None,
        "badges":        [],
        "personal_bests": {},
        "letters_read":  [],
        "archived_goals": [],
        "xp":            0,
        "last_stance":   None,
        "theme":         "Ocean",
        "streak_freezes": 0,
        "freeze_dates":  [],
        "ui_mode":       "auto",
        "identity":      identity,
    }
    _save_profile(profile)
    log.info("New profile created with %d goals, persona '%s'", len(goals), persona["name"])
    print(f"\n  Profile saved. {persona['name']} is watching now. Let's begin.\n")
    return profile


def manage_goals(profile):
    while True:
        print("\n  " + _divider())
        print("  YOUR GOALS")
        print("  " + _divider())
        for i, g in enumerate(profile["goals"], 1):
            print(f"  {i}. {g['name']:<24} target {g['target']} {g['unit']}"
                  f"  (weight {g['weight']})")
        print(f"  Reminder hour: {profile.get('reminder_hour', DEFAULT_REMINDER_HOUR)}:00")
        for a in profile.get("archived_goals", []):
            print(f"  (archived) {a['name']} - avg {a['lifetime_avg']}, "
                  f"last active {a['last_active']}")
        print("  " + _divider())
        print("  Number = edit goal, 'r' = reminder hour, 'a' = archive a goal, 0 = back.")
        raw = input("  Choice: ").strip().lower()

        if raw == "0":
            return
        if raw == "r":
            profile["reminder_hour"] = _input_int("  New reminder hour (0-23): ", lo=0, hi=23)
            _save_profile(profile)
            print("  Reminder hour updated.")
            continue
        if raw == "a":
            if len(profile["goals"]) <= 1:
                print("  ! Keep at least one goal.")
                continue
            idx = _input_int("  Archive which goal number? ", lo=1, hi=len(profile["goals"]))
            rec = archive_goal(profile, idx - 1, _read_logs())
            _save_profile(profile)
            print(f"  Archived {rec['name']} (kept its stats).")
            continue
        if not raw.isdigit() or not (1 <= int(raw) <= len(profile["goals"])):
            print("  ! Invalid choice.")
            continue

        g = profile["goals"][int(raw) - 1]
        print(f"\n  Editing: {g['name']}")
        g["target"] = _input_float(f"  New daily target ({g['unit']}) "
                                   f"[current {g['target']}]: ", lo=0.1)
        g["weight"] = _input_int("  New priority weight (1-3) "
                                 f"[current {g['weight']}]: ", lo=1, hi=3)
        new_why = input(f"  Why it matters [current: {g.get('why', '') or 'none'}]: ").strip()
        if new_why:
            g["why"] = new_why
        _save_profile(profile)
        print("  Goal updated.")


# phase 2: observe (today's numbers + obstacles)

def _ask_obstacle(goal_name):
    # only called for goals you missed
    print(f"    Why did you miss '{goal_name}'?")
    for idx, obs in enumerate(OBSTACLES):
        print(f"      {idx}. {obs}")
    choice = _input_int("      Choose: ", lo=0, hi=len(OBSTACLES) - 1)
    return OBSTACLES[choice]


def ask_energy_mood():
    # quick emotional check-in before the numbers
    print("\n  How are you feeling today? Be honest, your AlterEgo adjusts.")
    energy = _input_int("  Energy (1-5): ", lo=1, hi=5)
    mood   = _input_int("  Mood   (1-5): ", lo=1, hi=5)
    return energy, mood


def ask_reflection():
    # optional one-line journal
    text = input("\n  One thing you noticed about yourself today (Enter to skip): ").strip()
    return text


def observe(profile, targets=None):
    # targets lets recovery mode score against easier numbers
    today = datetime.date.today().isoformat()
    print(f"\n  Daily Check-In  ({today})")
    print(_divider())
    actuals, obstacles = [], []
    for i, goal in enumerate(profile["goals"]):
        tgt = targets[i] if targets else goal["target"]
        v = _input_float(
            f"  {goal['name']}  (target: {tgt} {goal['unit']}): ", lo=0)
        actuals.append(v)
        # only ask "why" if the goal was actually missed
        obstacles.append(_ask_obstacle(goal["name"]) if v < tgt else "None")
    return today, actuals, obstacles


# phase 3: think (gap math)

def think(profile, actuals):
    # gap = how far short, weighted; score = (1 - total_gap/max_possible) * 100
    goals          = profile["goals"]
    if not goals:                       # nothing to score
        return [], 100.0, 0
    gaps           = []
    total_possible = 0.0

    for i, goal in enumerate(goals):
        gap = max(0.0, goal["target"] - actuals[i]) * goal["weight"]
        gaps.append(gap)
        total_possible += goal["target"] * goal["weight"]

    total_gap = sum(gaps)
    score = (1.0 - total_gap / total_possible) * 100.0 if total_possible > 0 else 100.0
    score = max(0.0, min(100.0, round(score, 1)))

    weakest_idx = gaps.index(max(gaps))
    return gaps, score, weakest_idx


# phase 4: act (score, message, challenge)

# pool used when we don't know why the user missed it
_MICRO_CHALLENGES = [
    "Do {step} {unit} of {goal} before checking your phone.",
    "Set a 25 minute timer for {goal} right after you wake up.",
    "Write down your plan for {goal} on paper tonight.",
    "Cut one distraction and use that time for {goal}.",
    "Tell a friend you will do {step} {unit} of {goal} tomorrow.",
    "Get everything ready tonight so {goal} is easy tomorrow.",
    "Add {step} {unit} of {goal} to your calendar now.",
]

# "why did you miss it" menu; "None"/"" = nothing chosen
OBSTACLES = [
    "None",
    "Procrastination / phone",
    "Too tired / low energy",
    "No time / too busy",
    "Forgot",
    "Social / interrupted",
    "Other",
]

# used when we know the obstacle: pick a fix for that one
_OBSTACLE_CHALLENGES = {
    "Procrastination / phone": "Put your phone in another room and do {step} {unit} of {goal} first.",
    "Too tired / low energy":  "Try {goal} in the morning tomorrow, when you have more energy.",
    "No time / too busy":      "Add {step} {unit} of {goal} to your calendar as a fixed time.",
    "Forgot":                  "Set a phone alarm for {goal} so you don't forget tomorrow.",
    "Social / interrupted":    "Tell people you are busy for {step} {unit} while doing {goal}.",
}


def dominant_obstacle(logs, goal_index, window=14):
    # most-mentioned obstacle for this goal over the last `window` days
    key = f"obstacle_{goal_index}"
    counts = {}
    for r in logs[-window:]:
        obs = (r.get(key) or "").strip()
        if obs and obs != "None":
            counts[obs] = counts.get(obs, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def score_tone(score):
    # GUI also calls this so no prints
    if score >= 80:
        return "EXCELLENT", "Nice, you matched your AlterEgo today. Keep it up."
    if score >= 60:
        return "KEEP GOING", "Pretty good day. A few goals slipped, you are close."
    if score >= 40:
        return "WAKE UP", "You missed too much today. Try to fix one thing tomorrow."
    return "ROCK BOTTOM", "Bad day. Pick the smallest goal and just do that tomorrow."


def micro_challenge(profile, actuals, weakest_idx, date, obstacle=None):
    # known obstacle -> matching template, else pick a generic one
    # (deterministic on date+goal so it doesn't change on re-render)
    weakest  = profile["goals"][weakest_idx]
    actual_w = actuals[weakest_idx]
    step = round(max(actual_w * 1.25, weakest["target"] * 0.66), 2)
    step = min(step, weakest["target"])

    template = _OBSTACLE_CHALLENGES.get((obstacle or "").strip())
    if template is None:
        ci = abs(hash(date + weakest["name"])) % len(_MICRO_CHALLENGES)
        template = _MICRO_CHALLENGES[ci]
    return template.format(goal=weakest["name"], step=step, unit=weakest["unit"])


def act(profile, actuals, gaps, score, weakest_idx, date, streaks,
        obstacles=None, mode="standard", targets=None, coach=None, game_info=None):
    goals    = profile["goals"]
    weakest  = goals[weakest_idx]
    actual_w = actuals[weakest_idx]
    targets  = targets or [g["target"] for g in goals]

    obstacle  = obstacles[weakest_idx] if obstacles else None
    challenge = micro_challenge(profile, actuals, weakest_idx, date, obstacle)
    label = day_label(score, profile.get("recovery_mode"))
    pe = get_persona(profile)

    print("\n" + _divider("="))
    print(f"  ALTEREGO SCORE:  {score} / 100   [{label}]")
    print(_divider("="))

    print("\n  Goal Breakdown:")
    for i, g in enumerate(goals):
        bar = _progress_bar(actuals[i], targets[i])
        print(f"    {g['name']:<22} {bar}   {actuals[i]}/{targets[i]} {g['unit']}")

    # the coaching brain: how your AlterEgo is reading today, and why
    if coach:
        print(f"\n  {pe['name']} (stance: {coach['stance']}):")
        print(f"  {coach['headline']}")
        if coach.get("shift"):
            print("  (something changed in how I'm treating you today)")
        print("\n  Why:")
        for r in coach["reasons"]:
            print(f"   - {r}")
        if coach["enough"]:
            print("\n  Verdict: that was enough for today. Rest easy.")
    else:
        tone, _ = score_tone(score)
        print(f"\n  {pe['name']} says:")
        print(f"  {persona_message(profile, score, tone, mode)}")

    # the two voices: the teacher who pushes, the friend who holds you
    stance = coach["stance"] if coach else "standard"
    teacher, friend = dual_voice(profile, score, stance, date)
    print(f"\n  The teacher:  {teacher}")
    print(f"  The friend:   {friend}")
    il = identity_line(profile)
    if il:
        print(f"  {il}")

    print(f"\n  Weakest Area : {weakest['name']}")
    print(f"  AlterEgo did : {targets[weakest_idx]} {weakest['unit']}"
          f"   |   You did: {actual_w} {weakest['unit']}")
    if weakest.get("why"):
        print(f"  Remember why : {weakest['why']}")
    print(f"\n  Challenge for Tomorrow:")
    print(f"  -> {challenge}")

    advice = chronotype_advice(profile, weakest["name"])
    if advice:
        print(f"  Tip: {advice}")

    print(f"\n  Logging Streak : {streaks['log_streak']} day(s) in a row")

    # the fun layer: monster, loot, XP, level-up
    if game_info:
        print("\n  " + _divider("-"))
        print(f"  {game_info['monster']}")
        d = game_info["draw"]
        print(f"  Daily Draw: {d['label']} - {d['flavor']}"
              + (f" (+{d['xp']} XP)" if d["xp"] else ""))
        if game_info["combo"] > 1.0:
            print(f"  Combo x{game_info['combo']} active!")
        print(f"  +{game_info['xp_gained']} XP   {xp_bar(game_info['xp_after'])}")
        if game_info["leveled_up"]:
            print(f"  *** LEVEL UP! You are now Level {game_info['level_after']} "
                  f"({title_for_level(game_info['level_after'])})! ***")
    print(_divider("=") + "\n")

    return challenge, label


# phase 5: evolve (raise targets you keep hitting)

def evolve_apply(profile):
    # last 7 days: >=80% hit -> +10% target, <=40% -> flag for new strategy.
    # returns the per-goal results so the GUI can render its own card.
    logs = _read_logs()
    if len(logs) < 7:
        return []

    last7   = logs[-7:]
    results = []
    changed = False

    for i, goal in enumerate(profile["goals"]):
        key_a, key_t = f"actual_{i}", f"target_{i}"
        actuals = [float(r[key_a]) for r in last7 if key_a in r]
        targets = [float(r[key_t]) for r in last7 if key_t in r]
        if not actuals:
            continue

        hits = sum(1 for a, t in zip(actuals, targets) if a >= t)
        rate = hits / len(actuals)
        entry = {"goal": goal["name"], "rate": rate, "unit": goal["unit"],
                 "old": goal["target"]}

        if rate >= 0.80:
            new_target = round(goal["target"] * 1.10, 2)
            goal["target"] = new_target
            entry.update(action="raised", new=new_target)
            changed = True
        elif rate <= 0.40:
            entry.update(action="restructure", new=goal["target"])
        else:
            entry.update(action="ontrack", new=goal["target"])
        results.append(entry)

    if changed:
        _save_profile(profile)
        log.info("Weekly evolution raised targets")
    return results


def evolve(profile):
    results = evolve_apply(profile)
    if not results:
        return

    print("\n" + _divider("-"))
    print("  WEEKLY EVOLUTION ANALYSIS")
    print(_divider("-"))
    changed = False
    for r in results:
        if r["action"] == "raised":
            print(f"  ^ {r['goal']}: {r['rate']*100:.0f}% success"
                  f" -> target raised  {r['old']} -> {r['new']} {r['unit']}")
            changed = True
        elif r["action"] == "restructure":
            print(f"  * {r['goal']}: {r['rate']*100:.0f}% success"
                  f" -> micro-challenge strategy restructured")
        else:
            print(f"  . {r['goal']}: {r['rate']*100:.0f}% success (on track)")
    if changed:
        print("\n  Profile updated with new targets.")
    print(_divider("-") + "\n")


# phase 6: streaks, reports, charts

def compute_streaks(logs):
    # log_streak = consecutive days logged, momentum = recent good (>=60) run
    if not logs:
        return {"log_streak": 0, "momentum": 0, "longest_momentum": 0}

    dates = []
    for r in logs:
        try:
            dates.append(datetime.date.fromisoformat(r["date"]))
        except (ValueError, KeyError):
            continue
    dates.sort()

    log_streak = 1
    for i in range(len(dates) - 1, 0, -1):
        if (dates[i] - dates[i - 1]).days == 1:
            log_streak += 1
        else:
            break

    # momentum counts good days (60+). grace/rest days are neutral: they don't
    # count as good but they don't break you either. resting shouldn't punish.
    momentum = 0
    for r in reversed(logs):
        if (r.get("grace") or "") == "1":
            continue
        if float(r["score"]) >= 60:
            momentum += 1
        else:
            break

    longest = run = 0
    for r in logs:
        if (r.get("grace") or "") == "1":
            continue
        run = run + 1 if float(r["score"]) >= 60 else 0
        longest = max(longest, run)

    return {"log_streak": log_streak, "momentum": momentum, "longest_momentum": longest}


def effective_streak(profile, logs):
    # the streak we actually show the user: forgiven days count as covered
    dates = []
    for r in logs:
        try:
            dates.append(datetime.date.fromisoformat(r["date"]))
        except (ValueError, KeyError):
            pass
    fz = []
    for s in profile.get("freeze_dates", []):
        try:
            fz.append(datetime.date.fromisoformat(s))
        except ValueError:
            pass
    return protected_streak(dates, fz)


def _manage_freezes(profile, today):
    # called at the start of a check-in. if the user missed exactly one day and
    # has a freeze, spend it to keep the streak alive, and say so.
    logs = _read_logs()
    dates = []
    for r in logs:
        try:
            dates.append(datetime.date.fromisoformat(r["date"]))
        except (ValueError, KeyError):
            pass
    if not dates:
        return None
    today_d = datetime.date.fromisoformat(today)
    gap = (today_d - max(dates)).days
    if gap == 2 and int(profile.get("streak_freezes", 0)) > 0:
        missed = (today_d - datetime.timedelta(days=1)).isoformat()
        profile.setdefault("freeze_dates", []).append(missed)
        profile["streak_freezes"] = int(profile["streak_freezes"]) - 1
        log.info("Streak freeze used for %s", missed)
        return missed
    return None


def _earn_freeze(profile, momentum):
    # earn a freeze for every 7 good days, capped so it stays meaningful
    if momentum > 0 and momentum % 7 == 0 and int(profile.get("streak_freezes", 0)) < 3:
        profile["streak_freezes"] = int(profile.get("streak_freezes", 0)) + 1
        return True
    return False


_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def insights(profile, logs, min_days=5):
    # mines the log for: top lever (correlation), best/worst weekday,
    # top obstacle per goal, pair of goals that fail together
    out = {"enough_data": len(logs) >= min_days, "top_lever": None,
           "worst_weekday": None, "best_weekday": None,
           "obstacles": {}, "failure_pair": None}
    if not out["enough_data"]:
        return out

    goals  = profile["goals"]
    scores = [float(r["score"]) for r in logs]

    # 1. which goal's hit/miss tracks the overall score most -> the lever
    best_goal, best_corr = None, 0.0
    for i, g in enumerate(goals):
        key_a, key_t = f"actual_{i}", f"target_{i}"
        if key_a not in logs[-1]:
            continue
        hit = []
        for r in logs:
            try:
                hit.append(1.0 if float(r[key_a]) >= float(r[key_t]) else 0.0)
            except (KeyError, ValueError):
                hit.append(0.0)
        # correlation needs variance in both series
        if len(set(hit)) < 2 or len(set(scores)) < 2:
            continue
        try:
            c = statistics.correlation(hit, scores)
        except statistics.StatisticsError:
            continue
        if abs(c) > abs(best_corr):
            best_goal, best_corr = g["name"], c
    if best_goal:
        out["top_lever"] = {"goal": best_goal, "corr": round(best_corr, 2)}

    # 2. best/worst weekday by avg score
    by_day = {}
    for r, s in zip(logs, scores):
        try:
            wd = datetime.date.fromisoformat(r["date"]).weekday()
        except ValueError:
            continue
        by_day.setdefault(wd, []).append(s)
    if by_day:
        avg = {wd: statistics.mean(v) for wd, v in by_day.items()}
        worst = min(avg, key=avg.get)
        best  = max(avg, key=avg.get)
        out["worst_weekday"] = {"day": _WEEKDAYS[worst], "avg": round(avg[worst], 1)}
        out["best_weekday"]  = {"day": _WEEKDAYS[best],  "avg": round(avg[best], 1)}

    # 3. top obstacle per goal
    for i, g in enumerate(goals):
        obs = dominant_obstacle(logs, i)
        if obs:
            out["obstacles"][g["name"]] = obs

    # 4. pair of goals most often missed on the same day
    pair_counts = {}
    for r in logs:
        missed = []
        for i, g in enumerate(goals):
            key_a, key_t = f"actual_{i}", f"target_{i}"
            try:
                if float(r[key_a]) < float(r[key_t]):
                    missed.append(g["name"])
            except (KeyError, ValueError):
                pass
        for a in range(len(missed)):
            for b in range(a + 1, len(missed)):
                key = tuple(sorted((missed[a], missed[b])))
                pair_counts[key] = pair_counts.get(key, 0) + 1
    if pair_counts:
        pair, count = max(pair_counts.items(), key=lambda kv: kv[1])
        if count >= 2:
            out["failure_pair"] = {"goals": list(pair), "count": count}

    return out


def print_insights(profile):
    # terminal version of the GUI's Insights screen
    logs = _read_logs()
    data = insights(profile, logs)
    print("\n" + _divider("="))
    print("  INSIGHTS  (what actually moves your score)")
    print(_divider("="))
    if not data["enough_data"]:
        print(f"  Not enough data yet ({len(logs)} day(s)). Keep checking in.")
        print(_divider("=") + "\n")
        return

    lever = data["top_lever"]
    if lever:
        direction = "lifts" if lever["corr"] >= 0 else "drags"
        print(f"  Biggest lever  : '{lever['goal']}' {direction} your score most "
              f"(correlation {lever['corr']:+.2f}).")
    if data["worst_weekday"]:
        print(f"  Toughest day   : {data['worst_weekday']['day']} "
              f"(avg {data['worst_weekday']['avg']})")
        print(f"  Strongest day  : {data['best_weekday']['day']} "
              f"(avg {data['best_weekday']['avg']})")
    if data["obstacles"]:
        print("  Top obstacles  :")
        for goal, obs in data["obstacles"].items():
            print(f"     - {goal}: {obs}")
    if data["failure_pair"]:
        gp = data["failure_pair"]
        print(f"  Linked misses  : '{gp['goals'][0]}' and '{gp['goals'][1]}' "
              f"failed together {gp['count']} time(s).")
    stacks = habit_stack_suggestions(profile, logs)
    if stacks:
        print("  Habit stacks   :")
        for a, b, rate in stacks[:3]:
            print(f"     - hit {a} -> you also hit {b} {rate*100:.0f}% of the time")
    if detect_plateau(logs):
        print("  Heads up       : you've plateaued (stable but flat). Time to "
              "shake up the routine.")
    print(_divider("=") + "\n")


def report(profile):
    logs = _read_logs()
    if not logs:
        print("\n  No data yet. Do a daily check-in first.\n")
        return

    streaks = compute_streaks(logs)
    scores  = [float(r["score"]) for r in logs]
    goals   = profile["goals"]

    print("\n" + _divider("="))
    print("  PERFORMANCE REPORT")
    print(_divider("="))
    print(f"  Days Logged      : {len(logs)}")
    print(f"  Current Streak   : {streaks['log_streak']} day(s)")
    print(f"  Momentum (60+)   : {streaks['momentum']} day(s)  "
          f"(best ever: {streaks['longest_momentum']})")
    print(f"  Lifetime Avg     : {round(statistics.mean(scores), 1)} / 100")

    def window_stats(window, label):
        w_scores = [float(r["score"]) for r in window]
        print(f"\n  Last {label}:")
        print(f"  Avg Score      : {round(statistics.mean(w_scores), 1)} / 100")
        print(f"  Best / Worst   : {max(w_scores)} / {min(w_scores)}")
        delta = round(w_scores[-1] - w_scores[0], 1)
        arrow = "+" if delta > 0 else ("-" if delta < 0 else "~")
        print(f"  Trend          : {arrow}{abs(delta)} pts")
        stats = []
        for i, goal in enumerate(goals):
            key_a, key_t = f"actual_{i}", f"target_{i}"
            if key_a not in window[0]:
                continue
            acts = [float(r[key_a]) for r in window]
            tgts = [float(r[key_t]) for r in window]
            hits = sum(1 for a, t in zip(acts, tgts) if a >= t)
            stats.append((goal["name"], hits, len(window)))
        if stats:
            stats.sort(key=lambda x: x[1], reverse=True)
            print(f"  Most Improved  : {stats[0][0]} ({stats[0][1]}/{stats[0][2]} met)")
            print(f"  Most Neglected : {stats[-1][0]} ({stats[-1][1]}/{stats[-1][2]} met)")

    window_stats(logs[-7:], "7 Days")

    acc = intention_accuracy(profile, logs)
    if acc:
        print("\n  This week's intentions vs reality:")
        for r in acc:
            print(f"    {r['goal']}: wanted {r['intended']}, did {r['actual']} "
                  f"({r['accuracy']:.0f}% accurate)")

    if len(logs) >= 30:
        window_stats(logs[-30:], "30 Days")
        first, last = scores[-30], scores[-1]
        growth = round(((last - first) / max(first, 1)) * 100, 1)
        print(f"\n  30-Day Growth    : {'+' if growth >= 0 else ''}{growth}%")
    else:
        print(f"\n  ({30 - len(logs)} more day(s) until the full 30-day growth report.)")
    print(_divider("=") + "\n")


def _ascii_trend(logs, width=10):
    print("\n  Score Trend (recent):")
    print(_divider())
    for r in logs[-14:]:
        s = float(r["score"])
        filled = int(round(s / 100.0 * width))
        print(f"  {r['date']}  {'#' * filled}{'-' * (width - filled)}  {s:5.1f}")
    print(_divider() + "\n")


def plot_trend():
    logs = _read_logs()
    if not logs:
        print("\n  No data yet. Do a daily check-in first.\n")
        return
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n  matplotlib not installed, showing ASCII chart instead.")
        print("  (Install with:  pip install matplotlib  for a PNG chart.)")
        _ascii_trend(logs)
        return

    dates  = [r["date"] for r in logs]
    scores = [float(r["score"]) for r in logs]
    plt.figure(figsize=(10, 5))
    plt.plot(range(len(scores)), scores, marker="o", linewidth=2, color="#2E75B6")
    plt.axhline(60, color="orange", linestyle="--", linewidth=1, label="Momentum line (60)")
    plt.fill_between(range(len(scores)), scores, alpha=0.1, color="#2E75B6")
    plt.title("AlterEgo Score Trend")
    plt.xlabel("Day"); plt.ylabel("AlterEgo Score"); plt.ylim(0, 100)
    plt.xticks(range(len(scores)), dates, rotation=45, ha="right", fontsize=7)
    plt.legend(); plt.tight_layout()
    plt.savefig(CHART_FILE, dpi=120); plt.close()
    print(f"\n  Chart saved to '{CHART_FILE}' ({len(scores)} data points).\n")


def show_history(n=10):
    logs = _read_logs()
    if not logs:
        print("\n  No history yet.\n")
        return
    recent = logs[-n:]
    print(f"\n  Last {len(recent)} entries:")
    print(_divider())
    print(f"  {'Date':<12} {'Score':>6}   Challenge (truncated)")
    print(_divider())
    for r in recent:
        lbl = r.get("day_label", "")
        print(f"  {r['date']:<12} {float(r['score']):>6.1f}  {lbl:<12} {r.get('challenge', '')[:34]}")
    print(_divider() + "\n")


def print_reflections(n=14):
    logs = _read_logs()
    entries = [r for r in logs if r.get("reflection")]
    print("\n" + _divider("="))
    print("  REFLECTIONS (your own words)")
    print(_divider("="))
    if not entries:
        print("  No reflections yet. Add one after a check-in.")
        print(_divider("=") + "\n")
        return
    for r in entries[-n:]:
        print(f"  {r['date']}  ({float(r['score']):.0f})  {r['reflection']}")
    print(_divider("=") + "\n")


def print_badges(profile):
    have = set(profile.get("badges", []))
    print("\n" + _divider("="))
    print("  BADGES")
    print(_divider("="))
    for bid, label, _ in BADGES:
        mark = "[x]" if bid in have else "[ ]"
        print(f"  {mark} {label}")
    print(_divider("=") + "\n")


def print_patterns(profile):
    logs = _read_logs()
    data = behavioral_patterns(profile, logs)
    print("\n" + _divider("="))
    print(f"  WHAT {get_persona(profile)['name'].upper()} HAS LEARNED ABOUT YOU")
    print(_divider("="))
    if not data["enough_data"]:
        print(f"  Need 10+ days of data ({len(logs)} so far).")
        print(_divider("=") + "\n")
        return
    for t in data["triggers"]:
        print(f"  Trigger : when you miss {t['a']}, you miss {t['b']} the next day "
              f"{t['rate']*100:.0f}% of the time.")
    if data["weekday_cycle"]:
        wc = data["weekday_cycle"]
        print(f"  Cycle   : best on {wc['best']} ({wc['best_avg']}), "
              f"worst on {wc['worst']} ({wc['worst_avg']}).")
    if data["recovery_time"] is not None:
        print(f"  Recovery: after a bad day you take about {data['recovery_time']} "
              "days to climb back above 60.")
    sp = data["streak_personality"]
    if sp and sp["longest"]:
        extra = f", usually breaks on {sp['breaks_on']}" if sp["breaks_on"] else ""
        print(f"  Streaks : your longest run was {sp['longest']} days{extra}.")
    for goal, trend in data["goal_momentum"]:
        print(f"  Momentum: {goal} has been {trend} lately.")
    stacks = habit_stack_suggestions(profile, logs)
    for a, b, rate in stacks[:3]:
        print(f"  Stack   : on days you hit {a}, you hit {b} {rate*100:.0f}% of the time.")
    print(_divider("=") + "\n")


def print_letter(profile):
    path, text = latest_letter()
    if not text:
        print("\n  No weekly letter yet. They arrive every 7 days.\n")
        return
    print("\n" + _divider("="))
    print(text)
    print(_divider("=") + "\n")
    # mark as read
    if path and path not in profile.get("letters_read", []):
        profile.setdefault("letters_read", []).append(path)
        _save_profile(profile)


def do_scorecard(profile):
    logs = _read_logs()
    if not logs:
        print("\n  No data yet.\n")
        return
    path, text = export_scorecard(profile, logs)
    print("\n" + text)
    print(f"\n  Saved to {path}\n")


def do_heatmap():
    logs = _read_logs()
    path, err = plot_heatmap(logs)
    if err:
        print(f"\n  {err}\n")
    else:
        print(f"\n  Heatmap saved to {path}\n")


def doctor():
    # a self-diagnostic that exercises and proves the OS-level machinery.
    # handy for a demo: one command that shows the engine actually working.
    print("\n" + _divider("="))
    print("  ALTEREGO SELF-DIAGNOSTIC (the OS engine)")
    print(_divider("="))
    ok = True

    # 1. mutual exclusion: acquire the lock, confirm a second acquire is blocked
    try:
        held = osutil.FileLock("doctor_check", timeout=2)
        held.acquire()
        try:
            osutil.FileLock("doctor_check", timeout=0.3).acquire()
            print("  [FAIL] mutual exclusion: a second lock should have been blocked")
            ok = False
        except TimeoutError:
            print("  [OK]   mutual exclusion: lock held, second acquirer blocked (FileLock)")
        held.release()
    except Exception as exc:
        print(f"  [FAIL] mutual exclusion: {exc}"); ok = False

    # 2. atomic write: write then read back, confirm no temp files linger
    try:
        osutil.atomic_write_text("doctor_atomic.tmp.txt", "atomic-ok")
        with open("doctor_atomic.tmp.txt", encoding="utf-8") as f:
            assert f.read() == "atomic-ok"
        os.remove("doctor_atomic.tmp.txt")
        leftovers = [x for x in os.listdir(".") if x.endswith(".tmp")]
        print(f"  [OK]   atomic write: write/fsync/replace verified, {len(leftovers)} temp files")
    except Exception as exc:
        print(f"  [FAIL] atomic write: {exc}"); ok = False

    # 3. reminder daemon (IPC heartbeat)
    print(f"  [..]   reminder daemon: {'RUNNING' if _daemon_running() else 'stopped'}")

    # 4. log integrity (tamper detection via per-row hash)
    logs = _read_logs()
    tampered = verify_log_integrity(logs)
    if tampered:
        print(f"  [WARN] log integrity: {len(tampered)} row(s) edited outside the app")
    else:
        print(f"  [OK]   log integrity: {len(logs)} row(s), all hashes match")

    # 5. state audit (stale pids, leftover temp files, orphaned data)
    profile = _load_profile_safe()
    if profile:
        issues = audit_state(profile, logs, DAEMON_PID, LOG_FILE)
        if issues:
            for i in issues:
                print(f"  [WARN] audit: {i}")
        else:
            print("  [OK]   state audit: profile, logs, and pid files all healthy")
    else:
        print("  [..]   state audit: no profile yet")

    print(_divider("="))
    print("  " + ("All systems healthy." if ok else "Some checks failed, see above."))
    print(_divider("=") + "\n")
    return ok


def _tell_joke():
    print(f"\n  {random_joke()}\n")


def print_level(profile):
    print("\n" + _divider("="))
    print("  YOUR PROGRESS")
    print(_divider("="))
    print(f"  {xp_bar(profile.get('xp', 0))}")
    lvl, title, into, need = level_from_xp(profile.get("xp", 0))
    print(f"  Level {lvl}: {title}")
    print(f"  {need - into} XP to the next level.")
    print(_divider("=") + "\n")


def do_export(profile):
    name = export_backup(PROFILE_FILE, LOG_FILE)
    print(f"\n  Backup written to {name}\n")


def do_import(path):
    ok, msg = import_backup(path, PROFILE_FILE)
    print(f"\n  {'Restored from ' + path if ok else 'Import failed: ' + msg}\n")


# one full check-in end to end

def _score_profile(profile):
    # in recovery mode we score against easier (20% lower) targets
    if profile.get("recovery_mode"):
        eased = recovery_targets(profile)
        scoring = dict(profile)
        scoring["goals"] = [dict(g, target=eased[i]) for i, g in enumerate(profile["goals"])]
        return scoring, eased
    return profile, [g["target"] for g in profile["goals"]]


def daily_checkin(profile):
    today = datetime.date.today().isoformat()
    if _already_logged(today):
        print(f"\n  You already logged today ({today}). One entry per day allowed.")
        show_history()
        return

    # comeback + streak-freeze: handle gaps gently before anything else
    logs0 = _read_logs()
    gap = days_since_last([_d for _d in (_safe_date(r) for r in logs0) if _d], datetime.date.today())
    if gap and gap >= 2:
        msg = comeback_message(get_persona(profile)["name"], gap)
        if msg:
            print(f"\n  {msg}")
    froze = _manage_freezes(profile, today)
    if froze:
        print(f"\n  Streak freeze used! Your {effective_streak(profile, _read_logs())}-day "
              "streak is safe. You had one in the bank.")

    if profile.get("recovery_mode"):
        print("\n  [Recovery Mode] Targets are eased while you get back on your feet.")

    _maybe_ask_intentions(profile)
    grace = input("\n  Take a grace day today? Rest, no pressure. [y/N]: ").strip().lower() == "y"
    energy, mood = ask_energy_mood()
    scoring, targets = _score_profile(profile)
    today, actuals, obstacles = observe(profile, targets)
    gaps, score, weakest_idx = think(scoring, actuals)
    mode = emotional_mode(energy, mood, score)
    streaks = compute_streaks(_read_logs())            # streaks BEFORE today
    coach = coaching_state(profile, _read_logs(), energy, mood, score, streaks, grace)
    game_info = _apply_game(profile, score, streaks, grace, today)
    challenge, label = act(profile, actuals, gaps, score, weakest_idx, today,
                           streaks, obstacles, mode, targets, coach, game_info)
    if grace:
        label = "Rest Day"

    new_pbs = update_personal_bests(profile, actuals)
    for name in new_pbs:
        pe = get_persona(profile)
        print(f"  New personal best for {name}! {pe['name']} is taking notes.")

    reflection = ask_reflection()

    _log_entry(today, actuals, gaps, score, challenge, profile, obstacles,
               energy=energy, mood=mood, reflection=reflection, label=label,
               grace="1" if grace else "")
    profile["last_stance"] = coach["stance"]
    logs = _read_logs()
    n = len(logs)

    _handle_recovery_transitions(profile, logs)
    _award_badges(profile, logs)
    if _earn_freeze(profile, streaks["momentum"] + (1 if score >= 60 else 0)):
        print(f"  You earned a streak freeze! ({profile['streak_freezes']} in the bank) "
              "Miss a day and it won't break your streak.")
    _save_profile(profile)               # persist PBs, badges, recovery state, last_stance

    if n % 7 == 0:
        evolve(profile)
        path = write_weekly_letter(profile, logs)
        if path:
            print(f"  A new weekly letter from {get_persona(profile)['name']} is waiting "
                  f"(saved as {path}). Open 'Weekly letter' to read it.\n")
    if n % 30 == 0:
        print("  Milestone reached! View 'Reports' for your 30-day growth summary.\n")
    else:
        print(f"  Day {n} logged.  {30 - (n % 30)} day(s) until your next milestone.\n")


def _game_preview(profile, score, streaks, grace, date):
    # work out the draw, XP and level change WITHOUT touching the profile.
    # the GUI shows this first and only commits the XP when the check-in saves.
    draw   = daily_draw(date)
    momentum = streaks.get("momentum", 0)
    gained = xp_for_checkin(score, momentum, grace, draw["xp"])
    before = int(profile.get("xp", 0))
    after  = before + gained
    return {
        "draw": draw, "xp_gained": gained, "xp_after": after,
        "combo": combo_multiplier(momentum), "monster": monster_line(score),
        "leveled_up": level_from_xp(after)[0] > level_from_xp(before)[0],
        "level_after": level_from_xp(after)[0], "level_before": level_from_xp(before)[0],
    }


def _apply_game(profile, score, streaks, grace, date):
    # terminal path: preview then commit the XP in one step
    info = _game_preview(profile, score, streaks, grace, date)
    profile["xp"] = info["xp_after"]
    return info


def _maybe_ask_intentions(profile):
    # Feature 16: on Monday, ask once for this week's intended totals
    if datetime.date.today().weekday() != 0:
        return
    wk = week_key()
    if load_intentions().get(wk):
        return
    print("\n  New week. What do you intend to hit this week, per goal? (Enter to skip)")
    intentions = {}
    for g in profile["goals"]:
        raw = input(f"    {g['name']} total ({g['unit']}): ").strip()
        if raw:
            try:
                intentions[g["name"]] = float(raw)
            except ValueError:
                pass
    if intentions:
        save_intention(wk, intentions)
        print("  Logged. We'll see how close you get by Sunday.")


def express_apply(profile, level):
    # shared core for the 10-second check-in. maps one 1-5 rating to a day and
    # logs it. returns a small summary so any UI can show the result.
    today = datetime.date.today().isoformat()
    _manage_freezes(profile, today)
    frac = {1: 0.15, 2: 0.4, 3: 0.6, 4: 0.85, 5: 1.0}[level]
    _, targets = _score_profile(profile)
    actuals = [round(t * frac, 2) for t in targets]
    gaps, score, weakest_idx = think(_score_profile(profile)[0], actuals)
    streaks = compute_streaks(_read_logs())
    coach = coaching_state(profile, _read_logs(), level, level, score, streaks)
    challenge = micro_challenge(profile, actuals, weakest_idx, today)
    label = day_label(score, profile.get("recovery_mode"))
    game_info = _apply_game(profile, score, streaks, False, today)
    _log_entry(today, actuals, gaps, score, challenge, profile,
               energy=level, mood=level, label=label)
    _award_badges(profile, _read_logs())
    profile["last_stance"] = coach["stance"]
    _save_profile(profile)
    return {"score": score, "headline": coach["headline"], "game": game_info}


def express_checkin(profile):
    # the 10-second path for low-energy days. one question, no per-goal numbers.
    today = datetime.date.today().isoformat()
    if _already_logged(today):
        print(f"\n  You already logged today ({today}).")
        return
    print("\n  Quick check-in. How did today go overall?")
    print("   1) rough   2) meh   3) okay   4) good   5) great")
    level = _input_int("  Pick 1-5: ", lo=1, hi=5)
    res = express_apply(profile, level)
    print(f"\n  Logged a quick day. Score {res['score']}/100. {res['headline']}")
    print(f"  +{res['game']['xp_gained']} XP   {xp_bar(res['game']['xp_after'])}")
    print("  Nice. Showing up on a hard day still counts. See you tomorrow.\n")


def _handle_recovery_transitions(profile, logs):
    # enter recovery on a 3-day slump, leave it on a 2-day comeback
    if not profile.get("recovery_mode") and detect_slump(logs):
        profile["recovery_mode"] = True
        profile["recovery_since"] = datetime.date.today().isoformat()
        log.info("Entered recovery mode")
        print("\n  [Recovery Mode ON] You're in a hard stretch. We'll just do the "
              "minimum for a bit. No pressure.\n")
    elif profile.get("recovery_mode") and detect_comeback(logs):
        profile["recovery_mode"] = False
        profile["recovery_since"] = None
        log.info("Exited recovery mode")
        print(f"\n  [Comeback!] Two strong days in a row. {get_persona(profile)['name']} "
              "knew you'd be back. Targets restored.\n")


def _award_badges(profile, logs):
    newly = check_badges(profile, logs)
    for bid in newly:
        profile.setdefault("badges", []).append(bid)
        log.info("Badge earned: %s", bid)
        print(f"  Badge unlocked: {badge_label(bid)}")


# reminder daemon (runs as a separate background process)

def _daemon_settings():
    # read live each tick so mode/hour changes apply without restarting
    p = _load_profile_safe() or {}
    return {
        "hour": int(p.get("reminder_hour", DEFAULT_REMINDER_HOUR)),
        "mode": p.get("daemon_mode", "watchdog"),
        "recovery": bool(p.get("recovery_mode")),
        "burnout": detect_burnout_risk(p, _read_logs())[0] if p.get("goals") else False,
        "persona": get_persona(p)["name"] if p.get("goals") else "your AlterEgo",
    }


def _reminder_hour():
    p = _load_profile_safe()
    return int(p.get("reminder_hour", DEFAULT_REMINDER_HOUR)) if p else DEFAULT_REMINDER_HOUR


def _daemon_running():
    # heartbeat first, pid_alive as backup
    if os.path.exists(DAEMON_STATUS):
        try:
            with open(DAEMON_STATUS, encoding="utf-8") as f:
                st = json.load(f)
            if time.time() - st.get("heartbeat", 0) < HEARTBEAT_TTL:
                return True
        except (json.JSONDecodeError, OSError):
            pass
    if os.path.exists(DAEMON_PID):
        try:
            with open(DAEMON_PID, encoding="utf-8") as f:
                return osutil.pid_alive(int(f.read().strip()))
        except (ValueError, OSError):
            pass
    return False


def _daemon_pid():
    try:
        with open(DAEMON_PID, encoding="utf-8") as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None


def _daemon_message(cfg, today):
    # tone depends on the user's current state
    name = cfg["persona"]
    if cfg["burnout"]:
        return ("AlterEgo Agent",
                "The data says you might be burning out. Take a real rest day today, "
                "no log required.")
    if cfg["recovery"]:
        return ("AlterEgo Agent",
                f"Hey. You're in a hard stretch. {name} just wants the minimum today, "
                "that's enough.")
    return ("AlterEgo Agent",
            f"You haven't checked in today ({today}). {name} is waiting, take 30 seconds.")


def daemon_run(interval=DAEMON_INTERVAL):
    # main loop for the detached process. writes heartbeat, watches the
    # stop-flag file, nags at most once a day.
    osutil.atomic_write_text(DAEMON_PID, str(os.getpid()))
    log.info("Reminder daemon started")

    stop = {"flag": False}
    nags = {"date": None, "count": 0}      # throttle per day, supports adaptive 2nd nag

    def _handle(signum, _frame):
        log.info("Daemon received signal %s", signum)
        stop["flag"] = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle)
        except (ValueError, OSError):
            pass   # not every signal works on every platform

    try:
        while not stop["flag"]:
            if os.path.exists(DAEMON_STOP):
                log.info("Daemon saw stop flag")
                break

            today = datetime.date.today().isoformat()
            done  = _already_logged(today)
            now_h = datetime.datetime.now().hour
            cfg   = _daemon_settings()

            # heartbeat for the main app (includes live mode for the UI)
            osutil.atomic_write_text(DAEMON_STATUS, json.dumps({
                "heartbeat": time.time(),
                "pid":       os.getpid(),
                "checked_in": done,
                "date":      today,
                "mode":      cfg["mode"],
            }))

            if today != nags["date"]:
                nags["date"], nags["count"] = today, 0

            # silent mode: heartbeat only, never notify
            if cfg["mode"] != "silent" and not done and now_h >= cfg["hour"]:
                # adaptive nags up to twice a day, watchdog once
                cap = 2 if cfg["mode"] == "adaptive" else 1
                if nags["count"] < cap:
                    title, body = _daemon_message(cfg, today)
                    log.info("REMINDER (%s): %s", cfg["mode"], body)
                    osutil.notify(title, body)
                    nags["count"] += 1

            # 1s slices so the stop-flag is noticed fast
            slept = 0.0
            while slept < interval and not stop["flag"] and not os.path.exists(DAEMON_STOP):
                time.sleep(min(1.0, interval - slept))
                slept += 1.0
    finally:
        log.info("Reminder daemon stopping")
        for f in (DAEMON_PID, DAEMON_STATUS, DAEMON_STOP):
            try:
                os.remove(f)
            except FileNotFoundError:
                pass


def reminder_start():
    if _daemon_running():
        print("  Reminder daemon is already running.")
        return
    for f in (DAEMON_STOP, DAEMON_STATUS, DAEMON_PID):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass

    kwargs = {"stdin": subprocess.DEVNULL}
    logf = open(DAEMON_LOG, "a", encoding="utf-8")
    kwargs["stdout"] = logf
    kwargs["stderr"] = logf
    if os.name == "nt":
        DETACHED_PROCESS        = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--daemon-run"], **kwargs)

    # wait up to ~10s for first heartbeat
    for _ in range(40):
        if _daemon_running():
            print("  Reminder daemon started in the background.")
            print(f"  It will remind you after {_reminder_hour()}:00 if you haven't checked in.")
            return
        time.sleep(0.25)
    print("  ! Daemon did not report a heartbeat. Check 'alterego_daemon.log'.")


def reminder_stop():
    if not _daemon_running():
        print("  Reminder daemon is not running.")
        for f in (DAEMON_STOP, DAEMON_STATUS, DAEMON_PID):
            try:
                os.remove(f)
            except FileNotFoundError:
                pass
        return

    # nicely: drop a stop-flag and let it exit on its own
    osutil.atomic_write_text(DAEMON_STOP, "stop")
    pid = _daemon_pid()

    for _ in range(40):
        if not _daemon_running():
            print("  Reminder daemon stopped.")
            return
        time.sleep(0.25)

    # didn't quit, send SIGTERM directly
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for f in (DAEMON_STOP, DAEMON_STATUS, DAEMON_PID):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
    print("  Reminder daemon stopped (forced).")


def reminder_status():
    if _daemon_running():
        info = ""
        if os.path.exists(DAEMON_STATUS):
            try:
                with open(DAEMON_STATUS, encoding="utf-8") as f:
                    st = json.load(f)
                age = int(time.time() - st.get("heartbeat", 0))
                info = (f"  (pid {st.get('pid')}, last heartbeat {age}s ago, "
                        f"checked_in today: {st.get('checked_in')})")
            except (json.JSONDecodeError, OSError):
                pass
        print(f"  Reminder daemon: RUNNING{info}")
    else:
        print("  Reminder daemon: STOPPED")


DAEMON_MODES = ["watchdog", "adaptive", "silent"]


def reminder_menu():
    while True:
        p = _load_profile_safe() or {}
        print("\n  " + _divider())
        print("  REMINDER DAEMON")
        print("  " + _divider())
        reminder_status()
        print(f"  Mode: {p.get('daemon_mode', 'watchdog')}  "
              "(watchdog=once/day, adaptive=twice, silent=off)")
        print("  " + _divider())
        print("   1. Start daemon")
        print("   2. Stop daemon")
        print("   3. Change mode")
        print("   4. Refresh status")
        print("   0. Back")
        choice = input("  Choice: ").strip()
        if choice == "0":
            return
        elif choice == "1":
            reminder_start()
        elif choice == "2":
            reminder_stop()
        elif choice == "3":
            print("   1) watchdog   2) adaptive   3) silent")
            m = _input_int("  Mode: ", lo=1, hi=3)
            if p:
                p["daemon_mode"] = DAEMON_MODES[m - 1]
                _save_profile(p)
                print(f"  Mode set to {p['daemon_mode']} (applies live, no restart).")
        elif choice == "4":
            continue
        else:
            print("  ! Invalid option.")


# terminal menu

def _print_welcome(profile):
    logs = _read_logs()
    pe = get_persona(profile)
    gap = days_since_last([d for d in (_safe_date(r) for r in logs) if d], datetime.date.today())
    cm = comeback_message(pe["name"], gap) if gap else None
    if cm:
        print(f"  {cm}")
    else:
        print(f"  {smart_greeting(profile, logs)}")
    print(f"  AlterEgo: {pe['name']} ({pe['voice']})  |  "
          f"Tracking: {', '.join(g['name'] for g in profile['goals'])}")
    print(f"  {xp_bar(profile.get('xp', 0))}")
    streak = effective_streak(profile, logs)
    freezes = int(profile.get("streak_freezes", 0))
    print(f"  Streak: {streak} day(s)  |  Freezes in the bank: {freezes}")
    season_name, season_desc = growth_season(profile, logs)
    print(f"  Season: {season_name} - {season_desc}")
    pr = principle_for_state(profile, logs)
    print(f"  Principle: \"{pr['text']}\" - {pr['who']}")
    density = ui_density(profile, logs)
    if density["mode"] == "calm":
        print("  Taking it easy today. The quick check-in (option 0) is right there.")
    elif density["mode"] == "rich":
        print("  You're on a roll. Worth peeking at Insights or Patterns today.")
    # quiet audit + burnout banners
    issues = audit_state(profile, logs, DAEMON_PID, LOG_FILE)
    for i in issues:
        print(f"  [audit] {i}")
    risk, reason = detect_burnout_risk(profile, logs)
    if risk:
        print(f"  [{pe['name']}] You might need rest, not a challenge today ({reason}).")
    print()


def _ensure_profile():
    profile = _load_profile_safe()
    if profile is None:
        profile = setup_profile()
    elif _migrate_profile(profile):
        _save_profile(profile)          # persist any newly added fields
    return profile


def menu():
    _clear()
    print(BANNER)
    profile = _ensure_profile()
    _print_welcome(profile)

    options = {
        "1":  ("Daily check-in",     lambda: daily_checkin(profile)),
        "0":  ("Quick check-in (10s)", lambda: express_checkin(profile)),
        "2":  ("View history",       show_history),
        "3":  ("Reports & growth",   lambda: report(profile)),
        "4":  ("Insights",           lambda: print_insights(profile)),
        "5":  ("Patterns",           lambda: print_patterns(profile)),
        "6":  ("Reflections",        print_reflections),
        "7":  ("Badges",             lambda: print_badges(profile)),
        "8":  ("Weekly letter",      lambda: print_letter(profile)),
        "9":  ("Score card",         lambda: do_scorecard(profile)),
        "10": ("Score trend chart",  plot_trend),
        "11": ("Manage goals",       lambda: manage_goals(profile)),
        "12": ("Reminder daemon",    reminder_menu),
        "13": ("Tell me a joke",     _tell_joke),
        "14": ("Exit",               None),
    }

    while True:
        try:
            print(_divider())
            print("  MAIN MENU")
            print(_divider())
            for key, (label, _) in options.items():
                print(f"   {key:>2}. {label}")
            print(_divider())
            choice = input("  Select an option: ").strip()

            if choice == "14":
                print("\n  Keep showing up. Your AlterEgo is watching. Goodbye.\n")
                return
            action = options.get(choice)
            if action is None:
                print("  ! Invalid option. Choose 1-14.\n")
                continue
            action[1]()
        except KeyboardInterrupt:
            # clean exit instead of a traceback
            print("\n\n  Interrupted. Your progress is saved. Goodbye.\n")
            return


# entry point

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AlterEgo Agent: self-evolving accountability agent.")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--checkin", action="store_true", help="run one interactive daily check-in")
    g.add_argument("--report", action="store_true", help="print the performance report")
    g.add_argument("--insights", action="store_true", help="print the insight engine output")
    g.add_argument("--patterns", action="store_true", help="print the behavioral patterns")
    g.add_argument("--reflections", action="store_true", help="print recent reflections")
    g.add_argument("--badges", action="store_true", help="print earned badges")
    g.add_argument("--letter", action="store_true", help="print the latest weekly letter")
    g.add_argument("--scorecard", action="store_true", help="export and print the score card")
    g.add_argument("--level", action="store_true", help="show your XP and level")
    g.add_argument("--joke", action="store_true", help="hear a (questionable) joke")
    g.add_argument("--chart", action="store_true", help="generate the score-trend chart")
    g.add_argument("--heatmap", action="store_true", help="generate the year heatmap")
    g.add_argument("--export", action="store_true", help="zip up profile + log as a backup")
    g.add_argument("--import-file", metavar="ZIP", help="restore from a backup zip")
    g.add_argument("--reminder-start", action="store_true", help="start the reminder daemon")
    g.add_argument("--reminder-stop", action="store_true", help="stop the reminder daemon")
    g.add_argument("--reminder-status", action="store_true", help="show daemon status")
    g.add_argument("--doctor", action="store_true", help="run a self-diagnostic of the OS engine")
    g.add_argument("--daemon-run", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.daemon_run:
        daemon_run()
    elif args.checkin:
        daily_checkin(_ensure_profile())
    elif args.report:
        report(_ensure_profile())
    elif args.insights:
        print_insights(_ensure_profile())
    elif args.patterns:
        print_patterns(_ensure_profile())
    elif args.reflections:
        print_reflections()
    elif args.badges:
        print_badges(_ensure_profile())
    elif args.letter:
        print_letter(_ensure_profile())
    elif args.scorecard:
        do_scorecard(_ensure_profile())
    elif args.level:
        print_level(_ensure_profile())
    elif args.joke:
        _tell_joke()
    elif args.chart:
        plot_trend()
    elif args.heatmap:
        do_heatmap()
    elif args.export:
        do_export(_ensure_profile())
    elif args.import_file:
        do_import(args.import_file)
    elif args.reminder_start:
        reminder_start()
    elif args.reminder_stop:
        reminder_stop()
    elif args.reminder_status:
        reminder_status()
    elif args.doctor:
        doctor()
    else:
        menu()


if __name__ == "__main__":
    main()
