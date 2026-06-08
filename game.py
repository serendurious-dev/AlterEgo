"""
game.py - the fun layer.

Self improvement is easier when it doesn't feel like homework. This turns each
check-in into a little game: you earn XP, level up, build combos, fight the
Procrastination Monster, and pull a random reward. There are jokes and fortunes
too, because sometimes you just need a reason to smile, not another lecture.

Pure functions and content packs. Everything here is ASCII so it prints fine in
a plain terminal; the GUI adds the colour and the confetti.
"""

# titles you earn as you level up. (min_level, title)
TITLES = [
    (1,  "Novice"),
    (2,  "Apprentice"),
    (4,  "Disciplined"),
    (7,  "Focused"),
    (11, "Relentless"),
    (16, "Unstoppable"),
    (22, "Legend"),
    (30, "Ascended"),
]


def combo_multiplier(momentum):
    # consecutive good days stack a multiplier, up to 2x at a 10-day combo
    return round(1.0 + min(max(momentum, 0), 10) * 0.1, 2)


def xp_for_checkin(score, momentum=0, grace=False, draw_bonus=0):
    # a grace day still earns something. resting is part of the game.
    if grace:
        base = 20
    else:
        base = int(score * 0.5)            # 0..50 from the score
        base += momentum * 5               # streak bonus
    total = int(round(base * combo_multiplier(momentum))) + int(draw_bonus)
    return max(0, total)


def _xp_needed(level):
    # xp to go from this level to the next one. grows as you climb.
    return 100 + (level - 1) * 50


def level_from_xp(total_xp):
    # returns (level, title, xp_into_level, xp_needed_for_next)
    level, remaining = 1, max(0, int(total_xp))
    while remaining >= _xp_needed(level):
        remaining -= _xp_needed(level)
        level += 1
    return level, title_for_level(level), remaining, _xp_needed(level)


def title_for_level(level):
    title = TITLES[0][1]
    for lvl, name in TITLES:
        if level >= lvl:
            title = name
    return title


def xp_bar(total_xp, width=20):
    # a text progress bar toward the next level
    level, title, into, need = level_from_xp(total_xp)
    filled = int(round(into / need * width)) if need else 0
    bar = "#" * filled + "-" * (width - filled)
    return f"Lv {level} {title}  [{bar}] {into}/{need} XP"


# the Procrastination Monster: a recurring, low-stakes villain

def monster_line(score):
    if score >= 80:
        return "You slayed the Procrastination Monster today. It is hiding."
    if score >= 50:
        return "You and the Procrastination Monster fought to a draw. Rematch tomorrow."
    return "The Procrastination Monster won today. It is doing a little dance. Get it back tomorrow."


# variable reward: pull one card on each check-in. seeded by date so it is
# stable within a day but feels random day to day.

_DRAWS = [
    {"label": "Common: a nod from the universe", "flavor": "Keep going.", "xp": 5},
    {"label": "Common: pocket lint", "flavor": "Worthless, but it's yours.", "xp": 3},
    {"label": "Uncommon: small treasure", "flavor": "Found 15 bonus XP on the ground.", "xp": 15},
    {"label": "Rare: buried treasure", "flavor": "Jackpot. 30 bonus XP.", "xp": 30},
    {"label": "Buff: Momentum potion", "flavor": "Tomorrow you start with a win in your head.", "xp": 8},
    {"label": "Joke card", "flavor": "Redeem for one (1) groan.", "xp": 0},
    {"label": "Common: a high five", "flavor": "Leave you hanging? Never.", "xp": 5},
    {"label": "Uncommon: lucky coin", "flavor": "Heads, you win. Tails, you also win.", "xp": 12},
    {"label": "Rare: golden sticker", "flavor": "The good kind, from the good teacher.", "xp": 25},
    {"label": "Mystery: an unlabelled box", "flavor": "It rattles. You keep it.", "xp": 7},
]


def daily_draw(date):
    idx = abs(hash("draw" + str(date))) % len(_DRAWS)
    return _DRAWS[idx]


# laughs and small comforts

_JOKES = [
    "Why did the to-do list go to therapy? Too many unresolved issues.",
    "I told my goals a joke. They didn't laugh. Tough crowd.",
    "Procrastination is like a credit card: fun until the bill shows up.",
    "I'm reading a book on anti-gravity. Can't put it down.",
    "Discipline called. You left it on read.",
    "My alarm clock and I have trust issues now.",
    "I wanted to get in shape. Round is a shape, so technically a win.",
    "Tried to catch fog yesterday. Mist.",
    "I have a watch that only works at the gym. It runs on motivation.",
    "Future me sent a thank-you note. It's still loading.",
]

_FORTUNES = [
    "A future you is quietly cheering for this exact moment.",
    "Small steps still count as steps. Keep walking.",
    "Today's boring effort is tomorrow's quiet flex.",
    "You don't have to be great today. You have to be here.",
    "The streak you protect protects you back.",
    "Motivation is a guest. Discipline pays the rent.",
    "Rest is not quitting. Even the moon takes nights off.",
    "Done beats perfect, and done is on your side.",
]


def joke_of_the_day(date):
    return _JOKES[abs(hash("joke" + str(date))) % len(_JOKES)]


def fortune_of_the_day(date):
    return _FORTUNES[abs(hash("fortune" + str(date))) % len(_FORTUNES)]


def random_joke(seed=None):
    import random
    return random.choice(_JOKES) if seed is None else _JOKES[abs(hash(seed)) % len(_JOKES)]


# a curated quote of the day, separate from the silly stuff

_QUOTES = [
    ("The secret of getting ahead is getting started.", "Mark Twain"),
    ("You do not rise to the level of your goals, you fall to the level of your systems.", "James Clear"),
    ("Discipline is choosing between what you want now and what you want most.", "Abraham Lincoln"),
    ("Little by little, a little becomes a lot.", "Tanzanian proverb"),
    ("The man who moves a mountain begins by carrying away small stones.", "Confucius"),
    ("What you do every day matters more than what you do once in a while.", "Gretchen Rubin"),
    ("Fall seven times, stand up eight.", "Japanese proverb"),
    ("It always seems impossible until it is done.", "Nelson Mandela"),
    ("Motivation gets you going, but habit keeps you growing.", "Jim Rohn"),
    ("A year from now you will wish you had started today.", "Karen Lamb"),
]


def quote_of_the_day(date):
    text, who = _QUOTES[abs(hash("quote" + str(date))) % len(_QUOTES)]
    return text, who


# your AlterEgo grows a visible form as you level up

_AVATARS = [
    (1,  "\U0001F331", "Seedling"),    # sprout
    (2,  "\U0001F33F", "Sprout"),      # herb
    (4,  "\U0001FAB4", "Growing"),     # potted plant
    (7,  "\U0001F333", "Rooted"),      # tree
    (11, "⭐",      "Shining"),    # star
    (16, "\U0001F525", "Blazing"),     # fire
    (22, "\U0001F451", "Legendary"),   # crown
]


def avatar_for_level(level):
    # returns (glyph, label). the glyph is for the GUI, the label is safe anywhere.
    glyph, label = _AVATARS[0][1], _AVATARS[0][2]
    for lvl, g, lb in _AVATARS:
        if level >= lvl:
            glyph, label = g, lb
    return glyph, label


# ----- retention helpers: keep people from bouncing -----

# progressive disclosure. a new user sees a calm handful of screens; the rest
# unlock as they level up, so the app never dumps all of itself on day one.
SCREEN_UNLOCKS = {
    "Home": 1, "Check-in": 1, "Dashboard": 1, "Goals": 1, "Reminder": 1,
    "Badges": 2, "Insights": 2,
    "History": 3, "Reflections": 3, "Letter": 3,
    "Focus": 4, "Patterns": 4,
    "Event Log": 5,
}


def is_unlocked(screen, level):
    return level >= SCREEN_UNLOCKS.get(screen, 1)


def newly_unlocked(level):
    # screens that unlock exactly at this level (for the celebration)
    return [s for s, lvl in SCREEN_UNLOCKS.items() if lvl == level]


def next_unlock(level):
    # the nearest still-locked screen, or None if everything is open
    pending = [(lvl, s) for s, lvl in SCREEN_UNLOCKS.items() if lvl > level]
    if not pending:
        return None
    lvl, screen = min(pending)
    return {"screen": screen, "level": lvl}


def protected_streak(log_dates, freeze_dates):
    # consecutive days ending at the last entry, where a frozen day counts as
    # covered. this is why one missed day doesn't wipe your streak.
    import datetime
    days = sorted(set(log_dates))
    if not days:
        return 0
    covered = set(days) | set(freeze_dates)
    d = days[-1]
    streak = 0
    while d in covered:
        streak += 1
        d = d - datetime.timedelta(days=1)
    return streak


def days_since_last(log_dates, today):
    if not log_dates:
        return None
    return (today - max(log_dates)).days


def comeback_message(name, days):
    # warm, no guilt. shame is the main reason lapsed users never return.
    # a single missed day is handled quietly by a streak freeze, so only speak
    # up once someone has been away a couple of days or more.
    if days is None or days < 3:
        return None
    return (f"Welcome back. It's been {days} days, and that is completely fine. "
            f"{name} did not keep score while you were gone. Let's just start again, today.")


def next_milestone(profile, logs):
    # the nearest reward to chase, so there is always a near-term pull
    xp = int(profile.get("xp", 0))
    level, _title, into, need = level_from_xp(xp)
    items = [{"kind": "level", "label": f"Level {level + 1}", "remaining": need - into,
              "unit": "XP"}]
    nu = next_unlock(level)
    if nu:
        items.append({"kind": "unlock", "label": f"Unlock {nu['screen']}",
                      "remaining": nu["level"] - level, "unit": "levels"})
    days = len(logs)
    nxt = ((days // 10) + 1) * 10
    items.append({"kind": "days", "label": f"{nxt} days logged",
                  "remaining": nxt - days, "unit": "days"})
    return items
