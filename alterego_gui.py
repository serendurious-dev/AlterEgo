"""Desktop UI. Logic lives in alterego.py / features.py, this file draws screens."""

import os
import json
import time
import datetime
import threading

import customtkinter as ctk

import alterego as ae

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# bright, modern semantic colours (tailwind-ish). these stay fixed.
GOOD   = "#22C55E"
WARN   = "#F59E0B"
BAD    = "#EF4444"
MUTED  = "gray60"
INK    = "#0F172A"     # near-black for text on bright panels

# pickable accent themes. ACCENT/ACCENT2 get swapped in by apply_theme.
THEMES = {
    "Ocean":  ("#3B82F6", "#0EA5E9"),
    "Grape":  ("#8B5CF6", "#A855F7"),
    "Sunset": ("#F97316", "#FB7185"),
    "Forest": ("#10B981", "#34D399"),
    "Rose":   ("#EC4899", "#F472B6"),
    "Gold":   ("#EAB308", "#F59E0B"),
}
ACCENT, ACCENT2 = THEMES["Ocean"]
TONE_COLOR = {"EXCELLENT": GOOD, "KEEP GOING": "#3B82F6", "WAKE UP": WARN, "ROCK BOTTOM": BAD}

# a palette for the dashboard stat cards so they pop instead of all-grey
CARD_COLORS = ["#3B82F6", "#22C55E", "#F59E0B", "#8B5CF6", "#EC4899", "#0EA5E9"]

MOOD_FACES = {1: "\U0001F622", 2: "\U0001F61F", 3: "\U0001F610", 4: "\U0001F642", 5: "\U0001F601"}


def apply_theme(name):
    global ACCENT, ACCENT2, TONE_COLOR
    ACCENT, ACCENT2 = THEMES.get(name, THEMES["Ocean"])
    TONE_COLOR["KEEP GOING"] = ACCENT


def _score_color(score):
    if score >= 80:
        return GOOD
    if score >= 60:
        return ACCENT
    if score >= 40:
        return WARN
    return BAD


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AlterEgo Agent")
        self.geometry("1000x680")
        self.minsize(900, 600)

        self.profile = ae._load_profile_safe()
        if self.profile is not None:
            ae._migrate_profile(self.profile)
            apply_theme(self.profile.get("theme", "Ocean"))
        self.focus_sessions = 0          # counts Focus Mode sessions this run
        self.pending = None              # holds a check-in waiting for its reflection

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        if self.profile is None:
            self._disable_nav()
            self.show_setup()
        else:
            self._run_audit()
            self.show_ritual()           # ritual card -> home
            self.after(400, self._maybe_show_letter)

    # sidebar

    def _build_sidebar(self):
        # tear down any previous sidebar so rebuilds don't stack stale buttons
        old = getattr(self, "_sidebar", None)
        if old is not None:
            old.destroy()
        bar = ctk.CTkFrame(self, width=210, corner_radius=0)
        bar.grid(row=0, column=0, sticky="nsew")
        bar.grid_rowconfigure(2, weight=1)
        self._sidebar = bar

        # bright header panel with the evolving avatar + level
        head = ctk.CTkFrame(bar, fg_color=ACCENT, corner_radius=12)
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=(14, 8))
        pe = ae.get_persona(self.profile) if self.profile else {"name": "your ideal self", "traits": []}
        lvl = ae.level_from_xp(self.profile.get("xp", 0))[0] if self.profile else 1
        glyph, av_label = ae.avatar_for_level(lvl)
        ctk.CTkLabel(head, text=glyph, font=ctk.CTkFont(size=40)).pack(pady=(10, 0))
        ctk.CTkLabel(head, text=pe["name"], font=ctk.CTkFont(size=15, weight="bold"),
                     text_color="white").pack()
        ctk.CTkLabel(head, text=f"Level {lvl} {av_label}", font=ctk.CTkFont(size=11),
                     text_color="white").pack(pady=(0, 2))
        if self.profile:
            _, _, into, need = ae.level_from_xp(self.profile.get("xp", 0))
            self.xp_bar = ctk.CTkProgressBar(head, height=8, progress_color="white",
                                             fg_color=ACCENT2)
            self.xp_bar.set(into / need if need else 0)
            self.xp_bar.pack(fill="x", padx=14, pady=(2, 4))
            ctk.CTkLabel(head, text=f"{into}/{need} XP", font=ctk.CTkFont(size=9),
                         text_color="white").pack(pady=(0, 10))

        nav = ctk.CTkScrollableFrame(bar, fg_color="transparent")
        nav.grid(row=2, column=0, sticky="nsew", padx=4)
        self.nav_buttons = {}
        items = [
            ("Home",        "\U0001F3E0", self.show_home),
            ("Check-in",    "✅", self.show_checkin),
            ("Dashboard",   "\U0001F4CA", self.show_dashboard),
            ("Insights",    "\U0001F4A1", self.show_insights),
            ("Patterns",    "\U0001F9E0", self.show_patterns),
            ("Focus",       "⏱", self.show_focus),
            ("Reflections", "\U0001F4DD", self.show_reflections),
            ("Badges",      "\U0001F3C5", self.show_badges),
            ("Letter",      "✉", self.show_letter),
            ("History",     "\U0001F4C5", self.show_history),
            ("Goals",       "\U0001F3AF", self.show_goals),
            ("Event Log",   "\U0001F5C2", self.show_eventlog),
            ("Reminder",    "\U0001F514", self.show_reminder),
        ]
        level = ae.level_from_xp(self.profile.get("xp", 0))[0] if self.profile else 1
        for name, icon, cmd in items:
            if self.profile and ae.is_unlocked(name, level):
                b = ctk.CTkButton(nav, text=f"  {icon}  {name}", command=cmd, anchor="w",
                                  height=34, corner_radius=8, fg_color="transparent",
                                  text_color=("gray10", "gray90"), hover_color=ACCENT2)
                b.pack(fill="x", pady=2)
                self.nav_buttons[name] = b
            elif self.profile:
                need = ae.SCREEN_UNLOCKS.get(name, 1)
                b = ctk.CTkButton(nav, text=f"  \U0001F512  {name} (Lv {need})", anchor="w",
                                  height=34, corner_radius=8, fg_color="transparent",
                                  text_color=MUTED, hover_color="gray30", state="disabled")
                b.pack(fill="x", pady=2)
            else:
                # no profile yet (first run): nav is inert until setup is done
                b = ctk.CTkButton(nav, text=f"  {icon}  {name}", command=None, anchor="w",
                                  height=34, corner_radius=8, fg_color="transparent",
                                  text_color=MUTED, hover_color="gray30", state="disabled")
                b.pack(fill="x", pady=2)
                self.nav_buttons[name] = b

        foot = ctk.CTkFrame(bar, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=10, pady=8)
        ctk.CTkButton(foot, text="\U0001F36A  Fortune cookie", height=30, fg_color=ACCENT2,
                      hover_color=ACCENT, command=self._fortune_cookie).pack(fill="x", pady=(0, 6))
        row = ctk.CTkFrame(foot, fg_color="transparent"); row.pack(fill="x")
        ctk.CTkLabel(row, text="Theme", font=ctk.CTkFont(size=11), text_color=MUTED
                     ).pack(side="left", padx=(4, 4))
        theme = ctk.CTkOptionMenu(row, values=list(THEMES), width=110, command=self._set_theme)
        theme.set(self.profile.get("theme", "Ocean") if self.profile else "Ocean")
        theme.pack(side="left")
        mode = ctk.CTkOptionMenu(foot, values=["Dark", "Light", "System"], height=28,
                                 command=lambda m: ctk.set_appearance_mode(m.lower()))
        mode.pack(fill="x", pady=(6, 0)); mode.set("Dark")

    def _set_theme(self, name):
        apply_theme(name)
        if self.profile:
            self.profile["theme"] = name
            ae._save_profile(self.profile)
        self._build_sidebar()
        self.show_home()

    def _fortune_cookie(self):
        # a quick laugh, any time you want one
        import random
        msg = ae.random_joke() if random.random() < 0.5 else \
            ae.fortune_of_the_day(str(random.random()))
        self._toast(msg)

    def _express_checkin(self):
        # the 10-second path: one tap, no per-goal numbers
        if ae._already_logged(datetime.date.today().isoformat()):
            self._toast("You already checked in today.")
            return
        top = ctk.CTkToplevel(self); top.title("Quick check-in"); top.geometry("440x230")
        top.transient(self); top.grab_set()
        ctk.CTkLabel(top, text="How did today go overall?",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(20, 10))
        labels = [(1, "\U0001F622 rough"), (2, "\U0001F61F meh"), (3, "\U0001F610 okay"),
                  (4, "\U0001F642 good"), (5, "\U0001F601 great")]
        rowf = ctk.CTkFrame(top, fg_color="transparent"); rowf.pack(pady=10)

        def pick(level):
            top.destroy()
            res = ae.express_apply(self.profile, level)
            self._build_sidebar()
            if res["game"]["leveled_up"]:
                self.after(120, self._confetti)
            self._toast(f"Logged! Score {res['score']}/100, +{res['game']['xp_gained']} XP.\n"
                        f"{res['headline']}\nShowing up on a hard day still counts.")
            self.show_home()

        for lvl, txt in labels:
            ctk.CTkButton(rowf, text=txt, width=80, fg_color=ACCENT, hover_color=ACCENT2,
                          command=lambda l=lvl: pick(l)).pack(side="left", padx=4)
        ctk.CTkLabel(top, text="For low-energy days. The habit matters more than the number.",
                     text_color=MUTED, font=ctk.CTkFont(size=11)).pack(pady=(14, 0))

    def _disable_nav(self):
        for b in self.nav_buttons.values():
            b.configure(state="disabled")

    def _enable_nav(self):
        for b in self.nav_buttons.values():
            b.configure(state="normal")

    def _highlight(self, name):
        for label, b in self.nav_buttons.items():
            b.configure(fg_color=ACCENT if label == name else "transparent")

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    def _header(self, title, subtitle=""):
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        # title + a coloured accent rule, kept inside row 0 so screens can still
        # use row 2 for their body
        titlebox = ctk.CTkFrame(frame, fg_color="transparent")
        titlebox.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(titlebox, text=title, font=ctk.CTkFont(size=27, weight="bold"),
                     anchor="w", text_color=ACCENT).pack(anchor="w")
        rule = ctk.CTkFrame(titlebox, height=3, width=64, fg_color=ACCENT, corner_radius=2)
        rule.pack(anchor="w", pady=(3, 0))
        if subtitle:
            ctk.CTkLabel(frame, text=subtitle, font=ctk.CTkFont(size=13),
                         text_color=MUTED, anchor="w").grid(row=1, column=0, sticky="w",
                                                            pady=(6, 0))
        return frame

    def _run_audit(self):
        issues = ae.audit_state(self.profile, ae._read_logs(), ae.DAEMON_PID, ae.LOG_FILE)
        self.audit_issues = issues

    # ritual opening screen (Feature 18)

    def show_ritual(self):
        self._clear_content()
        logs = ae._read_logs()
        pe = ae.get_persona(self.profile)
        lvl = ae.level_from_xp(self.profile.get("xp", 0))[0]
        glyph, _ = ae.avatar_for_level(lvl)
        card = ctk.CTkFrame(self.content, fg_color=ACCENT, corner_radius=18)
        card.grid(row=0, column=0, sticky="nsew", padx=70, pady=70)
        card.grid_columnconfigure(0, weight=1); card.grid_rowconfigure((0, 5), weight=1)
        ctk.CTkLabel(card, text=glyph, font=ctk.CTkFont(size=60)).grid(row=1, column=0)
        ctk.CTkLabel(card, text=datetime.date.today().strftime("%A, %B %d"),
                     font=ctk.CTkFont(size=16), text_color="white").grid(row=2, column=0)
        ctk.CTkLabel(card, text=ae.smart_greeting(self.profile, logs),
                     font=ctk.CTkFont(size=22, weight="bold"), wraplength=540,
                     justify="center", text_color="white").grid(row=3, column=0, pady=14, padx=20)
        if logs:
            ctk.CTkLabel(card, text=f"Yesterday: {float(logs[-1]['score']):.0f}. {pe['name']} remembers.",
                         text_color="white").grid(row=4, column=0)
        self.after(2200, self.show_home)

    # home: the vibrant landing screen

    def show_home(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Home")
        self._clear_content()
        logs = ae._read_logs()
        pe = ae.get_persona(self.profile)
        lvl, title, into, need = ae.level_from_xp(self.profile.get("xp", 0))
        glyph, av_label = ae.avatar_for_level(lvl)
        streaks = ae.compute_streaks(logs)

        density = ae.ui_density(self.profile, logs)
        mode = density["mode"]

        root = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        root.grid(row=0, column=0, sticky="nsew")
        root.grid_columnconfigure(0, weight=1)

        # view-mode control: Auto adapts to your state, or pin it yourself
        ctl = ctk.CTkFrame(root, fg_color="transparent"); ctl.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(ctl, text="View", text_color=MUTED, font=ctk.CTkFont(size=11)
                     ).pack(side="left", padx=(4, 6))
        seg = ctk.CTkSegmentedButton(ctl, values=["Auto", "Calm", "Standard", "Rich"],
                                     command=self._set_ui_mode)
        seg.set(self.profile.get("ui_mode", "auto").capitalize()); seg.pack(side="left")
        if density["auto"] and density["reason"]:
            ctk.CTkLabel(ctl, text="  " + density["reason"], text_color=MUTED,
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=6)

        # gentle comeback banner if they've been away
        gap = ae.days_since_last([d for d in (ae._safe_date(r) for r in logs) if d],
                                 datetime.date.today())
        cm = ae.comeback_message(pe["name"], gap) if gap else None
        if cm:
            cb = ctk.CTkFrame(root, fg_color=GOOD, corner_radius=14); cb.pack(fill="x", pady=(0, 12))
            ctk.CTkLabel(cb, text="\U0001F33B  " + cm, text_color="white", wraplength=720,
                         justify="left").pack(anchor="w", padx=16, pady=10)

        # hero banner (smaller and quieter in calm mode)
        hero = ctk.CTkFrame(root, fg_color=ACCENT, corner_radius=18)
        hero.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(hero, text=glyph, font=ctk.CTkFont(size=44 if mode == "calm" else 54)
                     ).pack(side="left", padx=(24, 10), pady=(14 if mode == "calm" else 20))
        col = ctk.CTkFrame(hero, fg_color="transparent"); col.pack(side="left", pady=16, anchor="w")
        ctk.CTkLabel(col, text=ae.smart_greeting(self.profile, logs),
                     font=ctk.CTkFont(size=20, weight="bold"), text_color="white",
                     wraplength=520, justify="left").pack(anchor="w")
        season_name, season_desc = ae.growth_season(self.profile, logs)
        ctk.CTkLabel(col, text=f"{pe['name']}  |  Level {lvl} {title} {av_label}  |  {season_name}",
                     font=ctk.CTkFont(size=13), text_color="white").pack(anchor="w", pady=(4, 0))
        if mode != "calm":
            bar = ctk.CTkProgressBar(col, height=10, progress_color="white", fg_color=ACCENT2)
            bar.set(into / need if need else 0); bar.pack(fill="x", pady=(8, 0))
            ctk.CTkLabel(col, text=f"{into}/{need} XP to level {lvl+1}", font=ctk.CTkFont(size=10),
                         text_color="white").pack(anchor="w")

        today = datetime.date.today().isoformat()

        # a principle for where you are right now (the teacher's lesson)
        pr = ae.principle_for_state(self.profile, logs)
        pcard = ctk.CTkFrame(root, fg_color=ACCENT2, corner_radius=14); pcard.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(pcard, text=f"“{pr['text']}”", font=ctk.CTkFont(size=14, slant="italic"),
                     text_color="white", wraplength=720, justify="left").pack(anchor="w", padx=16, pady=(12, 2))
        ctk.CTkLabel(pcard, text=f"- {pr['who']}", text_color="white",
                     font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=(0, 6))
        ctk.CTkLabel(pcard, text=season_desc, text_color="white", wraplength=720,
                     font=ctk.CTkFont(size=11), justify="left").pack(anchor="w", padx=16, pady=(0, 12))
        il = ae.identity_line(self.profile)
        if il:
            ctk.CTkLabel(root, text=il, font=ctk.CTkFont(size=13, slant="italic"),
                         text_color=ACCENT, wraplength=720).pack(anchor="w", pady=(0, 10))

        if mode == "calm":
            # keep it light: a soft note, the streak, and one easy action
            note = ctk.CTkFrame(root); note.pack(fill="x", pady=(0, 12))
            ctk.CTkLabel(note, text="Keeping it light today. Everything is still here whenever "
                                    "you want it, no rush.", text_color="gray80",
                         wraplength=700, justify="left").pack(anchor="w", padx=16, pady=12)
            eff = ae.effective_streak(self.profile, logs)
            ctk.CTkLabel(root, text=f"\U0001F525 {eff}-day streak, safe and sound.",
                         text_color=GOOD, font=ctk.CTkFont(size=14)).pack(pady=(0, 10))
            if not ae._already_logged(today):
                ctk.CTkButton(root, text="\U0001F680  Quick check-in (10 seconds)", height=52,
                              fg_color=ACCENT, hover_color=ACCENT2,
                              font=ctk.CTkFont(size=17, weight="bold"),
                              command=self._express_checkin).pack(fill="x", pady=6)
                ctk.CTkButton(root, text="Full check-in", height=36, fg_color="transparent",
                              text_color=ACCENT, hover_color=ACCENT2,
                              command=self.show_checkin).pack(fill="x", pady=2)
            else:
                ctk.CTkLabel(root, text="✅ You checked in today. That's enough.",
                             text_color=GOOD, font=ctk.CTkFont(size=15)).pack(pady=10)
            return

        # standard + rich: the full home
        chips = ctk.CTkFrame(root, fg_color="transparent"); chips.pack(fill="x", pady=(0, 14))
        flame = "\U0001F525" if streaks["log_streak"] >= 3 else "✨"
        avg = round(sum(float(r["score"]) for r in logs) / len(logs), 1) if logs else 0
        eff = ae.effective_streak(self.profile, logs)
        freezes = int(self.profile.get("streak_freezes", 0))
        data = [(f"{flame} {eff}", "day streak", CARD_COLORS[1]),
                (f"\U0001F9CA {freezes}", "freezes", CARD_COLORS[5]),
                (f"\U0001F4C8 {avg}", "lifetime avg", CARD_COLORS[0]),
                (f"\U0001F3C5 {len(self.profile.get('badges', []))}", "badges", CARD_COLORS[3])]
        for i, (big, small, color) in enumerate(data):
            c = ctk.CTkFrame(chips, fg_color=color, corner_radius=14)
            c.grid(row=0, column=i, padx=5, sticky="nsew"); chips.grid_columnconfigure(i, weight=1)
            ctk.CTkLabel(c, text=big, font=ctk.CTkFont(size=22, weight="bold"),
                         text_color="white").pack(padx=16, pady=(12, 0))
            ctk.CTkLabel(c, text=small, text_color="white", font=ctk.CTkFont(size=11)).pack(padx=16, pady=(0, 12))

        # rich mode surfaces a deeper feature to explore
        if mode == "rich" and density.get("suggestion"):
            sg = density["suggestion"]
            rc = ctk.CTkFrame(root, fg_color=ACCENT2, corner_radius=14); rc.pack(fill="x", pady=(0, 14))
            ctk.CTkLabel(rc, text="\U0001F31F  You're thriving, here's something to explore",
                         text_color="white", font=ctk.CTkFont(size=14, weight="bold")
                         ).pack(anchor="w", padx=16, pady=(12, 2))
            ctk.CTkLabel(rc, text=sg["text"], text_color="white", wraplength=680,
                         justify="left").pack(anchor="w", padx=16)
            handler = self.nav_buttons.get(sg["screen"])
            cmd = handler.cget("command") if handler else None
            ctk.CTkButton(rc, text=f"Open {sg['screen']}", fg_color="white", text_color=INK,
                          hover_color=ACCENT, command=cmd if cmd else self.show_dashboard
                          ).pack(anchor="w", padx=16, pady=(8, 12))

        # what's next
        nxt = ctk.CTkFrame(root); nxt.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(nxt, text="\U0001F3AF  What's next", font=ctk.CTkFont(size=14, weight="bold")
                     ).pack(anchor="w", padx=16, pady=(12, 4))
        for m in ae.next_milestone(self.profile, logs):
            ctk.CTkLabel(nxt, text=f"  {m['remaining']} {m['unit']} to {m['label']}",
                         text_color="gray80").pack(anchor="w", padx=16, pady=1)
        nu = ae.next_unlock(lvl)
        if nu:
            ctk.CTkLabel(nxt, text=f"  \U0001F512 {nu['screen']} unlocks at Level {nu['level']}",
                         text_color=ACCENT).pack(anchor="w", padx=16, pady=(2, 12))
        else:
            ctk.CTkLabel(nxt, text="  Everything is unlocked. You went all the way.",
                         text_color=GOOD).pack(anchor="w", padx=16, pady=(2, 12))

        # primary action
        if ae._already_logged(today):
            ctk.CTkLabel(root, text="✅ You've checked in today. Nice.",
                         font=ctk.CTkFont(size=15), text_color=GOOD).pack(pady=10)
            ctk.CTkButton(root, text="View Dashboard", height=44, fg_color=ACCENT,
                          hover_color=ACCENT2, command=self.show_dashboard).pack(fill="x", pady=4)
        else:
            ctk.CTkButton(root, text="\U0001F680  Quick check-in (10 seconds)", height=40,
                          fg_color=ACCENT2, hover_color=ACCENT, command=self._express_checkin
                          ).pack(fill="x", pady=(6, 4))
            ctk.CTkButton(root, text="✅  Full check-in", height=52, fg_color=ACCENT,
                          hover_color=ACCENT2, font=ctk.CTkFont(size=17, weight="bold"),
                          command=self.show_checkin).pack(fill="x", pady=6)

    def _set_ui_mode(self, value):
        if self.profile is None:
            return
        self.profile["ui_mode"] = value.lower()
        ae._save_profile(self.profile)
        self.show_home()

    def _maybe_show_letter(self):
        # Feature 9: pop the weekly letter if there's an unread one
        path, text = ae.latest_letter()
        if not text or not path:
            return
        if path in self.profile.get("letters_read", []):
            return
        self._letter_popup(text, path)

    def _letter_popup(self, text, path):
        top = ctk.CTkToplevel(self)
        top.title("A letter from your AlterEgo")
        top.geometry("560x460")
        top.transient(self); top.grab_set()
        box = ctk.CTkTextbox(top, wrap="word", font=ctk.CTkFont(size=13))
        box.pack(fill="both", expand=True, padx=16, pady=16)
        box.insert("1.0", text); box.configure(state="disabled")

        def close():
            self.profile.setdefault("letters_read", []).append(path)
            ae._save_profile(self.profile)
            top.destroy()
        ctk.CTkButton(top, text="Close", command=close).pack(pady=(0, 14))

    # first-run setup (Feature 1: persona step added)

    def show_setup(self):
        self._clear_content()
        frame = self._header("Build your AlterEgo",
                             "Three goals, then shape the ideal self you'll measure against.")
        body = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", pady=(16, 0))
        frame.grid_rowconfigure(2, weight=1)

        # quick-start templates so you're not staring at a blank form
        tpl = ctk.CTkFrame(body, fg_color=ACCENT, corner_radius=12)
        tpl.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(tpl, text="Quick start (optional): fill the form with a preset",
                     text_color="white", font=ctk.CTkFont(size=13, weight="bold")
                     ).pack(anchor="w", padx=12, pady=(10, 4))
        trow = ctk.CTkFrame(tpl, fg_color="transparent"); trow.pack(fill="x", padx=12, pady=(0, 10))
        for name in ae.GOAL_TEMPLATES:
            ctk.CTkButton(trow, text=name, width=90, fg_color="white", text_color=INK,
                          hover_color=ACCENT2,
                          command=lambda n=name: self._apply_template(n)).pack(side="left", padx=4)

        self.setup_rows = []
        for i in range(1, 4):
            card = ctk.CTkFrame(body)
            card.pack(fill="x", pady=8)
            ctk.CTkLabel(card, text=f"\U0001F3AF  Goal {i}", font=ctk.CTkFont(size=15, weight="bold")
                         ).grid(row=0, column=0, columnspan=5, padx=12, pady=(10, 4), sticky="w")
            name = ctk.CTkEntry(card, placeholder_text="Description (e.g. Study)", width=200)
            unit = ctk.CTkEntry(card, placeholder_text="Unit (hours/times)", width=140)
            target = ctk.CTkEntry(card, placeholder_text="Target", width=90)
            weight = ctk.CTkOptionMenu(card, values=["1", "2", "3"], width=80); weight.set("2")
            baseline = ctk.CTkEntry(card, placeholder_text="Baseline", width=90)
            for col, (lbl, w) in enumerate([("Goal", name), ("Unit", unit), ("Target", target),
                                            ("Weight", weight), ("Baseline", baseline)]):
                ctk.CTkLabel(card, text=lbl).grid(row=1, column=col, padx=8, sticky="w")
                w.grid(row=2, column=col, padx=8, pady=(0, 6))
            why = ctk.CTkEntry(card, placeholder_text="Why does this matter to you? (optional)")
            why.grid(row=3, column=0, columnspan=5, padx=8, pady=(0, 12), sticky="ew")
            self.setup_rows.append((name, unit, target, weight, baseline, why))

        # persona card
        pcard = ctk.CTkFrame(body)
        pcard.pack(fill="x", pady=8)
        ctk.CTkLabel(pcard, text="Your AlterEgo", font=ctk.CTkFont(size=15, weight="bold")
                     ).grid(row=0, column=0, columnspan=4, padx=12, pady=(10, 4), sticky="w")
        self.persona_name = ctk.CTkEntry(pcard, placeholder_text="Name (e.g. The Scholar)", width=220)
        self.persona_traits = ctk.CTkEntry(pcard, placeholder_text="3 traits, comma separated", width=240)
        self.persona_voice = ctk.CTkOptionMenu(pcard, values=ae.VOICES, width=110)
        self.persona_chrono = ctk.CTkOptionMenu(pcard, values=ae.CHRONOTYPES, width=120)
        for col, (lbl, w) in enumerate([("Name", self.persona_name), ("Traits", self.persona_traits),
                                        ("Voice", self.persona_voice), ("Best time", self.persona_chrono)]):
            ctk.CTkLabel(pcard, text=lbl).grid(row=1, column=col, padx=8, sticky="w")
            w.grid(row=2, column=col, padx=8, pady=(0, 12))
        ctk.CTkLabel(pcard, text="I am becoming someone who...").grid(
            row=3, column=0, columnspan=4, padx=12, sticky="w")
        self.persona_identity = ctk.CTkEntry(
            pcard, placeholder_text="finishes what they start (optional)")
        self.persona_identity.grid(row=4, column=0, columnspan=4, padx=12, pady=(0, 12), sticky="ew")

        foot = ctk.CTkFrame(body, fg_color="transparent")
        foot.pack(fill="x", pady=8)
        ctk.CTkLabel(foot, text="Reminder hour (0-23):").pack(side="left", padx=(12, 8))
        self.setup_reminder = ctk.CTkEntry(foot, width=70)
        self.setup_reminder.insert(0, "20"); self.setup_reminder.pack(side="left")

        self.setup_error = ctk.CTkLabel(frame, text="", text_color=BAD)
        self.setup_error.grid(row=3, column=0, sticky="w", pady=(8, 0))
        ctk.CTkButton(frame, text="Create profile", height=42,
                      font=ctk.CTkFont(size=15, weight="bold"),
                      command=self._save_setup).grid(row=4, column=0, sticky="ew", pady=(10, 0))

    def _apply_template(self, name):
        # drop a preset's values into the form
        preset = ae.GOAL_TEMPLATES.get(name, [])
        for (n, u, t, w, b, why), g in zip(self.setup_rows, preset):
            for entry, val in [(n, g["name"]), (u, g["unit"]), (t, g["target"]),
                               (b, g["baseline"]), (why, g.get("why", ""))]:
                entry.delete(0, "end"); entry.insert(0, str(val))
            w.set(str(g["weight"]))

    def _save_setup(self):
        goals = []
        try:
            for (name, unit, target, weight, baseline, why) in self.setup_rows:
                tg = float(target.get())
                if tg <= 0:
                    raise ValueError("Target must be greater than 0.")
                goals.append({"name": name.get().strip() or "Goal",
                              "unit": unit.get().strip() or "units", "target": tg,
                              "weight": int(weight.get()), "baseline": float(baseline.get() or 0),
                              "why": why.get().strip()})
            rh = int(self.setup_reminder.get())
            if not (0 <= rh <= 23):
                raise ValueError("Reminder hour must be 0-23.")
        except ValueError as exc:
            msg = str(exc) if "must" in str(exc) else "Fill targets/baselines with numbers."
            self.setup_error.configure(text="! " + msg)
            return

        traits = [t.strip() for t in self.persona_traits.get().split(",") if t.strip()][:3]
        self.profile = {
            "created": datetime.date.today().isoformat(), "reminder_hour": rh, "goals": goals,
            "persona": {"name": self.persona_name.get().strip() or "The Scholar",
                        "voice": self.persona_voice.get(), "traits": traits or ["disciplined"]},
            "chronotype": self.persona_chrono.get(), "daemon_mode": "watchdog",
            "recovery_mode": False, "recovery_since": None, "badges": [],
            "personal_bests": {}, "letters_read": [], "archived_goals": [],
            "xp": 0, "last_stance": None, "theme": "Ocean",
            "streak_freezes": 0, "freeze_dates": [], "ui_mode": "auto",
            "identity": self.persona_identity.get().strip(),
        }
        ae._save_profile(self.profile)
        ae.log.info("Profile created via GUI: persona %s", self.profile["persona"]["name"])
        self._enable_nav()
        self._build_sidebar()            # refresh persona card
        self.show_home()

    # check-in (Feature 2 sliders, recovery/burnout banner)

    def show_checkin(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Check-in")
        self._clear_content()
        today = datetime.date.today().isoformat()
        frame = self._header("Daily Check-in", f"What did you actually do today?  ({today})")

        # banners
        rowi = 2
        if self.profile.get("recovery_mode"):
            self._banner(frame, rowi, "Recovery mode: targets are eased. Just show up today.", WARN)
            rowi += 1
        risk, reason = ae.detect_burnout_risk(self.profile, ae._read_logs())
        if risk:
            self._banner(frame, rowi, f"Your AlterEgo thinks you need rest, not a challenge ({reason}).", BAD)
            rowi += 1

        if ae._already_logged(today):
            box = ctk.CTkFrame(frame)
            box.grid(row=rowi, column=0, sticky="ew", pady=(16, 0))
            ctk.CTkLabel(box, text="You have already checked in today.",
                         font=ctk.CTkFont(size=15)).pack(padx=20, pady=20)
            ctk.CTkButton(box, text="View Dashboard", command=self.show_dashboard).pack(pady=(0, 20))
            return

        _scoring, targets = ae._score_profile(self.profile)
        body = ctk.CTkFrame(frame)
        body.grid(row=rowi, column=0, sticky="ew", pady=(14, 0))
        body.grid_columnconfigure(1, weight=1)

        # energy + mood sliders
        ctk.CTkLabel(body, text="How are you feeling today? Be honest, your AlterEgo adjusts.",
                     font=ctk.CTkFont(size=12), text_color=MUTED
                     ).grid(row=0, column=0, columnspan=3, padx=16, pady=(12, 4), sticky="w")
        self.energy_var = ctk.IntVar(value=3); self.mood_var = ctk.IntVar(value=3)
        self._slider_row(body, 1, "Energy", self.energy_var)
        self._slider_row(body, 2, "Mood", self.mood_var)

        # grace day toggle
        self.grace_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(body, text="Take a grace day (rest, no pressure, streak protected)",
                        variable=self.grace_var, font=ctk.CTkFont(size=12)
                        ).grid(row=2, column=2, padx=16, pady=4, sticky="e")

        # goals
        self.checkin_entries = []; self.checkin_obstacles = []
        self.checkin_targets = targets
        for i, g in enumerate(self.profile["goals"]):
            r = i + 3
            ctk.CTkLabel(body, text=g["name"], font=ctk.CTkFont(size=14, weight="bold"),
                         anchor="w").grid(row=r, column=0, padx=16, pady=10, sticky="w")
            e = ctk.CTkEntry(body, placeholder_text=f"target {targets[i]} {g['unit']}", width=130)
            e.grid(row=r, column=1, padx=8, pady=10, sticky="e")
            obs = ctk.CTkOptionMenu(body, values=ae.OBSTACLES, width=180); obs.set("None")
            obs.grid(row=r, column=2, padx=16, pady=10, sticky="e")
            self.checkin_entries.append(e); self.checkin_obstacles.append(obs)

        self.checkin_error = ctk.CTkLabel(frame, text="", text_color=BAD)
        self.checkin_error.grid(row=rowi + 1, column=0, sticky="w", pady=(8, 0))
        ctk.CTkButton(frame, text="Submit & Score", height=44,
                      font=ctk.CTkFont(size=15, weight="bold"),
                      command=self._submit_checkin).grid(row=rowi + 2, column=0, sticky="ew", pady=(10, 0))

    def _banner(self, parent, row, text, color):
        b = ctk.CTkFrame(parent, fg_color=color)
        b.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(b, text=text, text_color="white", wraplength=720, justify="left"
                     ).pack(anchor="w", padx=14, pady=8)

    def _slider_row(self, parent, row, label, var):
        ctk.CTkLabel(parent, text=label, width=80, anchor="w"
                     ).grid(row=row, column=0, padx=16, pady=4, sticky="w")
        face = ctk.CTkLabel(parent, text=MOOD_FACES[var.get()], width=36,
                            font=ctk.CTkFont(size=22))
        face.grid(row=row, column=2, padx=16, sticky="e")
        s = ctk.CTkSlider(parent, from_=1, to=5, number_of_steps=4, variable=var,
                          button_color=ACCENT, progress_color=ACCENT,
                          command=lambda v: face.configure(text=MOOD_FACES[int(float(v))]))
        s.grid(row=row, column=1, padx=8, pady=4, sticky="ew")

    def _submit_checkin(self):
        try:
            actuals = [float(e.get()) for e in self.checkin_entries]
            if any(a < 0 for a in actuals):
                raise ValueError
        except ValueError:
            self.checkin_error.configure(text="! Enter a non-negative number for every goal.")
            return

        today = datetime.date.today().isoformat()
        ae._manage_freezes(self.profile, today)     # bridge a missed day if possible
        targets = self.checkin_targets
        obstacles = []
        for i in range(len(self.profile["goals"])):
            chosen = self.checkin_obstacles[i].get()
            obstacles.append(chosen if actuals[i] < targets[i] else "None")

        scoring, _ = ae._score_profile(self.profile)
        gaps, score, weakest_idx = ae.think(scoring, actuals)
        energy, mood = self.energy_var.get(), self.mood_var.get()
        grace = self.grace_var.get()
        streaks = ae.compute_streaks(ae._read_logs())
        coach = ae.coaching_state(self.profile, ae._read_logs(), energy, mood, score, streaks, grace)
        gameinfo = ae._game_preview(self.profile, score, streaks, grace, today)
        weak_obs = obstacles[weakest_idx] if obstacles[weakest_idx] != "None" else None
        challenge = ae.micro_challenge(self.profile, actuals, weakest_idx, today, weak_obs)
        label = "Rest Day" if grace else ae.day_label(score, self.profile.get("recovery_mode"))
        new_pbs = ae.update_personal_bests(self.profile, actuals)

        self.pending = dict(today=today, actuals=actuals, gaps=gaps, score=score,
                            weakest_idx=weakest_idx, obstacles=obstacles, challenge=challenge,
                            label=label, energy=energy, mood=mood, targets=targets,
                            grace=grace, coach=coach, game=gameinfo)
        self._show_result(score, weakest_idx, coach, challenge, streaks, label, new_pbs, gameinfo)

    def _show_result(self, score, weakest_idx, coach, challenge, streaks, label, new_pbs, gameinfo):
        self._clear_content()
        frame = self._header("Today's Result")
        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        frame.grid_rowconfigure(2, weight=1)
        targets = self.pending["targets"]; actuals = self.pending["actuals"]

        badge = ctk.CTkFrame(scroll); badge.pack(fill="x", pady=6)
        ctk.CTkLabel(badge, text=f"{score}", font=ctk.CTkFont(size=52, weight="bold"),
                     text_color=_score_color(score)).pack(side="left", padx=(24, 6), pady=16)
        ctk.CTkLabel(badge, text="/ 100", font=ctk.CTkFont(size=20),
                     text_color=MUTED).pack(side="left", pady=(34, 16))
        ctk.CTkLabel(badge, text=label, font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=_score_color(score)).pack(side="right", padx=24)

        bars = ctk.CTkFrame(scroll); bars.pack(fill="x", pady=6)
        bars.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(bars, text="Goal breakdown", font=ctk.CTkFont(size=14, weight="bold")
                     ).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 6))
        for i, g in enumerate(self.profile["goals"]):
            pct = 1.0 if targets[i] <= 0 else min(1.0, actuals[i] / targets[i])
            ctk.CTkLabel(bars, text=g["name"], anchor="w", width=150
                         ).grid(row=i + 1, column=0, padx=(14, 6), pady=6, sticky="w")
            pb = ctk.CTkProgressBar(bars, height=16); pb.set(pct)
            pb.configure(progress_color=GOOD if pct >= 1.0 else ACCENT)
            pb.grid(row=i + 1, column=1, padx=6, pady=6, sticky="ew")
            ctk.CTkLabel(bars, text=f"{actuals[i]}/{targets[i]} {g['unit']}", width=120
                         ).grid(row=i + 1, column=2, padx=(6, 14), pady=6, sticky="e")

        # coaching card: how your AlterEgo reads today, and why
        pe = ae.get_persona(self.profile)
        stance_color = {"push": WARN, "celebrate": GOOD, "grace": ACCENT,
                        "recover": ACCENT, "steady": ACCENT}.get(coach["stance"], ACCENT)
        msg = ctk.CTkFrame(scroll); msg.pack(fill="x", pady=6)
        ctk.CTkLabel(msg, text=f"{pe['name']}  -  stance: {coach['stance']}",
                     font=ctk.CTkFont(size=14, weight="bold"), text_color=stance_color
                     ).pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(msg, text=coach["headline"], wraplength=640, justify="left",
                     font=ctk.CTkFont(size=13)).pack(anchor="w", padx=14, pady=(0, 6))
        if coach.get("shift"):
            ctk.CTkLabel(msg, text="(something changed in how I'm treating you today)",
                         text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=14)
        ctk.CTkLabel(msg, text="Why:", font=ctk.CTkFont(size=12, weight="bold")
                     ).pack(anchor="w", padx=14, pady=(6, 0))
        for r in coach["reasons"]:
            ctk.CTkLabel(msg, text="- " + r, wraplength=620, justify="left",
                         text_color="gray70").pack(anchor="w", padx=20, pady=1)
        if coach["enough"]:
            ctk.CTkLabel(msg, text="Verdict: that was enough for today. Rest easy.",
                         text_color=GOOD, font=ctk.CTkFont(size=13, weight="bold")
                         ).pack(anchor="w", padx=14, pady=(8, 12))
        else:
            ctk.CTkLabel(msg, text="").pack(pady=2)

        # the two voices: the teacher who pushes, the friend who holds you
        teacher, friend = ae.dual_voice(self.profile, score, coach["stance"],
                                        self.pending["today"])
        tv = ctk.CTkFrame(scroll); tv.pack(fill="x", pady=6)
        trow = ctk.CTkFrame(tv, fg_color="transparent"); trow.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(trow, text="\U0001F393 The teacher", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=WARN).pack(anchor="w")
        ctk.CTkLabel(trow, text=teacher, wraplength=640, justify="left",
                     text_color="gray80").pack(anchor="w")
        frow = ctk.CTkFrame(tv, fg_color="transparent"); frow.pack(fill="x", padx=14, pady=(0, 6))
        ctk.CTkLabel(frow, text="\U0001F49B The friend", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=GOOD).pack(anchor="w")
        ctk.CTkLabel(frow, text=friend, wraplength=640, justify="left",
                     text_color="gray80").pack(anchor="w")
        il = ae.identity_line(self.profile)
        if il:
            ctk.CTkLabel(tv, text=il, font=ctk.CTkFont(size=12, slant="italic"),
                         text_color=ACCENT, wraplength=640).pack(anchor="w", padx=14, pady=(0, 12))

        for name in new_pbs:
            pbf = ctk.CTkFrame(scroll, fg_color=GOOD); pbf.pack(fill="x", pady=4)
            ctk.CTkLabel(pbf, text=f"New personal best: {name}! {pe['name']} is taking notes.",
                         text_color="white").pack(anchor="w", padx=14, pady=8)

        weak = self.profile["goals"][weakest_idx]
        ch = ctk.CTkFrame(scroll); ch.pack(fill="x", pady=6)
        ctk.CTkLabel(ch, text=f"Weakest area: {weak['name']}",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(ch, text=challenge, wraplength=640, justify="left",
                     text_color=WARN).pack(anchor="w", padx=14, pady=(2, 4))
        if weak.get("why"):
            ctk.CTkLabel(ch, text=f"Remember why: {weak['why']}", wraplength=640,
                         justify="left", text_color=ACCENT).pack(anchor="w", padx=14, pady=(0, 4))
        advice = ae.chronotype_advice(self.profile, weak["name"])
        if advice:
            ctk.CTkLabel(ch, text="Tip: " + advice, text_color=MUTED, wraplength=640,
                         justify="left").pack(anchor="w", padx=14, pady=(0, 12))

        # the fun card: monster, loot, XP, level-up
        gi = gameinfo
        gcard = ctk.CTkFrame(scroll); gcard.pack(fill="x", pady=6)
        ctk.CTkLabel(gcard, text="The Game", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=GOOD).pack(anchor="w", padx=14, pady=(12, 4))
        ctk.CTkLabel(gcard, text=gi["monster"], wraplength=620, justify="left",
                     text_color="gray80").pack(anchor="w", padx=14)
        d = gi["draw"]
        draw_txt = f"Daily Draw: {d['label']} - {d['flavor']}" + (f"  (+{d['xp']} XP)" if d["xp"] else "")
        ctk.CTkLabel(gcard, text=draw_txt, wraplength=620, justify="left",
                     text_color=ACCENT).pack(anchor="w", padx=14, pady=(4, 0))
        combo_txt = f"  Combo x{gi['combo']}" if gi["combo"] > 1.0 else ""
        ctk.CTkLabel(gcard, text=f"+{gi['xp_gained']} XP{combo_txt}",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=14, pady=(4, 0))
        if gi["leveled_up"]:
            ctk.CTkLabel(gcard, text=f"LEVEL UP! You are now Level {gi['level_after']} "
                                     f"({ae.title_for_level(gi['level_after'])})!",
                         font=ctk.CTkFont(size=15, weight="bold"), text_color=GOOD
                         ).pack(anchor="w", padx=14, pady=(4, 0))
        ctk.CTkLabel(gcard, text="").pack(pady=2)

        # reflection box
        ref = ctk.CTkFrame(scroll); ref.pack(fill="x", pady=6)
        ctk.CTkLabel(ref, text="One thing you noticed about yourself today (optional)",
                     font=ctk.CTkFont(size=13)).pack(anchor="w", padx=14, pady=(12, 4))
        self.reflection_entry = ctk.CTkEntry(ref, placeholder_text="write a line, or leave blank")
        self.reflection_entry.pack(fill="x", padx=14, pady=(0, 12))

        ctk.CTkButton(frame, text="Save check-in", height=42,
                      font=ctk.CTkFont(size=15, weight="bold"),
                      command=self._finalize_checkin).grid(row=3, column=0, sticky="ew", pady=(12, 0))

        # celebrate the big moments
        if gi["leveled_up"] or score >= 100:
            self.after(150, self._confetti)

    def _finalize_checkin(self):
        p = self.pending
        reflection = self.reflection_entry.get().strip()
        ae._log_entry(p["today"], p["actuals"], p["gaps"], p["score"], p["challenge"],
                      self.profile, p["obstacles"], energy=p["energy"], mood=p["mood"],
                      reflection=reflection, focus_sessions=self.focus_sessions,
                      label=p["label"], grace="1" if p["grace"] else "")
        self.profile["last_stance"] = p["coach"]["stance"]
        self.profile["xp"] = p["game"]["xp_after"]      # commit the XP now
        self.focus_sessions = 0
        logs = ae._read_logs()
        ae._handle_recovery_transitions(self.profile, logs)
        ae._award_badges(self.profile, logs)
        streaks_now = ae.compute_streaks(logs)
        ae._earn_freeze(self.profile, streaks_now["momentum"])
        ae._save_profile(self.profile)
        if len(logs) % 7 == 0:
            ae.evolve_apply(self.profile)
            ae.write_weekly_letter(self.profile, logs)
        self.pending = None
        self._build_sidebar()             # reflect any newly unlocked screens
        self.show_dashboard()

    # dashboard (Feature 8 split, Feature 21 mood arc, Feature 7 heatmap)

    def show_dashboard(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Dashboard")
        self._clear_content()
        frame = self._header("Dashboard")
        logs = ae._read_logs()
        if not logs:
            ctk.CTkLabel(frame, text="No data yet. Do your first check-in.",
                         text_color=MUTED).grid(row=2, column=0, pady=40)
            return

        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        frame.grid_rowconfigure(2, weight=1)

        import statistics
        streaks = ae.compute_streaks(logs)
        scores = [float(r["score"]) for r in logs]
        cards = ctk.CTkFrame(scroll, fg_color="transparent"); cards.pack(fill="x")
        stats = [("\U0001F4C5 Days", str(len(logs))), ("\U0001F525 Streak", f"{streaks['log_streak']}"),
                 ("⚡ Momentum", f"{streaks['momentum']}"),
                 ("\U0001F4C8 Avg", f"{round(statistics.mean(scores), 1)}")]
        for i, (label, value) in enumerate(stats):
            c = ctk.CTkFrame(cards, fg_color=CARD_COLORS[i % len(CARD_COLORS)], corner_radius=14)
            c.grid(row=0, column=i, padx=6, pady=6, sticky="nsew")
            cards.grid_columnconfigure(i, weight=1)
            ctk.CTkLabel(c, text=value, font=ctk.CTkFont(size=26, weight="bold"),
                         text_color="white").pack(padx=18, pady=(14, 0))
            ctk.CTkLabel(c, text=label, text_color="white").pack(padx=18, pady=(0, 14))

        self._split_panel(scroll, logs)
        self._embed_chart(scroll, logs)
        self._embed_moodarc(scroll, logs)
        self._embed_heatmap(scroll, logs)

        tools = ctk.CTkFrame(scroll, fg_color="transparent"); tools.pack(fill="x", pady=8)
        ctk.CTkButton(tools, text="Export score card",
                      command=self._do_scorecard).pack(side="left", padx=6)
        ctk.CTkButton(tools, text="Backup (zip)", fg_color="gray40",
                      command=self._do_backup).pack(side="left", padx=6)

    def _split_panel(self, parent, logs):
        # Feature 8: You vs AlterEgo
        data = ae.compare_selves(self.profile, logs)
        if not data:
            return
        holder = ctk.CTkFrame(parent); holder.pack(fill="x", pady=8)
        ctk.CTkLabel(holder, text="You  vs  Your AlterEgo", font=ctk.CTkFont(size=14, weight="bold")
                     ).pack(anchor="w", padx=14, pady=(12, 6))
        grid = ctk.CTkFrame(holder, fg_color="transparent"); grid.pack(fill="x", padx=14)
        grid.grid_columnconfigure(1, weight=1)
        for i, row in enumerate(data["rows"]):
            ctk.CTkLabel(grid, text=row["goal"], width=130, anchor="w"
                         ).grid(row=i, column=0, sticky="w", pady=4)
            pb = ctk.CTkProgressBar(grid, height=16); pb.set(row["pct"])
            pb.configure(progress_color=GOOD if row["pct"] >= 1.0 else ACCENT)
            pb.grid(row=i, column=1, sticky="ew", padx=8, pady=4)
            ctk.CTkLabel(grid, text=f"{row['actual']} / {row['target']} {row['unit']}",
                         width=130).grid(row=i, column=2, sticky="e", pady=4)
        ctk.CTkLabel(holder, text=f"Gap to close: {data['gap_points']} points",
                     text_color=WARN).pack(anchor="w", padx=14, pady=(6, 12))

    def _embed_chart(self, parent, logs):
        holder = ctk.CTkFrame(parent); holder.pack(fill="both", expand=True, pady=8)
        ctk.CTkLabel(holder, text="Score trend", font=ctk.CTkFont(size=14, weight="bold")
                     ).pack(anchor="w", padx=14, pady=(12, 4))
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        except ImportError:
            ctk.CTkLabel(holder, text="(install matplotlib for charts)", text_color=MUTED
                         ).pack(padx=14, pady=14); return
        scores = [float(r["score"]) for r in logs]
        fig = Figure(figsize=(6.6, 2.8), dpi=100); fig.patch.set_alpha(0)
        ax = fig.add_subplot(111)
        ax.plot(range(len(scores)), scores, marker="o", color=ACCENT, linewidth=2)
        ax.axhline(60, color=WARN, linestyle="--", linewidth=1)
        ax.fill_between(range(len(scores)), scores, alpha=0.12, color=ACCENT)
        ax.set_ylim(0, 100); ax.set_xlabel("Day"); ax.set_ylabel("Score"); ax.grid(True, alpha=0.2)
        fig.tight_layout()
        cv = FigureCanvasTkAgg(fig, master=holder); cv.draw()
        cv.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _embed_moodarc(self, parent, logs):
        # Feature 21: energy + mood vs score (skip rows with bad numbers)
        energy, mood = [], []
        for r in logs:
            try:
                e = float(r.get("energy") or 0); m = float(r.get("mood") or 0)
            except (TypeError, ValueError):
                continue
            if e > 0 and m > 0:
                energy.append(e); mood.append(m)
        if len(energy) < 3:
            return
        holder = ctk.CTkFrame(parent); holder.pack(fill="both", expand=True, pady=8)
        ctk.CTkLabel(holder, text="Mood arc (energy + mood)", font=ctk.CTkFont(size=14, weight="bold")
                     ).pack(anchor="w", padx=14, pady=(12, 4))
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        except ImportError:
            return
        fig = Figure(figsize=(6.6, 2.4), dpi=100); fig.patch.set_alpha(0)
        ax = fig.add_subplot(111)
        ax.plot(range(len(energy)), energy, marker="o", color=ACCENT, label="energy")
        ax.plot(range(len(mood)), mood, marker="s", color=GOOD, label="mood")
        ax.set_ylim(0, 6); ax.set_xlabel("Day"); ax.set_ylabel("1-5")
        ax.legend(fontsize=8); ax.grid(True, alpha=0.2); fig.tight_layout()
        cv = FigureCanvasTkAgg(fig, master=holder); cv.draw()
        cv.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _embed_heatmap(self, parent, logs):
        # Feature 7: github-style year heatmap
        holder = ctk.CTkFrame(parent); holder.pack(fill="both", expand=True, pady=8)
        ctk.CTkLabel(holder, text="Year heatmap", font=ctk.CTkFont(size=14, weight="bold")
                     ).pack(anchor="w", padx=14, pady=(12, 4))
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.patches import Rectangle
        except ImportError:
            return
        by_date = {}
        for r in logs:
            try:
                by_date[datetime.date.fromisoformat(r["date"])] = float(r["score"])
            except (KeyError, ValueError):
                pass
        if not by_date:
            return
        end = max(by_date); start = end - datetime.timedelta(days=118)
        start -= datetime.timedelta(days=start.weekday())

        def colour(s):
            if s is None: return "#3a3a3a"
            if s >= 80: return GOOD
            if s >= 60: return ACCENT
            if s >= 40: return WARN
            return BAD

        fig = Figure(figsize=(6.6, 1.8), dpi=100); fig.patch.set_alpha(0)
        ax = fig.add_subplot(111)
        d = start; week = 0
        while d <= end:
            ax.add_patch(Rectangle((week, 6 - d.weekday()), 0.9, 0.9,
                                   facecolor=colour(by_date.get(d)), edgecolor="none"))
            if d.weekday() == 6:
                week += 1
            d += datetime.timedelta(days=1)
        ax.set_xlim(0, week + 1); ax.set_ylim(0, 7); ax.set_aspect("equal"); ax.axis("off")
        fig.tight_layout()
        cv = FigureCanvasTkAgg(fig, master=holder); cv.draw()
        cv.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _do_scorecard(self):
        path, _ = ae.export_scorecard(self.profile, ae._read_logs())
        self._toast(f"Score card saved to {path}")

    def _do_backup(self):
        name = ae.export_backup(ae.PROFILE_FILE, ae.LOG_FILE)
        self._toast(f"Backup saved to {name}")

    def _toast(self, text):
        top = ctk.CTkToplevel(self); top.title("Done"); top.geometry("420x140")
        top.transient(self); top.grab_set()
        ctk.CTkLabel(top, text=text, wraplength=380).pack(padx=16, pady=20)
        ctk.CTkButton(top, text="OK", command=top.destroy).pack(pady=(0, 12))

    def _confetti(self):
        # a short burst of falling colour to celebrate. pure tkinter, no libs.
        import tkinter as tk, random
        w = self.winfo_width() or 1000
        h = self.winfo_height() or 680
        # narrow strip across the top so it feels like a burst, not a blackout
        strip_h = 90
        canvas = tk.Canvas(self, width=w, height=strip_h, highlightthickness=0)
        canvas.place(x=0, y=0)
        colors = [ACCENT, GOOD, WARN, BAD, "#F0C808", "#9B59B6"]
        bits = []
        for _ in range(60):
            x = random.randint(0, w); y = random.randint(-strip_h, 0)
            r = random.randint(3, 7)
            o = canvas.create_oval(x, y, x + r, y + r, fill=random.choice(colors), outline="")
            bits.append([o, random.uniform(2.5, 5.0)])
        state = {"frame": 0, "h": strip_h}

        def fall():
            if not canvas.winfo_exists():       # window closed mid-animation
                return
            state["frame"] += 1
            state["h"] = min(state["h"] + 8, h)
            try:
                canvas.configure(height=int(state["h"]))
                for b in bits:
                    canvas.move(b[0], random.randint(-1, 1), b[1])
            except Exception:
                return
            if state["frame"] < 60:
                self.after(40, fall)
            else:
                canvas.destroy()
        fall()

    # insights

    def show_insights(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Insights")
        self._clear_content()
        frame = self._header("Insights", "What actually moves your score")
        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        frame.grid_rowconfigure(2, weight=1)
        logs = ae._read_logs()
        data = ae.insights(self.profile, logs)
        if not data["enough_data"]:
            ctk.CTkLabel(scroll, text=f"Not enough data yet ({len(logs)} day(s)). Unlocks at 5.",
                         text_color=MUTED).pack(anchor="w", pady=20, padx=10)
            return

        def card(title, lines, color=ACCENT):
            c = ctk.CTkFrame(scroll); c.pack(fill="x", pady=6)
            ctk.CTkLabel(c, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=color).pack(anchor="w", padx=14, pady=(12, 4))
            for ln in lines:
                ctk.CTkLabel(c, text=ln, anchor="w", justify="left", wraplength=620,
                             text_color="gray80").pack(anchor="w", padx=14, pady=1)
            ctk.CTkLabel(c, text="").pack(pady=2)

        if data["top_lever"]:
            lv = data["top_lever"]
            d = "lifts" if lv["corr"] >= 0 else "drags down"
            card("Your biggest lever",
                 [f"'{lv['goal']}' {d} your score most (correlation {lv['corr']:+.2f})."], GOOD)
        if data["worst_weekday"]:
            card("Day-of-week pattern",
                 [f"Toughest: {data['worst_weekday']['day']} ({data['worst_weekday']['avg']})",
                  f"Strongest: {data['best_weekday']['day']} ({data['best_weekday']['avg']})"], WARN)
        if data["obstacles"]:
            card("What blocks you most",
                 [f"- {g}: {o}" for g, o in data["obstacles"].items()], BAD)
        stacks = ae.habit_stack_suggestions(self.profile, logs)
        if stacks:
            card("Habit stacks " + ae.get_persona(self.profile)["name"] + " noticed",
                 [f"hit {a} -> you also hit {b} {int(r*100)}% of the time" for a, b, r in stacks[:3]])
        if ae.detect_plateau(logs):
            card("Plateau", ["You're stable but flat. Time to shake up the routine."], WARN)

    # patterns (Feature 5)

    def show_patterns(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Patterns")
        self._clear_content()
        pe = ae.get_persona(self.profile)
        frame = self._header("Patterns", f"What {pe['name']} has learned about you")
        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        frame.grid_rowconfigure(2, weight=1)
        logs = ae._read_logs()
        data = ae.behavioral_patterns(self.profile, logs)
        if not data["enough_data"]:
            ctk.CTkLabel(scroll, text=f"Need 10+ days ({len(logs)} so far).",
                         text_color=MUTED).pack(anchor="w", pady=20, padx=10)
            return

        def card(title, lines, color=ACCENT):
            c = ctk.CTkFrame(scroll); c.pack(fill="x", pady=6)
            ctk.CTkLabel(c, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=color).pack(anchor="w", padx=14, pady=(12, 4))
            for ln in lines:
                ctk.CTkLabel(c, text=ln, wraplength=620, justify="left",
                             text_color="gray80").pack(anchor="w", padx=14, pady=1)
            ctk.CTkLabel(c, text="").pack(pady=2)

        for t in data["triggers"]:
            card("Trigger chain", [f"When you miss {t['a']}, you miss {t['b']} the next "
                                   f"day {int(t['rate']*100)}% of the time."], BAD)
        if data["weekday_cycle"]:
            wc = data["weekday_cycle"]
            card("Weekly cycle", [f"Best on {wc['best']} ({wc['best_avg']}), "
                                  f"worst on {wc['worst']} ({wc['worst_avg']})."])
        if data["recovery_time"] is not None:
            card("Recovery time", [f"After a bad day you take about {data['recovery_time']} "
                                   "days to climb back above 60."])
        sp = data["streak_personality"]
        if sp and sp["longest"]:
            extra = f", usually breaks on {sp['breaks_on']}" if sp["breaks_on"] else ""
            card("Streak personality", [f"Longest run: {sp['longest']} days{extra}."], GOOD)
        if data["goal_momentum"]:
            card("Goal momentum", [f"{g}: {t}" for g, t in data["goal_momentum"]])

    # focus timer (Feature 6)

    def show_focus(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Focus")
        self._clear_content()
        frame = self._header("Focus Mode", "Run a 25-minute session for a goal")
        self.focus_state = {"remaining": 0, "running": False, "goal": None, "job": None}

        pick = ctk.CTkFrame(frame); pick.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        ctk.CTkLabel(pick, text="Pick a goal:").pack(side="left", padx=12, pady=12)
        self.focus_goal = ctk.CTkOptionMenu(pick, values=[g["name"] for g in self.profile["goals"]])
        self.focus_goal.pack(side="left", padx=8)

        self.focus_clock = ctk.CTkLabel(frame, text="25:00", font=ctk.CTkFont(size=64, weight="bold"))
        self.focus_clock.grid(row=3, column=0, pady=20)
        self.focus_note = ctk.CTkLabel(frame, text=f"Sessions this run: {self.focus_sessions}",
                                       text_color=MUTED)
        self.focus_note.grid(row=4, column=0)

        btns = ctk.CTkFrame(frame, fg_color="transparent"); btns.grid(row=5, column=0, pady=14)
        ctk.CTkButton(btns, text="Start", command=self._focus_start).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Pause", fg_color="gray40", command=self._focus_pause).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="Reset", fg_color=BAD, command=self._focus_reset).pack(side="left", padx=6)

    def _focus_tick(self):
        if not self.focus_state["running"]:
            return
        # if the user navigated away, the clock widget is gone. stop quietly.
        if not (self.focus_clock and self.focus_clock.winfo_exists()):
            self.focus_state["running"] = False
            return
        if self.focus_state["remaining"] <= 0:
            self.focus_state["running"] = False
            self.focus_sessions += 1
            self.focus_clock.configure(text="done")
            self.focus_note.configure(text=f"Session done. Sessions this run: {self.focus_sessions}")
            ae.osutil.notify("AlterEgo Agent", "25 minutes done. Take 5. Your AlterEgo is proud.")
            return
        self.focus_state["remaining"] -= 1
        m, s = divmod(self.focus_state["remaining"], 60)
        self.focus_clock.configure(text=f"{m:02d}:{s:02d}")
        self.focus_state["job"] = self.after(1000, self._focus_tick)

    def _focus_start(self):
        if self.focus_state["running"]:
            return
        if self.focus_state["remaining"] <= 0:
            self.focus_state["remaining"] = 25 * 60
        self.focus_state["running"] = True
        self._focus_tick()

    def _focus_pause(self):
        self.focus_state["running"] = False

    def _focus_reset(self):
        self.focus_state["running"] = False
        self.focus_state["remaining"] = 0
        self.focus_clock.configure(text="25:00")

    # reflections (Feature 3)

    def show_reflections(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Reflections")
        self._clear_content()
        frame = self._header("Reflections", "Your own words, over time")
        scroll = ctk.CTkScrollableFrame(frame)
        scroll.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        frame.grid_rowconfigure(2, weight=1)
        logs = ae._read_logs()
        entries = [r for r in logs if r.get("reflection")]
        if not entries:
            ctk.CTkLabel(scroll, text="No reflections yet. Add one after a check-in.",
                         text_color=MUTED).pack(pady=20)
            return
        for r in reversed(entries[-30:]):
            row = ctk.CTkFrame(scroll); row.pack(fill="x", pady=4, padx=4)
            ctk.CTkLabel(row, text=r["date"], width=92, anchor="w"
                         ).pack(side="left", padx=(12, 6), pady=10)
            ctk.CTkLabel(row, text=f"{float(r['score']):.0f}", width=36,
                         text_color=_score_color(float(r["score"])),
                         font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkLabel(row, text=r["reflection"], anchor="w", wraplength=560,
                         justify="left").pack(side="left", padx=8, fill="x", expand=True)

    # badges (Feature 10)

    def show_badges(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Badges")
        self._clear_content()
        frame = self._header("Badges", "Earned, not given")
        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        frame.grid_rowconfigure(2, weight=1)
        have = set(self.profile.get("badges", []))
        for bid, label, _ in ae.BADGES:
            earned = bid in have
            card = ctk.CTkFrame(card_parent := scroll, fg_color=(GOOD if earned else ("gray80", "gray20")))
            card.pack(fill="x", pady=5)
            ctk.CTkLabel(card, text=("[x] " if earned else "[ ] ") + label,
                         text_color="white" if earned else MUTED,
                         font=ctk.CTkFont(size=14, weight="bold" if earned else "normal")
                         ).pack(anchor="w", padx=16, pady=12)

    # letter (Feature 9)

    def show_letter(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Letter")
        self._clear_content()
        frame = self._header("Weekly Letter", "From your AlterEgo, every 7 days")
        path, text = ae.latest_letter()
        box = ctk.CTkTextbox(frame, wrap="word", font=ctk.CTkFont(size=13))
        box.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        frame.grid_rowconfigure(2, weight=1)
        box.insert("1.0", text or "No letter yet. The first one arrives after 7 days.")
        box.configure(state="disabled")
        if path and path not in self.profile.get("letters_read", []):
            self.profile.setdefault("letters_read", []).append(path)
            ae._save_profile(self.profile)

    # history (Feature 19 day labels)

    def show_history(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("History")
        self._clear_content()
        frame = self._header("History", "Your recent check-ins")
        logs = ae._read_logs()
        tampered = ae.verify_log_integrity(logs)
        scroll = ctk.CTkScrollableFrame(frame)
        scroll.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        frame.grid_rowconfigure(2, weight=1)
        if not logs:
            ctk.CTkLabel(scroll, text="No entries yet.", text_color=MUTED).pack(pady=20)
            return
        for r in reversed(logs[-60:]):
            row = ctk.CTkFrame(scroll); row.pack(fill="x", pady=4, padx=4)
            score = float(r["score"])
            ctk.CTkLabel(row, text=r["date"], width=92, anchor="w"
                         ).pack(side="left", padx=(12, 6), pady=10)
            ctk.CTkLabel(row, text=f"{score:.0f}", width=36, font=ctk.CTkFont(weight="bold"),
                         text_color=_score_color(score)).pack(side="left")
            ctk.CTkLabel(row, text=r.get("day_label", ""), width=92, anchor="w",
                         text_color="gray70").pack(side="left", padx=6)
            tag = "  [modified]" if r.get("date") in tampered else ""
            ctk.CTkLabel(row, text=r.get("challenge", "")[:50] + tag, anchor="w",
                         text_color=BAD if tag else "gray70").pack(side="left", padx=6,
                                                                   fill="x", expand=True)

    # goals + archive (Feature 24) + daemon-independent edits

    def show_goals(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Goals")
        self._clear_content()
        frame = self._header("Manage Goals", "Targets, weights, reminder hour")
        body = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        frame.grid_rowconfigure(2, weight=1)

        self.goal_edit = []
        for g in self.profile["goals"]:
            card = ctk.CTkFrame(body); card.pack(fill="x", pady=8)
            ctk.CTkLabel(card, text=g["name"], font=ctk.CTkFont(size=15, weight="bold")
                         ).grid(row=0, column=0, columnspan=4, padx=12, pady=(10, 6), sticky="w")
            ctk.CTkLabel(card, text=f"Target ({g['unit']})").grid(row=1, column=0, padx=12, sticky="w")
            tgt = ctk.CTkEntry(card, width=100); tgt.insert(0, str(g["target"]))
            tgt.grid(row=1, column=1, padx=8, pady=(0, 12))
            ctk.CTkLabel(card, text="Weight").grid(row=1, column=2, padx=12, sticky="w")
            wgt = ctk.CTkOptionMenu(card, values=["1", "2", "3"], width=70); wgt.set(str(g["weight"]))
            wgt.grid(row=1, column=3, padx=(8, 12), pady=(0, 12))
            ctk.CTkLabel(card, text="Why").grid(row=2, column=0, padx=12, sticky="w")
            why = ctk.CTkEntry(card, placeholder_text="why this matters (optional)")
            why.insert(0, g.get("why", ""))
            why.grid(row=2, column=1, columnspan=3, padx=8, pady=(0, 12), sticky="ew")
            self.goal_edit.append((g, tgt, wgt, why))

        archived = self.profile.get("archived_goals", [])
        if archived:
            ac = ctk.CTkFrame(body); ac.pack(fill="x", pady=8)
            ctk.CTkLabel(ac, text="Archived goals", font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=MUTED).pack(anchor="w", padx=12, pady=(10, 4))
            for a in archived:
                ctk.CTkLabel(ac, text=f"  {a.get('name')} (last active {a.get('last_active', '?')}, "
                                      f"avg {a.get('lifetime_avg', '?')})",
                             text_color=MUTED).pack(anchor="w", padx=12, pady=2)
            ctk.CTkLabel(ac, text="").pack(pady=2)

        rh = ctk.CTkFrame(body); rh.pack(fill="x", pady=8)
        ctk.CTkLabel(rh, text="Reminder hour (0-23)").pack(side="left", padx=12, pady=12)
        self.goal_reminder = ctk.CTkEntry(rh, width=70)
        self.goal_reminder.insert(0, str(self.profile.get("reminder_hour", 20)))
        self.goal_reminder.pack(side="left", pady=12)

        self.goal_status = ctk.CTkLabel(frame, text="", text_color=GOOD)
        self.goal_status.grid(row=3, column=0, sticky="w", pady=(6, 0))
        ctk.CTkButton(frame, text="Save changes", height=42, command=self._save_goals
                      ).grid(row=4, column=0, sticky="ew", pady=(8, 0))

    def _save_goals(self):
        try:
            for (g, tgt, wgt, why) in self.goal_edit:
                t = float(tgt.get())
                if t <= 0:
                    raise ValueError
                g["target"] = t; g["weight"] = int(wgt.get()); g["why"] = why.get().strip()
            rh = int(self.goal_reminder.get())
            if not (0 <= rh <= 23):
                raise ValueError
            self.profile["reminder_hour"] = rh
        except ValueError:
            self.goal_status.configure(text="! Targets > 0 and hour 0-23.", text_color=BAD)
            return
        ae._save_profile(self.profile)
        self.goal_status.configure(text="Saved.", text_color=GOOD)

    # event log viewer (Feature 22)

    def show_eventlog(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Event Log")
        self._clear_content()
        frame = self._header("Event Log", "What the agent has been doing")
        box = ctk.CTkTextbox(frame, wrap="none", font=ctk.CTkFont(size=11, family="Consolas"))
        box.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        frame.grid_rowconfigure(2, weight=1)
        try:
            with open(ae.EVENT_LOG, encoding="utf-8") as f:
                lines = f.readlines()[-300:]
            box.insert("1.0", "".join(lines) or "(empty)")
        except OSError:
            box.insert("1.0", "(no event log yet)")
        box.configure(state="disabled")

    # reminder + daemon mode (Feature 25)

    def show_reminder(self):
        if self.profile is None:
            return self.show_setup()
        self._highlight("Reminder")
        self._clear_content()
        frame = self._header("Reminder Daemon",
                             "Background process that nudges you if you skip a day")
        box = ctk.CTkFrame(frame); box.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        self.reminder_status_label = ctk.CTkLabel(box, text="checking...", font=ctk.CTkFont(size=16))
        self.reminder_status_label.pack(padx=20, pady=(20, 6))

        modef = ctk.CTkFrame(box, fg_color="transparent"); modef.pack(pady=(0, 8))
        ctk.CTkLabel(modef, text="Mode:").pack(side="left", padx=8)
        self.daemon_mode = ctk.CTkOptionMenu(modef, values=ae.DAEMON_MODES,
                                             command=self._set_daemon_mode)
        self.daemon_mode.set(self.profile.get("daemon_mode", "watchdog"))
        self.daemon_mode.pack(side="left", padx=8)
        ctk.CTkLabel(box, text="watchdog = once/day, adaptive = twice, silent = off",
                     text_color=MUTED, font=ctk.CTkFont(size=11)).pack()

        btns = ctk.CTkFrame(box, fg_color="transparent"); btns.pack(pady=(10, 20))
        ctk.CTkButton(btns, text="Start", command=self._daemon_start).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Stop", fg_color=BAD, hover_color="#922B21",
                      command=self._daemon_stop).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Refresh", fg_color="gray40",
                      command=self._refresh_reminder).pack(side="left", padx=8)
        self._refresh_reminder()

    def _set_daemon_mode(self, mode):
        self.profile["daemon_mode"] = mode
        ae._save_profile(self.profile)

    def _refresh_reminder(self):
        # a worker thread may call this after we've left the screen; bail if the
        # label is gone instead of crashing on a destroyed widget.
        lbl = getattr(self, "reminder_status_label", None)
        if not (lbl and lbl.winfo_exists()):
            return
        if ae._daemon_running():
            detail = ""
            try:
                with open(ae.DAEMON_STATUS, encoding="utf-8") as f:
                    st = json.load(f)
                age = int(time.time() - st.get("heartbeat", 0))
                detail = f"\n(pid {st.get('pid')}, heartbeat {age}s ago, mode {st.get('mode', '?')})"
            except (OSError, json.JSONDecodeError):
                pass
            lbl.configure(text="Status: RUNNING" + detail, text_color=GOOD)
        else:
            lbl.configure(text="Status: STOPPED", text_color=MUTED)

    def _daemon_start(self):
        self.reminder_status_label.configure(text="starting...", text_color=WARN)
        threading.Thread(target=lambda: (ae.reminder_start(),
                                         self.after(0, self._refresh_reminder)), daemon=True).start()

    def _daemon_stop(self):
        self.reminder_status_label.configure(text="stopping...", text_color=WARN)
        threading.Thread(target=lambda: (ae.reminder_stop(),
                                         self.after(0, self._refresh_reminder)), daemon=True).start()


if __name__ == "__main__":
    App().mainloop()
