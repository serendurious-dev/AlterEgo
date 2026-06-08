"""
coaching.py - the decision layer (the part that actually thinks).

Everything else in the project measures. This decides how to treat you today:
push you, hold steady, celebrate, give you grace, or help you recover. It reads
every signal (energy, mood, score, streak, burnout, recovery, the recent trend)
and then explains its reasoning in plain language, in your AlterEgo's voice.

This is what turns a tracker into an agent. It observes, reasons, and decides,
and it tells you why. It also knows when what you did was enough, so it can stop
pushing a person who is already running on empty.
"""

import statistics

import features as fx

STANCES = ["push", "steady", "celebrate", "grace", "recover"]


def capacity_expected(energy):
    # a fair day given how much you actually had in the tank.
    # energy 5 -> ~80, energy 3 -> ~48, energy 1 -> ~16.
    cap = max(1, min(5, int(energy or 3))) / 5.0
    return round(cap * 100 * 0.8, 1)


def did_enough(energy, score, streak_alive=False, grace=False):
    # three ways a day can count as enough, in order of meaning. returns
    # (enough, basis) where basis explains which one applied.
    if grace:
        return True, "grace"
    if int(energy or 3) <= 2 and score > 0:
        return True, "showed_up"          # depleted but still here
    if score >= capacity_expected(energy):
        return True, "capacity"           # met what today allowed
    if streak_alive and score >= 50:
        return True, "streak"             # kept the chain alive
    if score >= 70:
        return True, "outcome"            # just a good day
    return False, "short"


def _trend(logs, n=7):
    s = [float(r["score"]) for r in logs[-n:] if r.get("score")]
    if len(s) < 3:
        return "flat"
    if s[-1] > s[0] + 8:
        return "improving"
    if s[-1] < s[0] - 8:
        return "declining"
    return "flat"


def daily_signals(profile, logs, energy, mood, score, streaks):
    burnout, _reason = fx.detect_burnout_risk(profile, logs)
    return {
        "energy": int(energy or 3), "mood": int(mood or 3), "score": score,
        "momentum": streaks.get("momentum", 0), "log_streak": streaks.get("log_streak", 0),
        "recovery": bool(profile.get("recovery_mode")),
        "burnout": burnout, "plateau": fx.detect_plateau(logs),
        "trend": _trend(logs), "expected": capacity_expected(energy),
    }


def progress_note(profile, logs, min_days=10):
    # encouragement with memory: find a goal you've clearly grown at.
    if len(logs) < min_days:
        return None
    for i, g in enumerate(profile["goals"]):
        vals = []
        for r in logs:
            try:
                vals.append(float(r[f"actual_{i}"]))
            except (KeyError, ValueError):
                pass
        if len(vals) < min_days:
            continue
        third = max(2, len(vals) // 3)
        early = max(vals[:third]); recent = max(vals[-third:])
        if recent >= early * 1.3 and recent > early:
            return (f"{g['name']}: your best used to be {early:g} {g['unit']}, "
                    f"now it's {recent:g}. You've come a long way.")
    return None


def coaching_state(profile, logs, energy, mood, score, streaks, grace=False):
    """
    The brain. Returns a coherent read of today:
      stance     one of push / steady / celebrate / grace / recover
      intensity  gentle / firm / hard
      enough     did today count as enough
      basis      why it counted (capacity / showed_up / streak / outcome / grace)
      reasons    2-4 plain-language lines, the thinking out loud
      headline   one voiced line in the persona
      shift      True if this stance is a meaningful change from last time
    """
    sig = daily_signals(profile, logs, energy, mood, score, streaks)
    pe = fx.get_persona(profile)
    enough, basis = did_enough(sig["energy"], score,
                               streak_alive=sig["momentum"] > 0, grace=grace)

    # decide the stance, most protective conditions first
    if grace:
        stance, intensity = "grace", "gentle"
    elif sig["burnout"]:
        stance, intensity = "grace", "gentle"
    elif sig["energy"] <= 2 and sig["mood"] <= 2:
        stance, intensity = "grace", "gentle"
    elif sig["recovery"]:
        stance, intensity = "recover", "gentle"
    elif score >= 80 and sig["energy"] >= 3:
        stance, intensity = "celebrate", "firm"
    elif sig["energy"] >= 4 and score < 60:
        stance, intensity = "push", "hard"
    elif sig["energy"] <= 2 and score < sig["expected"]:
        stance, intensity = "grace", "gentle"
    elif sig["plateau"] and sig["energy"] >= 3:
        stance, intensity = "push", "firm"
    elif sig["trend"] == "declining" and sig["energy"] >= 3:
        stance, intensity = "push", "firm"
    else:
        stance, intensity = "steady", "firm"

    reasons = _build_reasons(pe, sig, score, stance, enough, basis)
    progress = progress_note(profile, logs)
    if progress:
        reasons.append(progress)

    mode = {"push": "push", "celebrate": "celebrate",
            "grace": "recovery", "recover": "recovery"}.get(stance, "standard")
    tone, _ = _tone_for(score)
    headline = fx.persona_message(profile, score, tone, mode)

    shift = stance != profile.get("last_stance")
    return {"stance": stance, "intensity": intensity, "enough": enough,
            "basis": basis, "reasons": reasons, "headline": headline, "shift": shift}


def _tone_for(score):
    if score >= 80:
        return "EXCELLENT", None
    if score >= 60:
        return "KEEP GOING", None
    if score >= 40:
        return "WAKE UP", None
    return "ROCK BOTTOM", None


UI_MODES = ["auto", "calm", "standard", "rich"]

# things worth surfacing when the user is thriving and has room for more
_RICH_SUGGESTIONS = [
    ("Patterns", "See what the agent has learned about your habits over time."),
    ("Insights", "Find out which goal actually moves your score the most."),
    ("Letter", "Read this week's letter from your AlterEgo."),
    ("Badges", "Check which achievements you're closing in on."),
]


def recent_state(logs, n=4):
    # average energy and mood over the last few logged days (defaults to neutral)
    es, ms = [], []
    for r in logs[-n:]:
        try:
            es.append(float(r.get("energy") or 0))
        except ValueError:
            pass
        try:
            ms.append(float(r.get("mood") or 0))
        except ValueError:
            pass
    e = statistics.mean([x for x in es if x > 0]) if any(x > 0 for x in es) else 3.0
    m = statistics.mean([x for x in ms if x > 0]) if any(x > 0 for x in ms) else 3.0
    return e, m


def ui_density(profile, logs):
    """
    Decide how much of the app to show today: calm, standard, or rich.

    Nothing is ever removed. This only changes what steps forward. When the
    user is depleted or overwhelmed we keep it light; when they're thriving we
    surface the deeper features. A manual ui_mode setting always wins.
    """
    override = profile.get("ui_mode", "auto")
    if override in ("calm", "standard", "rich"):
        return {"mode": override, "reason": "you chose this view", "auto": False,
                "suggestion": _suggestion(logs) if override == "rich" else None}

    if fx.detect_burnout_risk(profile, logs)[0] or profile.get("recovery_mode"):
        return {"mode": "calm", "reason": "you seem to need a lighter day",
                "auto": True, "suggestion": None}

    e, m = recent_state(logs)
    if (e + m) / 2 <= 2.3:
        return {"mode": "calm", "reason": "your energy has been low lately",
                "auto": True, "suggestion": None}

    trailing_good = 0
    for r in reversed(logs):
        try:
            if float(r["score"]) >= 60:
                trailing_good += 1
            else:
                break
        except (KeyError, ValueError):
            break
    if e >= 4 and trailing_good >= 3:
        return {"mode": "rich", "reason": "you're on a roll, here's more to explore",
                "auto": True, "suggestion": _suggestion(logs)}

    return {"mode": "standard", "reason": "", "auto": True, "suggestion": None}


def _suggestion(logs):
    idx = abs(hash("rich" + str(len(logs)))) % len(_RICH_SUGGESTIONS)
    screen, text = _RICH_SUGGESTIONS[idx]
    return {"screen": screen, "text": text}


def _build_reasons(pe, sig, score, stance, enough, basis):
    out = []
    e = sig["energy"]
    # how it's reading your capacity today
    if e <= 2:
        out.append(f"Your energy was {e}/5, so I'm not measuring you against a "
                   f"perfect day. Today's fair line was about {sig['expected']:.0f}.")
    elif e >= 4:
        out.append(f"You had real energy today ({e}/5). That changes what I expect.")

    # the enough verdict, phrased by how it was earned
    if enough:
        if basis == "showed_up":
            out.append("You were running low and you showed up anyway. "
                       "That counts more than the number.")
        elif basis == "capacity":
            out.append("You met what today actually allowed. That is a real win.")
        elif basis == "streak":
            out.append("Not your best, but you kept the momentum alive. That matters.")
        elif basis == "grace":
            out.append("Today is a rest day. Nothing to prove, just be here.")
        else:
            out.append("Plainly a good day. Enjoy it.")
    else:
        if stance == "push" and e >= 4:
            out.append("You had the energy and the day still got away. "
                       "I'm not letting that slide.")
        else:
            out.append("Today fell short of what you're capable of. We fix one thing tomorrow.")

    # streak / momentum context
    if sig["momentum"] >= 3:
        out.append(f"That's {sig['momentum']} good days in a row. You're building something.")
    elif sig["plateau"]:
        out.append("You've been steady but flat for a while. Time to shake the routine.")
    elif sig["trend"] == "improving":
        out.append("Your last several days are trending up. Keep the line going.")
    return out
