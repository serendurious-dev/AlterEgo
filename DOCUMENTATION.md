# AlterEgo Agent - Technical Documentation

This is the deeper write-up for anyone (including my future self) who wants to
understand how the project actually works under the hood. The README is the front
door. This is the engine room.

Author: Prodipta Acharjee
Course: Operating Systems (004310-006)

---

## 1. The big picture

The whole project is built around one idea: two processes sharing the same files.

There is the main app (the GUI or the terminal), and there is a background reminder
daemon. They never talk directly. They talk through files. The moment you have two
processes touching the same data, you inherit every classic operating-system
problem, and solving those problems honestly is what makes this an OS project
instead of just a habit tracker.

So the architecture has three layers:

1. **The interface layer** (`alterego_gui.py`, and the menu/CLI in `alterego.py`).
   This is just presentation. It never contains real logic.
2. **The logic layer** (`features.py`, `coaching.py`, `game.py`, `wisdom.py`).
   Pure functions, mostly. Given a profile and a log, they return data or text.
   They are easy to test because they have no side effects.
3. **The OS layer** (`osutil.py` and the daemon code in `alterego.py`). This is
   where locking, atomic writes, signals, IPC, and notifications live.

`alterego.py` sits in the middle, imports the logic functions, and re-exports them
so the GUI and the tests can all reach them through one namespace.

---

## 2. The 6-phase agent loop

The original concept was an "Observe, Think, Act, Evolve" agent. The whole daily
flow follows that, with two extra phases for setup and reporting.

**Phase 1 - Setup.** First run only. You define three goals (name, unit, target,
priority weight, baseline), build your persona, and write your identity line. This
is saved to `alterego_profile.json`.

**Phase 2 - Observe.** Each day you rate energy and mood, then log your actual
performance per goal. If you miss a goal, the app asks why (the obstacle).

**Phase 3 - Think.** The scoring math:

```
gap_i  = max(0, target_i - actual_i) * weight_i
score  = (1 - sum(gap_i) / sum(target_i * weight_i)) * 100,  clamped to [0, 100]
```

The goal with the largest weighted gap is your weakest area for the day.

**Phase 4 - Act.** The agent produces the daily report: the score, a stance and
its reasoning, the teacher and friend voices, the weakest area, a targeted
micro-challenge, and the game results (XP, draw, level-up).

**Phase 5 - Evolve.** Every 7 days it looks at the last week. Goals you hit 80% of
the time get their target raised by 10%. Goals you miss 40% of the time get their
strategy restructured. A weekly letter in your AlterEgo's voice is written.

**Phase 6 - Report.** Streaks, the 7 and 30-day windows, intention accuracy, and
the trend chart.

---

## 3. The operating-system concepts, mapped to code

This is the part that matters for grading, so here is exactly where each concept
lives and why it is there.

### 3.1 Mutual exclusion (`osutil.FileLock`)

The problem: the app and the daemon can both try to write `profile.json` or
`log.csv` at the same moment. Two writers can both read the old value, both add to
it, and one overwrites the other. That is a lost update, a classic race condition.

The solution is a mutex. `FileLock.acquire` does this:

```python
self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
```

`O_CREAT | O_EXCL` means "create this file, but fail if it already exists." The
operating system guarantees that check-and-create happens atomically in a single
syscall. So if ten processes race, exactly one succeeds and the rest get
`FileExistsError`. That is a test-and-set primitive, the building block of a lock.

Two refinements worth knowing:
- **Stale-lock recovery.** If the holder crashes, the lock file is never deleted,
  which would deadlock everything. So if the lock file is older than 30 seconds,
  it is assumed abandoned and reclaimed.
- **The Windows quirk.** On Windows, deleting the lock file while another thread is
  opening it raises `PermissionError` instead of `FileExistsError`. The lock
  treats that as transient contention and retries. I only found this because the
  concurrency test caught it.

The proof it works is in `test_alterego.py`: eight threads each do fifty
read-modify-write increments on a shared counter, all through the lock. The result
is exactly 400 every time. Without the lock you get lost updates and a number
below 400.

### 3.2 Atomic writes (`osutil.atomic_write_text`)

The problem: if you `open(file, "w")` and the program crashes mid-write, the file
is truncated and corrupt. Your whole profile is gone.

The solution:

```python
# write everything to a temp file
with open(tmp, "w") as f:
    f.write(text); f.flush(); os.fsync(f.fileno())
os.replace(tmp, path)   # atomic rename
```

`os.replace` (a rename) is atomic on both NTFS and POSIX. So the complete new
content is written to a temp file first, forced to disk with `fsync`, and then the
name is flipped over in one indivisible step. A crash before the rename leaves the
old file intact; a crash after leaves the new file intact. The reader never sees a
partial file. `fsync` matters because `write` only puts data in the OS page cache,
not necessarily on the physical disk.

### 3.3 The daemon (`reminder_start`, `daemon_run`)

A reminder is useless if it only fires while the app is open. So it runs as a
detached background process:

```python
if os.name == "nt":
    kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
else:
    kwargs["start_new_session"] = True
subprocess.Popen([sys.executable, __file__, "--daemon-run"], **kwargs)
```

This spawns the same script with a hidden `--daemon-run` flag. The detach flags
cut it loose from the terminal so it outlives the parent. On POSIX,
`start_new_session=True` is the modern equivalent of the classic double-fork plus
setsid daemonization.

### 3.4 Signals

The daemon installs handlers so it shuts down cleanly instead of being killed
mid-write:

```python
def _handle(signum, _frame):
    stop["flag"] = True
for sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(sig, _handle)
```

Instead of dying on the signal, it sets a flag and lets the loop exit through its
`finally` block, which removes its own pid, status, and stop files. Worth being
honest about: signals are a POSIX strength. On Windows `SIGTERM` delivery is
limited, so the stop-flag file is the primary shutdown mechanism and signals are
the fallback. Using two mechanisms on purpose is the point.

### 3.5 Inter-process communication

The app and the daemon are separate processes with separate memory. They
coordinate through three files:

| File | Direction | Meaning |
|---|---|---|
| `alterego_daemon.pid` | daemon to app | "my process id is N" |
| `alterego_daemon.status` | daemon to app | a heartbeat: timestamp, pid, did you check in today, current mode |
| `alterego_daemon.stop` | app to daemon | "please shut down" |

The app decides the daemon is alive by checking heartbeat freshness, not just by
the pid, so it can tell a crashed daemon from a live one. To stop it, the app
writes the stop-flag and waits for the daemon's cleanup, only force-killing as a
last resort.

This is file-based IPC. I chose files over sockets because the two processes are
started at completely different times by different commands. There is no
parent-child pipe between them, and a socket would need port management and both
ends running at once. The honest trade-off is latency equal to the polling
interval, which is fine for a once-a-day reminder.

### 3.6 The smaller OS touches

- **Native notifications** (`osutil.notify`): `user32.MessageBoxW` via ctypes on
  Windows, `osascript` on macOS, `notify-send` on Linux, with a stderr fallback.
- **Configurable daemon**: the mode (watchdog, adaptive, silent) is read from the
  profile on every loop tick, so it reconfigures live without a restart.
- **Data integrity**: every log row stores a short SHA-256 of its date, score, and
  challenge. The history screen recomputes and flags any row edited outside the
  app as `[modified]`.
- **Crash recovery and audit**: a corrupt profile is renamed to `.corrupt` and
  rebuilt instead of crashing. On launch, an audit cleans up stale daemon pids and
  leftover temp files.
- **Structured logging**: every check-in, evolution, daemon event, badge, and
  error is timestamped with the process id into `alterego_events.log`.

---

## 4. The data files

| File | What it holds |
|---|---|
| `alterego_profile.json` | goals, persona, identity, level, xp, badges, personal bests, streak freezes, theme, ui mode, all settings |
| `alterego_log.csv` | one row per day: date, score, energy, mood, reflection, day label, the per-goal numbers and obstacles, and the integrity hash |
| `alterego_intentions.json` | your stated weekly intentions |
| `alterego_events.log` | the audit trail |
| generated documents | weekly letters, score cards, charts, heatmaps, backup zips |

The CSV schema is forward-compatible. `_log_entry` rewrites the whole file each
time (it is small) using `DictWriter`, so when I added new columns over time, old
log files kept working and just got the new fields filled in. The full rewrite is
also how the log gets the same atomic and locked write as the profile.

One robustness note: `_read_logs` only returns rows that have a date and a numeric
score. That single gate at the source keeps every downstream `float(score)` call
from crashing on a hand-edited file.

---

## 5. The intelligence layers

### 5.1 The coaching brain (`coaching.py`)

This is the part that decides how to treat you. `coaching_state` reads every
signal (energy, mood, score, streak, recovery, burnout, the recent trend) and
returns one coherent stance:

- **push** when you had the energy and still fell short
- **celebrate** on a genuinely strong day
- **steady** on an ordinary day
- **recover** while climbing out of a slump
- **grace** when you are depleted, at burnout risk, or you ask for a rest

It also computes whether you did **enough**, combining three ideas: did you beat
what today's energy realistically allowed (effort vs capacity), did you show up at
all when you were running on empty, and did you keep your streak alive. So a 40 on
a low-energy day can beat expectation and the agent tells you to rest easy instead
of grinding you down.

`ui_density` uses the same signals to decide how much of the app to show: calm,
standard, or rich. Nothing is removed, the interface just adapts.

### 5.2 The soul layer (`wisdom.py`)

`dual_voice` returns the teacher line and the friend line for the day, banded by
score and stance. `principle_for_state` surfaces a Stoic, Kaizen, or
self-compassion principle that fits your current state. `growth_season` names the
chapter you are in (First Steps, Building, Thriving, Plateau, the Dip,
Rebuilding). `identity_line` reflects back the "I am becoming someone who..." you
wrote at setup.

### 5.3 The game layer (`game.py`)

XP per check-in scaled by score, streak, and a combo multiplier that grows the
longer you stay consistent. Levels and titles. An evolving avatar. A variable
reward draw. The Procrastination Monster. Progressive screen unlocks that gate the
advanced screens behind levels, which doubles as an anti-overwhelm mechanic.

### 5.4 The analytics (`features.py`)

The persona messages, the badges (including the funny ones), the insight engine
(correlation between goal success and score, weekday averages, habit stacks), the
behavioral pattern engine (trigger chains, recovery time, streak personality), the
weekly letter, the score card, the heatmap, the backup zip, the state audit, and
the integrity hashing all live here.

---

## 6. Testing

133 tests across five test files, run with:

```
python -m unittest discover -p "test_*.py" -v
```

The ones I would point a grader at:

- `test_filelock_is_mutually_exclusive` proves the mutex under 8 real threads.
- `test_atomic_write_*` proves the crash-safe write and that no temp files leak.
- `test_corrupt_profile_is_quarantined` proves the recovery path.
- `test_read_logs_drops_non_numeric_scores` and `test_think_handles_empty_goals`
  prove the bad-data hardening.
- The coaching, game, and wisdom test files prove the decision logic, the "enough"
  models, and the voices.

---

## 7. Known limitations and honest notes

- Signals are weaker on Windows than POSIX, which is why the stop-flag file is the
  primary daemon shutdown path. This is documented, not accidental.
- The intelligence features (insights, patterns, burnout, plateau) need several
  days of real data before they say anything meaningful. With little data they
  correctly report "not enough data yet."
- `_log_entry` rewrites the whole CSV on every check-in. For a year of data that is
  365 small rows, so it is a deliberate trade of a tiny bit of work for getting
  atomic writes and forward-compatible columns for free.
- The emoji and color are GUI-only. The terminal stays plain ASCII on purpose so
  it never hits an encoding error on Windows.
