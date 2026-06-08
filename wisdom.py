"""
wisdom.py - the soul layer.

This is what makes the agent feel like a teacher and a friend instead of a
scoreboard. It carries a small library of principles (Stoic, Kaizen, growth,
self-compassion) and surfaces the right one for where you are right now. It
names the season of growth you're in, so the journey has a shape. And it speaks
in two voices at once: the teacher, who tells you the firm truth and pushes you
to your edge, and the friend, who takes you in their arms when the day was hard.

Pure functions and content. ASCII so the terminal stays happy; the GUI adds the
colour.
"""

import features as fx

# principles, grouped by the state you're in. picked to fit the moment, not at
# random, because the right words at the wrong time mean nothing.
PRINCIPLES = {
    "start": [
        ("A journey of a thousand miles begins with a single step.", "Lao Tzu"),
        ("You do not have to be great to start. You have to start to be great.", "Zig Ziglar"),
        ("Well begun is half done.", "Aristotle"),
    ],
    "struggle": [
        ("You cannot control what happened. You can control the next small step.", "Stoicism"),
        ("The impediment to action advances action. What stands in the way becomes the way.", "Marcus Aurelius"),
        ("Fall down seven times, stand up eight.", "Japanese proverb"),
        ("Be gentle with yourself. You are doing the best you can with what today gave you.", "Self-compassion"),
    ],
    "thrive": [
        ("When things go well, stay humble. Consistency, not intensity, is the secret.", "Kaizen"),
        ("Do not trust motivation. Build the habit that holds even on bad days.", "James Clear"),
        ("You are what you repeatedly do. Excellence is a habit.", "Aristotle"),
    ],
    "plateau": [
        ("Comfort is the quiet enemy of growth. A small disruption wakes you up.", "Growth mindset"),
        ("When the path feels flat, change the route, not the destination.", "Kaizen"),
    ],
    "recover": [
        ("Rest is not the opposite of progress. It is part of it.", "Self-compassion"),
        ("Even the moon takes nights off, and still it lights the sky.", "Proverb"),
        ("Almost everything will work again if you unplug it for a while, including you.", "Anne Lamott"),
    ],
    "neutral": [
        ("Small steps, repeated, become a different life.", "Kaizen"),
        ("Discipline is choosing what you want most over what you want now.", "Stoicism"),
        ("We are what we repeatedly do.", "Will Durant"),
        ("How you do the small days is how you do the big ones.", "Proverb"),
    ],
}

SEASONS = {
    "first_steps": ("First Steps", "The beginning is the most honest part. Just keep showing up."),
    "building":    ("Building Season", "Quiet, unglamorous work. This is where the foundation is poured."),
    "thriving":    ("Thriving Season", "You're in flow. Enjoy it, and stay humble enough to keep it."),
    "plateau":     ("The Plateau", "Steady but flat. Comfortable. Time to change something on purpose."),
    "dip":         ("The Dip", "Things are sliding. Not a failure, a signal. Adjust and hold on."),
    "rebuilding":  ("Rebuilding Season", "You're climbing back. Be patient. Roots grow before the tree shows."),
}


def _scores(logs):
    out = []
    for r in logs:
        try:
            out.append(float(r["score"]))
        except (KeyError, TypeError, ValueError):
            pass
    return out


def _state(profile, logs):
    # which bucket of life are you in right now
    profile = profile or {}
    if profile.get("recovery_mode"):
        return "recover"
    if fx.detect_burnout_risk(profile, logs)[0]:
        return "recover"
    s = _scores(logs)
    if len(s) < 3:
        return "start"
    if fx.detect_plateau(logs):
        return "plateau"
    if all(x < 40 for x in s[-3:]):
        return "struggle"
    import statistics
    if statistics.mean(s[-3:]) >= 75:
        return "thrive"
    return "neutral"


def principle_for_state(profile, logs):
    import datetime
    bucket = _state(profile, logs)
    pool = PRINCIPLES.get(bucket, PRINCIPLES["neutral"])
    idx = abs(hash("principle" + bucket + datetime.date.today().isoformat())) % len(pool)
    text, who = pool[idx]
    return {"text": text, "who": who, "state": bucket}


def principle_of_the_day(date):
    pool = PRINCIPLES["neutral"]
    return pool[abs(hash("pod" + str(date))) % len(pool)]


def growth_season(profile, logs):
    profile = profile or {}
    s = _scores(logs)
    if len(s) < 3:
        return SEASONS["first_steps"]
    if profile.get("recovery_mode"):
        return SEASONS["rebuilding"]
    if fx.detect_plateau(logs):
        return SEASONS["plateau"]
    import statistics
    recent = statistics.mean(s[-3:])
    earlier = statistics.mean(s[-6:-3]) if len(s) >= 6 else recent
    if recent >= 75 and recent >= earlier:
        return SEASONS["thriving"]
    if recent < earlier - 8:
        return SEASONS["dip"]
    if recent < 45:
        return SEASONS["rebuilding"]
    return SEASONS["building"]


# the two voices. the teacher pushes you to your edge, the friend holds you.
# every check-in hears both, because real growth needs both.

_TEACHER = {
    "hard": [
        "The standard does not move because today was heavy. Tomorrow you meet it again.",
        "Feel the disappointment, then use it. That sting is information, not a verdict.",
        "You know what you have to do. The hard day does not change the work.",
    ],
    "mid": [
        "Good is the enemy of your best. Close the last bit of the gap.",
        "You left something on the table today. Tomorrow, take it.",
        "Solid. Now do it again when you don't feel like it. That is the real test.",
    ],
    "good": [
        "This is your floor, not your ceiling. Build the next step from here.",
        "Excellent. Now protect this. The hardest day to show up is the one after a win.",
        "You proved you can. Tomorrow, prove it wasn't luck.",
    ],
}

_FRIEND = {
    "hard": [
        "And listen, you still showed up, and that counts more than the number. I've got you.",
        "Today was hard and that is allowed. Rest tonight. I am not going anywhere.",
        "Be kind to yourself. One rough day does not undo who you are becoming.",
    ],
    "mid": [
        "You're closer than you think, honestly. I see the effort even when the score doesn't.",
        "Proud of you for being here. A little more tomorrow, no pressure.",
        "This is a good, ordinary day, and ordinary days are what build everything.",
    ],
    "good": [
        "And hey, take a second to actually feel this one. You earned it.",
        "I'm proud of you. Not for the number, for the showing up that made it.",
        "Look how far you've come. Hold onto this feeling for the harder days.",
    ],
}


def dual_voice(profile, score, stance, date=""):
    # returns (teacher_line, friend_line). band by score, with grace/recover
    # always treated tenderly.
    if stance in ("grace", "recover") or score < 40:
        band = "hard"
    elif score >= 80:
        band = "good"
    else:
        band = "mid"
    t = _TEACHER[band]; f = _FRIEND[band]
    ti = abs(hash("t" + band + str(date))) % len(t)
    fi = abs(hash("f" + band + str(date))) % len(f)
    return t[ti], f[fi]


def identity_line(profile):
    # reinforce who they said they're becoming
    ident = ((profile or {}).get("identity") or "").strip()
    if not ident:
        return None
    return f"Remember: you are becoming {ident}."
