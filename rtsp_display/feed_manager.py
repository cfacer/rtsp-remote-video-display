"""Feed Manager — captures RTSP streams and renders into tkinter Canvas widgets.

Each FeedSlot runs a background capture thread (OpenCV/RTSP) and a
tkinter after() display loop that converts frames to PhotoImages and
paints them onto the slot's Canvas.  All rendering stays inside the
single tkinter window — no external subprocess windows.
"""

import logging
import os
import threading
import time
from typing import Callable, Dict, List, Optional

import cv2
from PIL import Image, ImageTk

from rtsp_display.utils import redact_url

logger = logging.getLogger(__name__)

# Pillow >=10 moved resampling filters to Image.Resampling
_RESAMPLE = getattr(getattr(Image, "Resampling", Image), "BILINEAR", 1)


class FeedSlot:
    """Manages one RTSP stream displayed on a tkinter Canvas."""

    DISPLAY_INTERVAL_MS = 33  # ~30 fps display refresh

    def __init__(
        self,
        slot_id: int,
        url: str,
        canvas,                                    # tk.Canvas
        root,                                      # tk.Tk
        feed_config: Optional[dict] = None,
        on_status_change: Optional[Callable] = None,
    ) -> None:
        self.slot_id = slot_id
        self.url = url
        self.canvas = canvas
        self.root = root
        self._cfg = feed_config or {}
        self._on_status_change = on_status_change

        self.status: str = "stopped"
        self.restart_count: int = 0
        self.started_at: Optional[float] = None

        self._running: bool = False
        self._cap: Optional[cv2.VideoCapture] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._latest_frame: Optional[Image.Image] = None
        self._frame_lock = threading.Lock()
        self._photo: Optional[ImageTk.PhotoImage] = None   # prevent GC
        self._canvas_image_id: Optional[int] = None
        self._after_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self.started_at = time.time()
        self._set_status("starting")
        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True
        )
        self._capture_thread.start()
        self._schedule_display()

    def stop(self) -> None:
        self._running = False
        # Release the capture immediately to unblock any pending cap.read() call
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._set_status("stopped")

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_info(self) -> dict:
        return {
            "slot": self.slot_id,
            "url": redact_url(self.url),
            "status": self.status,
            "restart_count": self.restart_count,
            "uptime_s": int(time.time() - self.started_at) if self.started_at else 0,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _set_status(self, status: str) -> None:
        if self.status != status:
            self.status = status
            if self._on_status_change:
                self._on_status_change(self.slot_id, status)

    def _capture_loop(self) -> None:
        """Background thread: opens the RTSP stream and reads frames continuously."""
        reconnect_delay = float(self._cfg.get("reconnect_delay", 5))
        stall_timeout = float(self._cfg.get("stall_timeout", 30))
        rtsp_transport = self._cfg.get("rtsp_transport", "tcp")

        # Configure RTSP transport for the OpenCV/FFMPEG backend
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = f"rtsp_transport;{rtsp_transport}"

        while self._running:
            try:
                logger.info(
                    "Slot %d: opening %s", self.slot_id, redact_url(self.url)
                )
                self._cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
                try:
                    self._cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10_000)
                    self._cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(stall_timeout * 1_000))
                except Exception:
                    pass  # older OpenCV builds may not support these props

                if not self._cap.isOpened():
                    raise RuntimeError("Failed to open RTSP stream")

                self._set_status("playing")
                last_frame_time = time.time()

                while self._running:
                    ret, frame = self._cap.read()
                    if not ret:
                        elapsed = time.time() - last_frame_time
                        if elapsed > stall_timeout:
                            logger.warning(
                                "Slot %d: stall detected (%.0f s without a frame)",
                                self.slot_id, elapsed,
                            )
                            self._set_status("stalled")
                        break

                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    with self._frame_lock:
                        self._latest_frame = Image.fromarray(frame_rgb)
                    last_frame_time = time.time()

            except Exception as exc:
                logger.warning("Slot %d: capture error: %s", self.slot_id, exc)
            finally:
                if self._cap is not None:
                    self._cap.release()
                    self._cap = None

            if self._running:
                self.restart_count += 1
                self._set_status("restarting")
                logger.info(
                    "Slot %d: reconnecting in %.0f s (attempt %d)…",
                    self.slot_id, reconnect_delay, self.restart_count,
                )
                time.sleep(reconnect_delay)

    def _schedule_display(self) -> None:
        """Main-thread loop: renders the latest captured frame onto the Canvas."""
        if not self._running:
            return

        with self._frame_lock:
            img = self._latest_frame

        if img is not None:
            try:
                w = self.canvas.winfo_width()
                h = self.canvas.winfo_height()
                if w > 1 and h > 1:
                    img_resized = img.resize((w, h), _RESAMPLE)
                    photo = ImageTk.PhotoImage(img_resized)
                    if self._canvas_image_id is None:
                        self._canvas_image_id = self.canvas.create_image(
                            0, 0, anchor="nw", image=photo
                        )
                    else:
                        self.canvas.itemconfig(self._canvas_image_id, image=photo)
                    self._photo = photo  # keep reference — prevents GC
            except Exception:
                pass  # canvas may be destroyed during layout transitions

        self._after_id = self.root.after(self.DISPLAY_INTERVAL_MS, self._schedule_display)


# ---------------------------------------------------------------------------


class FeedManager:
    """Manages a collection of FeedSlots."""

    def __init__(self, config, on_status_change: Optional[Callable] = None) -> None:
        self._config = config
        self._on_status_change = on_status_change
        self._slots: Dict[int, FeedSlot] = {}

    def set_feeds(
        self,
        urls: List[str],
        canvases: List,    # List[tk.Canvas]
        root,              # tk.Tk
    ) -> None:
        """Stop all current slots and start new ones.

        Args:
            urls:     Ordered list of RTSP URLs.  Empty string → skip slot.
            canvases: Parallel list of tk.Canvas widgets to render into.
            root:     The tkinter root window (for after() scheduling).
        """
        self.clear()
        feed_cfg = self._config.get("feeds", default={})

        for idx, url in enumerate(urls):
            if not url or idx >= len(canvases):
                continue
            slot = FeedSlot(
                slot_id=idx,
                url=url,
                canvas=canvases[idx],
                root=root,
                feed_config=feed_cfg,
                on_status_change=self._on_status_change,
            )
            slot.start()
            self._slots[idx] = slot
            logger.info("Feed slot %d started: %s", idx, redact_url(url))

    def clear(self) -> None:
        for slot in list(self._slots.values()):
            slot.stop()
        self._slots.clear()
        logger.info("All feed slots cleared")

    def is_active(self) -> bool:
        return bool(self._slots)

    def get_status(self) -> List[dict]:
        return [slot.get_info() for slot in self._slots.values()]
