"""OS bits: file lock, atomic write, desktop notification, logger. stdlib only."""

import os
import sys
import time
import shutil
import logging
import threading
import subprocess


class FileLock:
    # O_EXCL = "create only if missing" -> one process wins, rest get FileExistsError.
    # Reclaim after `stale` seconds in case the holder crashed.

    def __init__(self, target, timeout=10.0, poll=0.05, stale=30.0):
        self.path    = str(target) + ".lock"
        self.timeout = timeout
        self.poll    = poll
        self.stale   = stale
        self._fd     = None

    def acquire(self):
        start = time.time()
        while True:
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(self._fd, f"{os.getpid()} {time.time():.0f}".encode())
                return self
            except FileExistsError:
                # steal it if abandoned
                try:
                    if time.time() - os.path.getmtime(self.path) > self.stale:
                        os.remove(self.path)
                        continue
                except (FileNotFoundError, PermissionError):
                    continue
                if time.time() - start >= self.timeout:
                    raise TimeoutError(f"Timed out acquiring lock: {self.path}")
                time.sleep(self.poll)
            except PermissionError:
                # windows: this raises PermissionError, not FileExistsError, mid-race. just retry.
                if time.time() - start >= self.timeout:
                    raise TimeoutError(f"Timed out acquiring lock: {self.path}")
                time.sleep(self.poll)

    def release(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        # same windows quirk on the way out
        for _ in range(50):
            try:
                os.remove(self.path)
                return
            except FileNotFoundError:
                return
            except PermissionError:
                time.sleep(0.01)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


def atomic_write_text(path, text, encoding="utf-8"):
    # write -> fsync -> rename. crash anywhere = old file survives.
    directory = os.path.dirname(os.path.abspath(path)) or "."
    tmp = os.path.join(directory, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def pid_alive(pid):
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        return False
    return True


def notify(title, message, blocking=False):
    # native popup. windows -> MessageBox, mac -> osascript, linux -> notify-send,
    # else stderr. threaded by default so the daemon loop isn't blocked.
    def _show():
        try:
            if os.name == "nt":
                import ctypes
                MB_OK            = 0x0
                MB_ICONINFO      = 0x40
                MB_SETFOREGROUND = 0x10000
                MB_SYSTEMMODAL   = 0x1000
                ctypes.windll.user32.MessageBoxW(
                    0, str(message), str(title),
                    MB_OK | MB_ICONINFO | MB_SETFOREGROUND | MB_SYSTEMMODAL)
                return
            if sys.platform == "darwin":
                script = f'display notification "{message}" with title "{title}"'
                subprocess.run(["osascript", "-e", script], check=False)
                return
            if shutil.which("notify-send"):
                subprocess.run(["notify-send", str(title), str(message)], check=False)
                return
        except Exception:
            pass
        sys.stderr.write(f"\a[{title}] {message}\n")
        sys.stderr.flush()

    if blocking:
        _show()
    else:
        threading.Thread(target=_show, daemon=True).start()


def get_logger(name, logfile):
    # don't add the handler twice on re-import
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(logfile, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s  pid=%(process)d  [%(levelname)s]  %(message)s")
        )
        logger.addHandler(handler)
        logger.propagate = False
    return logger
