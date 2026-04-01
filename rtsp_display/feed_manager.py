"""Feed Manager — spawns and supervises ffplay subprocesses.

Each *FeedSlot* manages one ffplay process.  It monitors the process
for two failure modes:

1. **Hard crash** — the process exits unexpectedly.  Detected via
   ``process.poll()``.
2. **Soft stall** — the process is running but the stream is frozen.
   Detected by watching ffplay's stderr output; ffplay emits periodic
   progress lines (e.g. A-V sync info) when the stream is live.  If
   no output arrives within *stall_timeout* seconds the slot is
   considered stalled and the process is restarted.

On Linux the video is embedded directly into a tkinter Frame via the
X11 ``-wid`` flag.  On macOS (development mode) ffplay opens its own
window so the developer can observe the stream without needing an X
server.
"""

import logging
import subprocess
import sys
import threading
import time
from typing import Callable, Dict, List, Optional

from rtsp_display.utils import redact_credentials as _redact_credentials
from rtsp_display.utils import redact_url as _redact_url

logger = logging.getLogger(__name__)


class FeedSlot:
    """Manages one ffplay subprocess for a single display slot."""

    def __init__(
        self,
        slot_id: int,
        url: str,
        window_id: Optional[int] = None,
        feed_config: Optional[dict] = None,
        on_status_change: Optional[Callable] = None,
    ) -> None:
        self.slot_id = slot_id
        self.url = url
        self.window_id = window_id       # X11 window ID for embedding (Linux only)
        self._cfg = feed_config or {}
        self._on_status_change = on_status_change

        self.process: Optional[subprocess.Popen] = None
        self.status: str = "stopped"    # stopped | starting | playing | stalled | error
        self.restart_count: int = 0
        self.started_at: Optional[float] = None
        self.last_activity: Optional[float] = None

        self._running: bool = False
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the ffplay process and supervision threads."""
        self._running = True
        self._launch()

    def stop(self) -> None:
        """Terminate the ffplay process and stop supervision."""
        self._running = False
        self._set_status("stopped")
        if self.process and self.process.poll() is None:
            logger.info("Slot %d: terminating ffplay", self.slot_id)
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Slot %d: force-killing ffplay", self.slot_id)
                self.process.kill()
                self.process.wait()
        self.process = None

    # ------------------------------------------------------------------
    # Internal — process management
    # ------------------------------------------------------------------

    def _launch(self) -> None:
        """(Re)launch the ffplay subprocess."""
        # Kill any existing process first
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait()

        cmd = self._build_command()
        logger.info("Slot %d: launching → %s", self.slot_id, _redact_credentials(" ".join(cmd)))

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self.started_at = time.time()
            self.last_activity = time.time()
            self._set_status("starting")

            # Stderr monitor — updates last_activity so the watchdog can
            # distinguish a live stream from a frozen one
            self._stderr_thread = threading.Thread(
                target=self._monitor_stderr, daemon=True
            )
            self._stderr_thread.start()

            # Watchdog — restarts the slot on crash or stall
            if self._watchdog_thread is None or not self._watchdog_thread.is_alive():
                self._watchdog_thread = threading.Thread(
                    target=self._watchdog, daemon=True
                )
                self._watchdog_thread.start()

        except FileNotFoundError:
            logger.error(
                "Slot %d: 'ffplay' not found.  Install ffmpeg: sudo apt install ffmpeg",
                self.slot_id,
            )
            self._set_status("error")
        except Exception as exc:
            logger.error("Slot %d: failed to start ffplay: %s", self.slot_id, exc)
            self._set_status("error")

    def _build_command(self) -> List[str]:
        rtsp_transport = self._cfg.get("rtsp_transport", "tcp")
        extra_args: List[str] = self._cfg.get("ffplay_extra_args", [])

        cmd = [
            "ffplay",
            "-rtsp_transport", rtsp_transport,
            "-timeout", "10000000",         # 10 s in µs
            # Stderr verbosity — needed for stall detection
            "-loglevel", "info",
            # UI flags
            "-noborder",
            "-autoexit",                    # exit when stream ends naturally
        ]

        if self.window_id and sys.platform.startswith("linux"):
            # Embed into the tkinter frame's X11 window
            cmd += ["-wid", str(self.window_id)]
        # On macOS (dev mode) ffplay opens its own floating window

        cmd += extra_args
        cmd += [self.url]
        return cmd

    # ------------------------------------------------------------------
    # Internal — monitoring
    # ------------------------------------------------------------------

    def _monitor_stderr(self) -> None:
        """Read stderr lines from ffplay; update last_activity on any output."""
        if not self.process or not self.process.stderr:
            return
        try:
            for line in self.process.stderr:
                line = line.rstrip()
                if not line:
                    continue
                self.last_activity = time.time()
                # Transition to playing once we see stream data
                if self.status == "starting":
                    self._set_status("playing")
                safe_line = _redact_credentials(line)
                ll = safe_line.lower()
                if any(kw in ll for kw in ("error", "failed", "invalid", "broken")):
                    logger.warning("Slot %d ffplay: %s", self.slot_id, safe_line)
                else:
                    logger.debug("Slot %d ffplay: %s", self.slot_id, safe_line)
        except Exception:
            pass  # stderr pipe closed when process exits

    def _watchdog(self) -> None:
        """Poll the process every 5 s; restart on crash or stall."""
        stall_timeout: float = float(self._cfg.get("stall_timeout", 30))
        reconnect_delay: float = float(self._cfg.get("reconnect_delay", 5))

        while self._running:
            time.sleep(5)
            if not self._running:
                break

            # --- Hard crash ---
            if self.process and self.process.poll() is not None:
                exit_code = self.process.returncode
                logger.warning(
                    "Slot %d: ffplay exited (code %d); restarting in %.0f s…",
                    self.slot_id, exit_code, reconnect_delay,
                )
                self.restart_count += 1
                self._set_status("restarting")
                time.sleep(reconnect_delay)
                if self._running:
                    self._launch()
                continue

            # --- Soft stall ---
            if self.last_activity and (time.time() - self.last_activity) > stall_timeout:
                logger.warning(
                    "Slot %d: stall detected (no output for %.0f s); restarting…",
                    self.slot_id, stall_timeout,
                )
                self.restart_count += 1
                self._set_status("stalled")
                if self.process and self.process.poll() is None:
                    self.process.kill()
                    self.process.wait()
                time.sleep(reconnect_delay)
                if self._running:
                    self._launch()

    def _set_status(self, status: str) -> None:
        self.status = status
        if self._on_status_change:
            try:
                self._on_status_change(self.slot_id, status)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_info(self) -> dict:
        return {
            "slot": self.slot_id,
            "url": _redact_url(self.url),
            "status": self.status,
            "restart_count": self.restart_count,
            "uptime_s": int(time.time() - self.started_at) if self.started_at else 0,
        }


# ---------------------------------------------------------------------------


class FeedManager:
    """Manages the full set of active FeedSlots."""

    def __init__(self, config, on_status_change: Optional[Callable] = None) -> None:
        self._config = config
        self._on_status_change = on_status_change
        self._slots: Dict[int, FeedSlot] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_feeds(
        self,
        urls: List[str],
        window_ids: Optional[List[Optional[int]]] = None,
    ) -> None:
        """Stop all current slots and start new ones.

        Args:
            urls: Ordered list of RTSP URLs.  Empty string / None → skip slot.
            window_ids: Parallel list of X11 window IDs (Linux) or None.
        """
        self.clear()
        feed_cfg = self._config.get("feeds", default={})

        for idx, url in enumerate(urls):
            if not url:
                continue
            wid = (window_ids[idx] if window_ids and idx < len(window_ids) else None)
            slot = FeedSlot(
                slot_id=idx,
                url=url,
                window_id=wid,
                feed_config=feed_cfg,
                on_status_change=self._on_status_change,
            )
            slot.start()
            self._slots[idx] = slot
            logger.info("Feed slot %d started: %s", idx, _redact_url(url))

    def clear(self) -> None:
        """Stop and remove all active slots."""
        for slot in list(self._slots.values()):
            slot.stop()
        self._slots.clear()
        logger.info("All feed slots cleared")

    def is_active(self) -> bool:
        return bool(self._slots)

    def get_status(self) -> List[dict]:
        return [slot.get_info() for slot in self._slots.values()]
