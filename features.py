"""
The intelligence + persona layer for AlterEgo.

These are all pure-ish helpers: most take (profile, logs) and return data or a
string, a few write a file (letter, scorecard, heatmap, backup). Keeping them
here keeps alterego.py focused on the loop and the daemon. alterego.py imports
everything from this file so the rest of the app and the tests still call them
as ae.something().
"""

import os
import json
import glob
import zipfile
import hashlib
import datetime
import statistics

import osutil

LETTER_PREFIX   = "alterego_letter_"
SCORECARD_PREFIX = "alterego_scorecard_"
HEATMAP_FILE    = "alterego_heatmap.png"
INTENTIONS_FILE = "alterego_intentions.json"

VOICES     = ["firm", "warm", "fierce", "playful"]
CHRONOTYPES = ["morning", "afternoon", "night"]

# quick-start presets so a new user isn't staring at a blank setup form
GOAL_TEMPLATES = {
    "Student": [
        {"name": "Study", "unit": "hours", "target": 3.0, "weight": 3, "baseline": 1.0,
         "why": "to become someone who finishes what they start"},
        {"name": "Sleep", "unit": "hours", "target": 8.0, "weight": 2, "baseline": 6.0, "why": ""},
        {"name": "Reading", "unit": "minutes", "target": 30.0, "weight": 1, "baseline": 10.0, "why": ""},
    ],
    "Athlete": [
        {"name": "Training", "unit": "sessions", "target": 1.0, "weight": 3, "baseline": 0.0, "why": ""},
        {"name": "Sleep", "unit": "hours", "target": 8.0, "weight": 2, "baseline": 6.0, "why": ""},
        {"name": "Steps", "unit": "thousand", "target": 8.0, "weight": 1, "baseline": 4.0, "why": ""},
    ],
    "Creator": [
        {"name": "Create", "unit": "hours", "target": 2.0, "weight": 3, "baseline": 0.5,
         "why": "to build the body of work I want to be known for"},
        {"name": "Sleep", "unit": "hours", "target": 7.0, "weight": 2, "baseline": 6.0, "why": ""},
        {"name": "Learn", "unit": "minutes", "target": 30.0, "weight": 1, "baseline": 10.0, "why": ""},
    ],
    "Balanced": [
        {"name": "Deep Work", "unit": "hours", "target": 2.0, "weight": 3, "baseline": 1.0, "why": ""},
        {"name": "Exercise", "unit": "times", "target": 1.0, "weight": 2, "baseline": 0.0, "why": ""},
        {"name": "Sleep", "unit": "hours", "target": 8.0, "weight": 2, "baseline": 6.0, "why": ""},
    ],
}

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# small shared helpers

def _scores(logs):
    out = []
    for r in logs:
        try:
            out.append(float(r["score"]))
        except (KeyError, ValueError):
            pass
    return out


def _dated(logs):
    # (date, row) sorted by date, skipping unparseable dates
    out = []
    for r in logs:
        try:
            out.append((datetime.date.fromisoformat(r["date"]), r))
        except (KeyError, ValueError):
            pass
    out.sort(key=lambda x: x[0])
    return out


def _goal_hit(row, i):
    try:
        return float(row[f"actual_{i}"]) >= float(row[f"target_{i}"])
    except (KeyError, ValueError):
        return False


def row_hash(date, score, challenge):
    # sha256 of the fields we care about. used for tamper detection.
    raw = f"{date}|{score}|{challenge}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


# Feature 1: persona

def get_persona(profile):
    p = (profile or {}).get("persona") or {}
    return {
        "name":   p.get("name") or "your AlterEgo",
        "voice":  p.get("voice") or "firm",
        "traits": p.get("traits") or [],
    }


# voice lines for the four score bands, plain "standard" mode
_STANDARD = {
    "EXCELLENT": {
        "firm":   "That is the standard. {name} showed up as you today.",
        "warm":   "Look at you. {name} is proud of this one, hold onto the feeling.",
        "fierce": "THAT is what {name} looks like. Do it again tomorrow.",
        "playful": "Okay show-off. {name} is impressed and slightly intimidated.",
    },
    "KEEP GOING": {
        "firm":   "Solid, but {name} knows there was more in you. Close the gap.",
        "warm":   "Good day. {name} sees you trying, a little more tomorrow.",
        "fierce": "Decent. {name} wants the version that does not settle. Push.",
        "playful": "Not bad! {name} gives it a solid 'eh, respectable'. We can do better.",
    },
    "WAKE UP": {
        "firm":   "You slipped today. {name} does not make excuses, and neither should you.",
        "warm":   "Rough one. {name} still believes in you, fix one thing tomorrow.",
        "fierce": "{name} showed up and you did not. Tomorrow you answer for it.",
        "playful": "Yikes. {name} watched that happen in slow motion. Redemption arc starts tomorrow.",
    },
    "ROCK BOTTOM": {
        "firm":   "Bad day. {name} starts again tomorrow, smallest goal first.",
        "warm":   "Today hurt. {name} is not leaving. One tiny win tomorrow, that is all.",
        "fierce": "Zero is a choice. {name} is waiting. Tomorrow you show up.",
        "playful": "Well that was a speedrun to the bottom. {name} is laughing WITH you. Mostly.",
    },
}

_RECOVERY = {
    "firm":   "You are running low today and that is real. {name} does not expect 100% from a 40% day. Rest, come back tomorrow.",
    "warm":   "I know today was heavy. {name} is not disappointed in you. Rest tonight, we go again tomorrow.",
    "fierce": "Even {name} needs a night off. Recover hard so you can come back swinging.",
    "playful": "Battery at 2%, I see you. {name} says nap now, conquer later. This is allowed.",
}
_PUSH = {
    "firm":   "You had the energy and still fell short. {name} is not accepting that. Tomorrow, no excuses.",
    "warm":   "You had more in the tank today. {name} knows you can use it, let's aim higher tomorrow.",
    "fierce": "Full battery and you coasted? {name} showed up, you did not. Fix it.",
    "playful": "Full tank and you parked it? {name} saw that. Tomorrow we actually drive.",
}
_CELEBRATE = {
    "firm":   "That is exactly who {name} is. Lock it in.",
    "warm":   "Beautiful day. {name} is proud, and you should be too.",
    "fierce": "THAT is the standard {name} set. Again tomorrow.",
    "playful": "Chef's kiss. {name} is framing this one. Do it again, legend.",
}


def persona_message(profile, score, tone, mode="standard"):
    # one line in the persona's voice. mode (recovery/push/celebrate) wins over
    # the plain tone bands.
    pe = get_persona(profile)
    voice = pe["voice"] if pe["voice"] in VOICES else "firm"
    if mode == "recovery":
        table = _RECOVERY
    elif mode == "push":
        table = _PUSH
    elif mode == "celebrate":
        table = _CELEBRATE
    else:
        table = _STANDARD.get(tone, _STANDARD["KEEP GOING"])
    return table[voice].format(name=pe["name"])


# Feature 2: emotional mode

def emotional_mode(energy, mood, score):
    # decide whether to push, hold, celebrate, or stay neutral
    try:
        energy = float(energy); mood = float(mood)
    except (TypeError, ValueError):
        energy = mood = 3
    if energy <= 2 and mood <= 2:
        return "recovery"
    if energy >= 4 and score < 60:
        return "push"
    if score >= 80:
        return "celebrate"
    return "standard"


# Feature 4: recovery mode

def detect_slump(logs):
    # last 3 scores all below 40
    s = _scores(logs)
    return len(s) >= 3 and all(x < 40 for x in s[-3:])


def detect_comeback(logs):
    # last 2 scores both above 60 (used to exit recovery mode)
    s = _scores(logs)
    return len(s) >= 2 and all(x > 60 for x in s[-2:])


def recovery_targets(profile):
    # 20% easier, not saved to the profile
    out = []
    for g in profile["goals"]:
        out.append(round(g["target"] * 0.8, 2))
    return out


# Feature 14: personal bests

def update_personal_bests(profile, actuals):
    # compare today's actuals to the stored bests, return list of new PB goal names
    pb = profile.setdefault("personal_bests", {})
    today = datetime.date.today().isoformat()
    new = []
    for i, g in enumerate(profile["goals"]):
        val = actuals[i]
        prev = pb.get(g["name"], {}).get("value")
        if prev is None or val > prev:
            if prev is not None and val > prev:
                new.append(g["name"])
            pb[g["name"]] = {"value": val, "date": today}
    return new


# Feature 15: plateau

def detect_plateau(logs):
    # stable but not growing: last 10 scores, stdev < 5, mean 55..75
    s = _scores(logs)
    if len(s) < 10:
        return False
    last10 = s[-10:]
    if statistics.pstdev(last10) >= 5:
        return False
    return 55 <= statistics.mean(last10) <= 75


# Feature 19: day label

def day_label(score, recovery_mode=False):
    if recovery_mode:
        return "Rest Day"
    if score >= 90:
        return "Locked In"
    if score >= 70:
        return "Showed Up"
    if score >= 60:
        return "Good Enough"
    if score >= 40:
        return "Slipped"
    return "Ghost Day"


# Feature 17: circadian advice

def chronotype_advice(profile, goal_name):
    ct = profile.get("chronotype")
    if ct == "night":
        return f"You work best at night. Move {goal_name} to after 9pm, your peak."
    if ct == "morning":
        return f"You work best in the morning. Start {goal_name} before 9am."
    if ct == "afternoon":
        return f"You peak in the afternoon. Block {goal_name} early afternoon."
    return None


# Feature 20: smart greeting

def smart_greeting(profile, logs, now=None):
    now = now or datetime.datetime.now()
    pe = get_persona(profile)
    name = pe["name"]
    s = _scores(logs)
    part = "morning" if now.hour < 12 else ("afternoon" if now.hour < 18 else "evening")

    if profile.get("recovery_mode"):
        return f"Rest day. {name} is not asking for perfect today. Just show up."

    # streak based
    from_streak = _consec_run(_dated(logs))
    if now.weekday() == 0 and from_streak >= 3:
        return f"New week. {name} has a {from_streak}-day streak to protect. No slow start."
    if part == "evening" and s and s[-1] < 40:
        return f"End of the day. Yesterday was rough, make today count."
    if s and s[-1] >= 90:
        return f"Good {part}. {name} was sharp yesterday, keep that line going."
    if from_streak >= 1:
        return f"Good {part}. {from_streak}-day streak alive. Keep it."
    return f"Good {part}. {name} is ready when you are."


def _consec_run(dated):
    # length of the consecutive-day run ending at the last entry
    if not dated:
        return 0
    run = 1
    for i in range(len(dated) - 1, 0, -1):
        if (dated[i][0] - dated[i - 1][0]).days == 1:
            run += 1
        else:
            break
    return run


# Feature 10: badges

# each badge: id, label, and a predicate(profile, logs) -> bool
def _longest_consec(dated):
    if not dated:
        return 0
    longest = run = 1
    for i in range(1, len(dated)):
        if (dated[i][0] - dated[i - 1][0]).days == 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 1
    return longest


def _badge_first_week(profile, logs):
    return _longest_consec(_dated(logs)) >= 7

def _badge_diamond(profile, logs):
    return _longest_consec(_dated(logs)) >= 21

def _badge_perfect(profile, logs):
    return any(x >= 100 for x in _scores(logs))

def _badge_climber(profile, logs):
    s = _scores(logs)
    if len(s) < 30:
        return False
    return statistics.mean(s[-5:]) - statistics.mean(s[-30:-25]) >= 15

def _badge_resilient(profile, logs):
    s = _scores(logs)
    for i in range(len(s) - 3):
        if all(x < 40 for x in s[i:i+3]):
            if any(x > 70 for x in s[i+3:i+7]):
                return True
    return False

def _badge_locked_in(profile, logs):
    dated = _dated(logs)
    if len(dated) < 14:
        return False
    last14 = [r for _, r in dated[-14:]]
    for i in range(len(profile["goals"])):
        if all(_goal_hit(r, i) for r in last14):
            return True
    return False

def _badge_comeback(profile, logs):
    dated = _dated(logs)
    for i in range(1, len(dated)):
        if (dated[i][0] - dated[i-1][0]).days == 1:
            try:
                prev = float(dated[i-1][1]["score"]); cur = float(dated[i][1]["score"])
            except (KeyError, ValueError):
                continue
            if prev < 30 and cur >= 80:
                return True
    return False


# the fun ones

def _badge_goblin(profile, logs):
    return any(s == 0 for s in _scores(logs))         # a true zero day happened

def _badge_overachiever(profile, logs):
    return sum(1 for s in _scores(logs) if s >= 100) >= 3

def _badge_phoenix(profile, logs):
    s = _scores(logs)
    for i in range(len(s) - 3):
        if all(x < 40 for x in s[i:i+3]) and any(x >= 80 for x in s[i+3:i+8]):
            return True
    return False

def _badge_centurion(profile, logs):
    return len(_scores(logs)) >= 100


BADGES = [
    ("first_week",   "First Week (7 days straight)",       _badge_first_week),
    ("diamond",      "Diamond Streak (21 days)",            _badge_diamond),
    ("perfect_day",  "Perfect Day (scored 100)",            _badge_perfect),
    ("climber",      "Climber (+15 avg over 30 days)",      _badge_climber),
    ("resilient",    "Resilient (back from a slump)",       _badge_resilient),
    ("locked_in",    "Locked In (a goal 14 days)",          _badge_locked_in),
    ("comeback",     "Comeback Kid (80+ after a <30)",      _badge_comeback),
    ("goblin_mode",  "Goblin Mode (a 0 day, we don't talk about it)", _badge_goblin),
    ("overachiever", "Overachiever (three perfect days)",   _badge_overachiever),
    ("phoenix",      "Phoenix (rose from 3 ghost days)",    _badge_phoenix),
    ("centurion",    "Centurion (100 days logged)",         _badge_centurion),
]


def check_badges(profile, logs):
    # return badge ids earned now that weren't earned before
    have = set(profile.get("badges", []))
    newly = []
    for bid, _label, pred in BADGES:
        if bid in have:
            continue
        try:
            if pred(profile, logs):
                newly.append(bid)
        except Exception:
            pass
    return newly


def badge_label(bid):
    for b_id, label, _ in BADGES:
        if b_id == bid:
            return label
    return bid


# Feature 11: burnout risk

BURNOUT_WORDS = ["tired", "exhausted", "can't", "cant", "overwhelmed",
                 "hate this", "burnt out", "burned out", "drained", "done"]


def detect_burnout_risk(profile, logs):
    # returns (bool, reason). a few independent signals, any one trips it.
    if len(logs) < 5:
        return False, ""

    # 1. reflections mentioning burnout words
    hits = 0
    for r in logs[-7:]:
        text = (r.get("reflection") or "").lower()
        if any(w in text for w in BURNOUT_WORDS):
            hits += 1
    if hits >= 2:
        return True, "your recent notes sound exhausted"

    # 2. high energy but falling scores over 5+ days
    s = _scores(logs)
    energies = []
    for r in logs[-5:]:
        try:
            energies.append(float(r.get("energy") or 0))
        except ValueError:
            energies.append(0)
    if len(s) >= 5 and all(e >= 4 for e in energies) and s[-1] < s[-5]:
        return True, "full energy but your scores keep dropping"

    # 3. high energy, low mood, 7 days
    if len(logs) >= 7:
        ok = True
        for r in logs[-7:]:
            try:
                e = float(r.get("energy") or 0); m = float(r.get("mood") or 5)
            except ValueError:
                ok = False; break
            if not (e >= 4 and m <= 2):
                ok = False; break
        if ok:
            return True, "high energy but low mood all week"

    # 4. score variance spiking
    if len(s) >= 8 and statistics.pstdev(s[-8:]) > 25:
        return True, "your days are swinging wildly"

    return False, ""


# Feature 12: habit stacks

def habit_stack_suggestions(profile, logs, threshold=0.70, min_days=14):
    # for each ordered goal pair, P(hit B | hit A). return strong ones.
    if len(logs) < min_days:
        return []
    goals = profile["goals"]
    out = []
    for a in range(len(goals)):
        a_days = [r for r in logs if _goal_hit(r, a)]
        if len(a_days) < 3:
            continue
        for b in range(len(goals)):
            if a == b:
                continue
            both = sum(1 for r in a_days if _goal_hit(r, b))
            rate = both / len(a_days)
            if rate >= threshold:
                out.append((goals[a]["name"], goals[b]["name"], round(rate, 2)))
    out.sort(key=lambda x: x[2], reverse=True)
    return out


# Feature 8: AlterEgo vs You

def compare_selves(profile, logs):
    # actual vs target per goal for the most recent entry
    if not logs:
        return None
    row = logs[-1]
    rows = []
    actual_total = target_total = 0.0
    for i, g in enumerate(profile["goals"]):
        try:
            actual = float(row[f"actual_{i}"]); target = float(row[f"target_{i}"])
        except (KeyError, ValueError):
            continue
        rows.append({"goal": g["name"], "unit": g["unit"],
                     "actual": actual, "target": target,
                     "pct": 0.0 if target <= 0 else min(1.0, actual / target)})
        actual_total += actual; target_total += target
    try:
        score = float(row["score"])
    except (KeyError, ValueError):
        score = 0.0
    return {"rows": rows, "score": score, "gap_points": round(100 - score, 1)}


# Feature 5: behavioral patterns

def behavioral_patterns(profile, logs, min_days=10):
    out = {"enough_data": len(logs) >= min_days, "triggers": [],
           "weekday_cycle": None, "recovery_time": None,
           "streak_personality": None, "goal_momentum": []}
    if not out["enough_data"]:
        return out

    goals = profile["goals"]
    dated = _dated(logs)

    # trigger chains: miss A today -> miss B tomorrow
    for a in range(len(goals)):
        for b in range(len(goals)):
            if a == b:
                continue
            base = follow = 0
            for i in range(len(dated) - 1):
                d0, r0 = dated[i]; d1, r1 = dated[i + 1]
                if (d1 - d0).days != 1:
                    continue
                if not _goal_hit(r0, a):           # missed A
                    base += 1
                    if not _goal_hit(r1, b):       # then missed B
                        follow += 1
            if base >= 3 and follow / base >= 0.6:
                out["triggers"].append({
                    "a": goals[a]["name"], "b": goals[b]["name"],
                    "rate": round(follow / base, 2)})

    # weekday cycle: best vs worst weekday
    by_day = {}
    for d, r in dated:
        try:
            by_day.setdefault(d.weekday(), []).append(float(r["score"]))
        except (KeyError, ValueError):
            pass
    if by_day:
        avg = {k: statistics.mean(v) for k, v in by_day.items()}
        best = max(avg, key=avg.get); worst = min(avg, key=avg.get)
        out["weekday_cycle"] = {"best": _WEEKDAYS[best], "worst": _WEEKDAYS[worst],
                                "best_avg": round(avg[best], 1),
                                "worst_avg": round(avg[worst], 1)}

    # recovery time: after a sub-40 day, how long to climb back above 60
    s = [float(r["score"]) for _, r in dated]
    spans = []
    i = 0
    while i < len(s):
        if s[i] < 40:
            j = i + 1
            while j < len(s) and s[j] < 60:
                j += 1
            if j < len(s):
                spans.append(j - i)
            i = j
        else:
            i += 1
    if spans:
        out["recovery_time"] = round(statistics.mean(spans), 1)

    # streak personality: longest run + where breaks happen
    longest = _longest_consec(dated)
    break_days = {}
    for i in range(1, len(dated)):
        d, r = dated[i]
        try:
            if float(r["score"]) < 60:
                break_days[d.weekday()] = break_days.get(d.weekday(), 0) + 1
        except (KeyError, ValueError):
            pass
    worst_break = max(break_days, key=break_days.get) if break_days else None
    out["streak_personality"] = {
        "longest": longest,
        "breaks_on": _WEEKDAYS[worst_break] if worst_break is not None else None}

    # goal momentum: improving or declining over last 14
    for i, g in enumerate(goals):
        vals = []
        for _, r in dated[-14:]:
            try:
                vals.append(float(r[f"actual_{i}"]))
            except (KeyError, ValueError):
                pass
        if len(vals) >= 6:
            half = len(vals) // 2
            early = statistics.mean(vals[:half]); late = statistics.mean(vals[half:])
            if late > early * 1.1:
                out["goal_momentum"].append((g["name"], "improving"))
            elif late < early * 0.9:
                out["goal_momentum"].append((g["name"], "declining"))
    return out


# Feature 16: intentions

def load_intentions():
    if not os.path.exists(INTENTIONS_FILE):
        return {}
    try:
        with open(INTENTIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_intention(week_key, intentions):
    data = load_intentions()
    data[week_key] = intentions
    osutil.atomic_write_text(INTENTIONS_FILE, json.dumps(data, indent=2))


def week_key(date=None):
    date = date or datetime.date.today()
    iso = date.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def intention_accuracy(profile, logs, wk=None):
    # compare this week's actual totals to the stated intention
    wk = wk or week_key()
    intentions = load_intentions().get(wk)
    if not intentions:
        return None
    totals = {}
    for r in logs:
        try:
            d = datetime.date.fromisoformat(r["date"])
        except (KeyError, ValueError):
            continue
        if week_key(d) != wk:
            continue
        for i, g in enumerate(profile["goals"]):
            try:
                totals[g["name"]] = totals.get(g["name"], 0.0) + float(r[f"actual_{i}"])
            except (KeyError, ValueError):
                pass
    rows = []
    for goal, want in intentions.items():
        got = totals.get(goal, 0.0)
        acc = 100.0 if want == 0 else max(0.0, 100.0 - abs(want - got) / want * 100.0)
        rows.append({"goal": goal, "intended": want, "actual": round(got, 1),
                     "accuracy": round(acc, 0)})
    return rows


# Feature 9: weekly letter

def _letter_filename(date=None):
    return f"{LETTER_PREFIX}{week_key(date)}.txt"


def generate_weekly_letter(profile, logs):
    pe = get_persona(profile)
    name = pe["name"]
    last7 = logs[-7:]
    scores = _scores(last7)
    if not scores:
        return None
    avg = round(statistics.mean(scores), 1)

    # biggest win: goal hit most this week
    goals = profile["goals"]
    hit_counts = []
    for i, g in enumerate(goals):
        hits = sum(1 for r in last7 if _goal_hit(r, i))
        hit_counts.append((g["name"], hits))
    hit_counts.sort(key=lambda x: x[1], reverse=True)
    best_goal = hit_counts[0][0] if hit_counts else "your goals"
    worst_goal = hit_counts[-1][0] if hit_counts else "a goal"

    closings = {"firm": "Do the work.", "warm": "I'm proud of you. Keep going.",
                "fierce": "No excuses. Show up."}
    close = closings.get(pe["voice"], "Keep going.")

    lines = [
        f"A letter from {name}",
        f"Week of {datetime.date.today().isoformat()}",
        "",
        f"This week you averaged {avg} out of 100.",
        f"Your strongest goal was {best_goal}. That is the part of you that showed up.",
        f"The one that needs you next week is {worst_goal}.",
        "",
        f"Next week, pick {worst_goal} and protect it like the rest depend on it.",
        "",
        close,
        f"- {name}",
    ]
    return "\n".join(lines)


def write_weekly_letter(profile, logs):
    text = generate_weekly_letter(profile, logs)
    if not text:
        return None
    path = _letter_filename()
    osutil.atomic_write_text(path, text)
    return path


def latest_letter():
    files = sorted(glob.glob(f"{LETTER_PREFIX}*.txt"))
    if not files:
        return None, None
    path = files[-1]
    try:
        with open(path, encoding="utf-8") as f:
            return path, f.read()
    except OSError:
        return path, None


# Feature 13: scorecard

def export_scorecard(profile, logs):
    pe = get_persona(profile)
    path = f"{SCORECARD_PREFIX}{datetime.date.today().strftime('%Y-%m')}.txt"
    scores = _scores(logs)
    lines = ["=" * 50, "  ALTEREGO SCORE CARD", "=" * 50,
             f"  AlterEgo : {pe['name']}",
             f"  Traits   : {', '.join(pe['traits']) or 'n/a'}",
             f"  Date     : {datetime.date.today().isoformat()}", ""]
    if scores:
        last30 = scores[-30:]
        lines += [f"  Days logged    : {len(scores)}",
                  f"  30-day average : {round(statistics.mean(last30), 1)} / 100",
                  f"  Best day       : {max(last30)}",
                  f"  Worst day      : {min(last30)}"]
        dated = _dated(logs)
        lines.append(f"  Longest streak : {_longest_consec(dated)} days")
        goals = profile["goals"]
        gstats = []
        for i, g in enumerate(goals):
            hits = sum(1 for r in logs[-30:] if _goal_hit(r, i))
            gstats.append((g["name"], hits))
        if gstats:
            gstats.sort(key=lambda x: x[1], reverse=True)
            lines.append(f"  Top goal       : {gstats[0][0]} ({gstats[0][1]} hits)")
            lines.append(f"  Needs work     : {gstats[-1][0]} ({gstats[-1][1]} hits)")
    badges = profile.get("badges", [])
    if badges:
        lines += ["", "  Badges earned:"]
        for b in badges:
            lines.append(f"    - {badge_label(b)}")
    _path, letter = latest_letter()
    if letter:
        quote = letter.splitlines()[3] if len(letter.splitlines()) > 3 else ""
        if quote:
            lines += ["", f"  From {pe['name']}: \"{quote.strip()}\""]
    lines += ["", "=" * 50]
    text = "\n".join(lines)
    osutil.atomic_write_text(path, text)
    return path, text


# Feature 23: state audit

def audit_state(profile, logs, daemon_pid_file=None, log_file=None):
    issues = []
    # goals present
    if not profile.get("goals"):
        issues.append("profile has no goals")
    # personal bests vs goal names
    goal_names = {g["name"] for g in profile.get("goals", [])}
    for name in list(profile.get("personal_bests", {})):
        if name not in goal_names:
            issues.append(f"personal best for archived goal '{name}'")
    # leftover temp files from a crashed write
    leftovers = [f for f in os.listdir(".") if f.endswith(".tmp")]
    if leftovers:
        issues.append(f"{len(leftovers)} leftover .tmp file(s) cleaned up")
        for f in leftovers:
            try:
                os.remove(f)
            except OSError:
                pass
    # stale daemon pid
    if daemon_pid_file and os.path.exists(daemon_pid_file):
        try:
            with open(daemon_pid_file, encoding="utf-8") as f:
                pid = int(f.read().strip())
            if not osutil.pid_alive(pid):
                os.remove(daemon_pid_file)
                issues.append("stale daemon PID cleaned up")
        except (ValueError, OSError):
            pass
    return issues


# Feature 24: goal archiving

def archive_goal(profile, goal_index, logs):
    # move a goal out of the active list, keeping its final stats
    goals = profile["goals"]
    if not (0 <= goal_index < len(goals)):
        return None
    g = goals[goal_index]
    acts, last_active = [], None
    for r in logs:
        try:
            acts.append(float(r[f"actual_{goal_index}"]))
            last_active = r.get("date", last_active)
        except (KeyError, ValueError):
            pass
    record = {
        "name": g["name"], "unit": g["unit"],
        "days_tracked": len(acts),
        "lifetime_avg": round(statistics.mean(acts), 2) if acts else 0,
        "highest_day": max(acts) if acts else 0,
        "last_active": last_active,
    }
    profile.setdefault("archived_goals", []).append(record)
    goals.pop(goal_index)
    profile.get("personal_bests", {}).pop(g["name"], None)
    return record


# Feature 26: log integrity

def verify_log_integrity(logs):
    # return set of dates whose stored hash no longer matches the row
    tampered = set()
    for r in logs:
        stored = r.get("hash")
        if not stored:
            continue
        if row_hash(r.get("date", ""), r.get("score", ""), r.get("challenge", "")) != stored:
            tampered.add(r.get("date"))
    return tampered


# Feature 27: export / import backup

def export_backup(profile_file, log_file):
    name = f"alterego_backup_{datetime.date.today().isoformat()}.zip"
    with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as z:
        for f in (profile_file, log_file, INTENTIONS_FILE):
            if os.path.exists(f):
                z.write(f)
    return name


def import_backup(zip_path, profile_file):
    if not os.path.exists(zip_path):
        return False, "file not found"
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            if profile_file not in names:
                return False, "backup has no profile, not restoring"
            # validate the profile json before overwriting anything
            with z.open(profile_file) as f:
                data = json.loads(f.read().decode("utf-8"))
            if "goals" not in data:
                return False, "profile in backup looks invalid"
            z.extractall(".")
        return True, "restored"
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError) as exc:
        return False, str(exc)


# Feature 7: heatmap

def plot_heatmap(logs):
    # github-style year grid coloured by daily score
    if not logs:
        return None, "no data yet"
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        return None, "matplotlib not installed"

    by_date = {}
    for r in logs:
        try:
            by_date[datetime.date.fromisoformat(r["date"])] = float(r["score"])
        except (KeyError, ValueError):
            pass
    if not by_date:
        return None, "no dated entries"

    end = max(by_date)
    start = end - datetime.timedelta(days=363)
    # align start to a Monday
    start -= datetime.timedelta(days=start.weekday())

    def colour(score):
        if score is None:
            return "#2b2b2b"
        if score >= 80:
            return "#2FA572"
        if score >= 60:
            return "#2E75B6"
        if score >= 40:
            return "#E1A100"
        return "#C0392B"

    fig, ax = plt.subplots(figsize=(12, 2.4))
    d = start
    week = 0
    while d <= end:
        col = week
        row = d.weekday()
        ax.add_patch(Rectangle((col, 6 - row), 0.9, 0.9,
                               facecolor=colour(by_date.get(d)), edgecolor="none"))
        if d.weekday() == 6:
            week += 1
        d += datetime.timedelta(days=1)

    ax.set_xlim(0, week + 1); ax.set_ylim(0, 7)
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("AlterEgo Year Heatmap")
    fig.tight_layout()
    fig.savefig(HEATMAP_FILE, dpi=120, facecolor="white")
    plt.close(fig)
    return HEATMAP_FILE, None
