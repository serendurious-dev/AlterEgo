"""Generates a clean, horizontal system-architecture diagram for the AlterEgo Agent."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

INK   = "#1E293B"
BLUE  = "#3B82F6"
INDIGO= "#6366F1"
GREEN = "#22C55E"
AMBER = "#F59E0B"
GRAY  = "#475569"
RED   = "#EF4444"
BG    = "#F8FAFC"

fig, ax = plt.subplots(figsize=(18, 9.6))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 180)
ax.set_ylim(0, 96)
ax.axis("off")


def box(x, y, w, h, lines, color, tcolor="white", title_fs=12, sub_fs=9.0):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                 boxstyle="round,pad=0.6,rounding_size=2.0",
                 linewidth=0, facecolor=color, zorder=2))
    if isinstance(lines, str):
        lines = [lines]
    step = 4.0
    top = y + h / 2 + (len(lines) - 1) * step / 2
    for i, ln in enumerate(lines):
        ax.text(x + w / 2, top - i * step, ln, ha="center", va="center",
                color=tcolor, zorder=3,
                fontsize=title_fs if i == 0 else sub_fs,
                fontweight="bold" if i == 0 else "normal")


def arrow(x1, y1, x2, y2, color=GRAY, ls="-", double=False):
    style = "<|-|>" if double else "-|>"
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                 mutation_scale=15, lw=1.7, color=color, linestyle=ls, zorder=1))


def alabel(x, y, t, color=GRAY):
    ax.text(x, y, t, ha="center", va="center", fontsize=8, color=color,
            style="italic", zorder=4)


# title
ax.text(90, 92.5, "AlterEgo Agent  -  System Architecture", ha="center",
        va="center", fontsize=18, fontweight="bold", color=INK)
ax.text(90, 88, "a self-improvement agent built on a real operating-system foundation",
        ha="center", va="center", fontsize=11, color=GRAY, style="italic")

# column headers
for x, t in [(38, "INTERFACE"), (71, "CORE"), (111, "LOGIC + OS"), (157, "DATA")]:
    ax.text(x, 83.5, t, ha="center", va="center", fontsize=9,
            color="#94A3B8", fontweight="bold")

# USER
box(3, 46, 16, 14, "USER", INK, title_fs=13)

# interface
box(24, 60, 28, 16, ["Desktop GUI", "alterego_gui.py", "13 screens, themes, charts"], BLUE)
box(24, 36, 28, 16, ["Terminal / CLI", "alterego.py", "menu, flags, --doctor"], BLUE)

# core
box(58, 42, 26, 24, ["CORE AGENT", "alterego.py", "", "Observe  >  Think  >",
                     "Act  >  Evolve", "weighted gap scoring"], INDIGO, title_fs=12, sub_fs=8.6)

# logic + os
box(90, 58, 42, 22, ["LOGIC LAYER",
                     "features  -  analytics, badges, letters",
                     "coaching  -  push / rest / 'enough' brain",
                     "game  -  XP, levels, combos, rewards",
                     "wisdom  -  teacher + friend, principles"],
    GREEN, title_fs=12, sub_fs=8.6)
box(90, 30, 42, 22, ["OS LAYER  (osutil.py)",
                     "FileLock  -  mutex via O_EXCL syscall",
                     "atomic_write_text  -  fsync + rename",
                     "notify  -  signals  -  event logger"],
    AMBER, title_fs=12, sub_fs=8.6)

# data
box(138, 42, 38, 22, ["DATA",
                      "profile.json  -  goals, persona,",
                      "xp, badges, settings",
                      "log.csv  -  daily entries + hash",
                      "every write: locked + atomic"],
    GRAY, title_fs=12, sub_fs=8.6)

# daemon (wide bottom bar)
box(58, 6, 118, 16, ["REMINDER  DAEMON   (separate background process)",
                     "heartbeat + stop-flag + PID files       signal handling (SIGTERM / SIGINT)",
                     "configurable modes (watchdog / adaptive / silent)       native OS notifications"],
    RED, title_fs=12, sub_fs=9.0)

# arrows
arrow(19, 55, 24, 68); alabel(20.5, 63, "uses")
arrow(19, 51, 24, 44)
arrow(52, 68, 58, 58); alabel(55, 64, "calls")
arrow(52, 44, 58, 50)
arrow(84, 60, 90, 69)
arrow(84, 48, 90, 41)
arrow(132, 69, 138, 57); alabel(135, 65, "read /")
arrow(132, 41, 138, 49); alabel(135, 47, "write")
arrow(157, 42, 157, 22, color=RED, ls="--", double=True)
ax.text(160, 32, "IPC\n(shared files)", ha="left", va="center", fontsize=9,
        color=RED, fontweight="bold", style="italic")

ax.text(90, 1.5, "8 modules   |   133 automated tests   |   pure standard library for the OS engine   |   Python + CustomTkinter + matplotlib",
        ha="center", va="center", fontsize=9.5, color=GRAY)

fig.tight_layout()
fig.savefig("alterego_architecture.png", dpi=150, facecolor=BG, bbox_inches="tight")
print("saved alterego_architecture.png")
