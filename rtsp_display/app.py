"""Main application — owns the tkinter root, logo, layout frames, and orchestration."""

import logging
import time
import tkinter as tk
from typing import Dict, List, Optional

from rtsp_display.config import Config
from rtsp_display.feed_manager import FeedManager
from rtsp_display.logo import LogoAnimation
from rtsp_display.mqtt_client import MQTTClient

logger = logging.getLogger(__name__)

# Supported layout names → (columns, rows)
LAYOUTS: Dict[str, tuple] = {
    "1x1": (1, 1),
    "2x2": (2, 2),
}


class RTSPDisplayApp:
    """Top-level application object.

    Responsibilities
    ----------------
    * Create and configure the fullscreen tkinter window.
    * Show the animated logo when idle.
    * Build a grid of tkinter Frames when feeds are requested, hand their
      X11 window IDs to FeedManager so ffplay can embed into them.
    * Receive MQTT commands and dispatch to the correct handler.
    * Periodically publish status back to MQTT.
    """

    STATUS_INTERVAL_MS = 30_000  # publish status every 30 s

    def __init__(self, config: Config) -> None:
        self._config = config
        self._current_layout: Optional[str] = None
        self._current_urls: List[str] = []
        self._feed_frames: List[tk.Frame] = []
        self._feed_container: Optional[tk.Frame] = None
        self._app_start = time.time()

        # ---- tkinter window ----
        self.root = tk.Tk()
        self.root.title("RTSP Remote Video Display")

        bg = config.get("display", "background_color", default="#0a0a0a")
        accent = config.get("display", "accent_color", default="#00d4ff")
        self.root.configure(bg=bg)

        fullscreen = config.get("display", "fullscreen", default=True)
        if fullscreen:
            self.root.attributes("-fullscreen", True)

        # Suppress the default close button in kiosk mode
        self.root.protocol("WM_DELETE_WINDOW", self._noop_close)

        # ---- Animated logo ----
        self._logo = LogoAnimation(self.root, bg_color=bg, accent=accent)
        self._logo.show()

        # ---- Feed manager ----
        self._feeds = FeedManager(
            config,
            on_status_change=self._on_feed_status_change,
        )

        # ---- MQTT ----
        self._mqtt = MQTTClient(config, command_handler=self._handle_mqtt_command)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        logger.info("RTSP Remote Video Display starting up")
        self._mqtt.connect()
        self._schedule_status_publish()
        self.root.mainloop()
        # Cleanup after mainloop exits
        self._feeds.clear()
        self._mqtt.disconnect()

    # ------------------------------------------------------------------
    # MQTT command handling
    # ------------------------------------------------------------------

    def _handle_mqtt_command(self, payload: dict) -> None:
        """Called from the MQTT thread — dispatch to tkinter main thread."""
        self.root.after(0, lambda p=payload: self._process_command(p))

    def _process_command(self, payload: dict) -> None:
        action = payload.get("action", "").lower().strip()
        logger.info("Processing command: %s", action)
        dispatch = {
            "show_feed":    self._cmd_show_feed,
            "set_layout":   self._cmd_set_layout,
            "show_preset":  self._cmd_show_preset,
            "clear":        self._cmd_clear,
            "ping":         self._cmd_ping,
        }
        handler = dispatch.get(action)
        if handler:
            try:
                handler(payload)
            except Exception as exc:
                logger.error("Error executing command '%s': %s", action, exc, exc_info=True)
        else:
            logger.warning("Unknown command action: '%s'", action)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _cmd_show_feed(self, payload: dict) -> None:
        """Show one or more feeds in the requested layout.

        Expected payload::

            {
                "action": "show_feed",
                "layout": "2x2",          # optional, defaults to 1x1
                "feeds": [
                    {"slot": 0, "url": "rtsp://..."},
                    {"slot": 1, "url": "rtsp://..."}
                ]
            }
        """
        layout = payload.get("layout", "1x1")
        if layout not in LAYOUTS:
            logger.warning("Unknown layout '%s'; falling back to 1x1", layout)
            layout = "1x1"

        max_slots = LAYOUTS[layout][0] * LAYOUTS[layout][1]
        urls: List[str] = [""] * max_slots

        for feed_spec in payload.get("feeds", []):
            slot = int(feed_spec.get("slot", 0))
            url = str(feed_spec.get("url", ""))
            if 0 <= slot < max_slots:
                urls[slot] = url

        self._activate_layout(layout, urls)

    def _cmd_set_layout(self, payload: dict) -> None:
        """Switch layout while keeping existing feed URLs where possible."""
        layout = payload.get("layout", "1x1")
        if layout not in LAYOUTS:
            logger.warning("Unknown layout '%s'", layout)
            return
        max_slots = LAYOUTS[layout][0] * LAYOUTS[layout][1]
        existing = (self._current_urls + [""] * max_slots)[:max_slots]
        self._activate_layout(layout, existing)

    def _cmd_show_preset(self, payload: dict) -> None:
        """Load a named preset from config.

        Preset config example::

            presets:
              front_cameras:
                layout: "2x2"
                feeds:
                  - "rtsp://camera1/stream"
                  - "rtsp://camera2/stream"
        """
        name = payload.get("name", "")
        presets: dict = self._config.get("presets", default={}) or {}
        preset = presets.get(name)
        if not preset:
            logger.warning("Preset '%s' not found in config", name)
            return
        layout = preset.get("layout", "1x1")
        feeds_list = preset.get("feeds", [])
        # Build urls list
        max_slots = LAYOUTS.get(layout, (1, 1))[0] * LAYOUTS.get(layout, (1, 1))[1]
        urls = (list(feeds_list) + [""] * max_slots)[:max_slots]
        self._activate_layout(layout, urls)

    def _cmd_clear(self, payload: Optional[dict] = None) -> None:
        """Stop all feeds and return to the logo screen."""
        logger.info("Clearing all feeds — showing logo")
        self._feeds.clear()
        self._current_urls = []
        self._current_layout = None
        self._destroy_feed_container()
        self._logo.show()
        self._publish_status("idle")

    def _cmd_ping(self, payload: Optional[dict] = None) -> None:
        """Respond to a ping with an immediate status update."""
        self._publish_status()

    # ------------------------------------------------------------------
    # Layout / frame management
    # ------------------------------------------------------------------

    def _activate_layout(self, layout: str, urls: List[str]) -> None:
        """Tear down the current layout and build a new one with *urls*."""
        active = [u for u in urls if u]
        if not active:
            self._cmd_clear()
            return

        cols, rows = LAYOUTS[layout]
        logger.info("Activating layout %s (%dx%d) with %d feed(s)", layout, cols, rows, len(active))

        self._current_layout = layout
        self._current_urls = list(urls)

        # Hide logo, rebuild frames
        self._logo.hide()
        self._destroy_feed_container()
        self._build_feed_frames(cols, rows)

        # Realise canvases so winfo_width/height return valid dimensions
        self.root.update()

        self._feeds.set_feeds(urls, canvases=self._feed_frames, root=self.root)
        self._publish_status("playing")

    def _build_feed_frames(self, cols: int, rows: int) -> None:
        """Create a cols×rows grid of Canvas widgets inside the root window."""
        self._feed_container = tk.Frame(self.root, bg="black")
        self._feed_container.pack(fill=tk.BOTH, expand=True)
        self._feed_frames = []

        for r in range(rows):
            self._feed_container.rowconfigure(r, weight=1)
        for c in range(cols):
            self._feed_container.columnconfigure(c, weight=1)

        for r in range(rows):
            for c in range(cols):
                canvas = tk.Canvas(
                    self._feed_container,
                    bg="#050505",
                    bd=0,
                    highlightthickness=0,
                )
                canvas.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
                self._feed_frames.append(canvas)

    def _destroy_feed_container(self) -> None:
        if self._feed_container:
            self._feed_container.destroy()
            self._feed_container = None
        self._feed_frames = []

    # ------------------------------------------------------------------
    # Status publishing
    # ------------------------------------------------------------------

    def _schedule_status_publish(self) -> None:
        self._publish_status()
        self.root.after(self.STATUS_INTERVAL_MS, self._schedule_status_publish)

    def _publish_status(self, state: Optional[str] = None) -> None:
        if state is None:
            state = "playing" if self._feeds.is_active() else "idle"
        self._mqtt.publish_status(
            state=state,
            layout=self._current_layout,
            feeds=self._feeds.get_status(),
        )

    def _on_feed_status_change(self, slot_id: int, status: str) -> None:
        """Called from feed worker threads when a slot status changes."""
        logger.debug("Feed slot %d status: %s", slot_id, status)
        # Publish an updated status snapshot (schedule on main thread)
        self.root.after(0, self._publish_status)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _noop_close(self) -> None:
        """Ignore window close events — kiosk mode has no keyboard."""
        logger.debug("WM_DELETE_WINDOW ignored (kiosk mode)")
