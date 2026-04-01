"""Animated idle logo rendered on a tkinter Canvas.

The animation shows a stylised camera icon with:
  - Pulsing glow rings
  - A sweeping scan line across the lens
  - Blinking record indicator
  - Subtle background grid
  - Corner bracket decorations
  - App name and status text
"""
import math
import tkinter as tk


class LogoAnimation:
    """Fullscreen animated idle logo.

    Usage::

        logo = LogoAnimation(root, bg_color="#0a0a0a", accent="#00d4ff")
        logo.show()   # start animating and pack into parent
        logo.hide()   # stop and unpack
    """

    FPS = 30
    FRAME_DELAY_MS = 1000 // FPS
    CYCLE_FRAMES = FPS * 10  # 10-second full animation cycle

    def __init__(
        self,
        parent: tk.Widget,
        bg_color: str = "#0a0a0a",
        accent: str = "#00d4ff",
    ) -> None:
        self._parent = parent
        self.bg_color = bg_color
        self.accent = accent
        self._secondary = "#0066cc"

        self._canvas = tk.Canvas(parent, bg=bg_color, highlightthickness=0)
        self._frame: int = 0
        self._running: bool = False
        self._after_id = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(self) -> None:
        """Pack the canvas and begin animating."""
        self._canvas.pack(fill=tk.BOTH, expand=True)
        if not self._running:
            self._running = True
            self._tick()

    def hide(self) -> None:
        """Stop animating and remove from layout."""
        self._running = False
        if self._after_id is not None:
            try:
                self._canvas.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._canvas.pack_forget()

    # ------------------------------------------------------------------
    # Animation loop
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        if not self._running:
            return
        self._draw()
        self._frame = (self._frame + 1) % self.CYCLE_FRAMES
        self._after_id = self._canvas.after(self.FRAME_DELAY_MS, self._tick)

    def _draw(self) -> None:
        c = self._canvas
        c.delete("all")

        w = c.winfo_width()
        h = c.winfo_height()
        if w < 10 or h < 10:
            return

        cx, cy_base = w // 2, h // 2

        # Slow pulse: 0→1→0 over full cycle
        t_slow = (self._frame / self.CYCLE_FRAMES) * 2 * math.pi
        pulse = 0.5 + 0.5 * math.sin(t_slow)

        # Camera dimensions (responsive)
        cam_w = min(300, max(180, w // 4))
        cam_h = int(cam_w * 0.65)
        cam_cx = cx
        cam_cy = cy_base - 20  # slightly above centre

        self._draw_grid(w, h)
        self._draw_glow(cam_cx, cam_cy, cam_w, cam_h, pulse)
        self._draw_camera(cam_cx, cam_cy, cam_w, cam_h)
        self._draw_text(cx, cam_cy + cam_h // 2 + 55)
        self._draw_corners(w, h, size=32, margin=18)

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_grid(self, w: int, h: int) -> None:
        spacing = 60
        color = self._blend(self.bg_color, "#1a2a3a", 0.4)
        for x in range(0, w, spacing):
            self._canvas.create_line(x, 0, x, h, fill=color, width=1)
        for y in range(0, h, spacing):
            self._canvas.create_line(0, y, w, y, fill=color, width=1)

    def _draw_glow(
        self, cx: int, cy: int, cam_w: int, cam_h: int, pulse: float
    ) -> None:
        for i in range(4, 0, -1):
            pad = i * 18 + int(pulse * 12)
            alpha = 0.08 * pulse / i
            color = self._blend(self.bg_color, self.accent, alpha)
            self._canvas.create_oval(
                cx - cam_w // 2 - pad,
                cy - cam_h // 2 - pad,
                cx + cam_w // 2 + pad,
                cy + cam_h // 2 + pad,
                outline=color,
                width=1,
                fill="",
            )

    def _draw_camera(self, cx: int, cy: int, cam_w: int, cam_h: int) -> None:
        x = cx - cam_w // 2
        y = cy - cam_h // 2

        # ---- Body ----
        body_top = y + cam_h // 7
        self._canvas.create_rectangle(
            x, body_top, x + cam_w, y + cam_h,
            fill="#0d1b2a", outline=self.accent, width=2,
        )

        # ---- Viewfinder bump ----
        bump_w = cam_w // 4
        bump_x = cx - bump_w // 2
        self._canvas.create_rectangle(
            bump_x, y, bump_x + bump_w, body_top + 2,
            fill="#0d1b2a", outline=self.accent, width=2,
        )

        # ---- Lens ----
        lens_r = int(cam_h * 0.30)
        lens_cx = cx
        lens_cy = y + cam_h // 2 + cam_h // 10

        # Animated outer ring
        t_slow = (self._frame / self.CYCLE_FRAMES) * 2 * math.pi
        pulse = 0.5 + 0.5 * math.sin(t_slow)
        outer_r = lens_r + int(6 * pulse)
        self._canvas.create_oval(
            lens_cx - outer_r, lens_cy - outer_r,
            lens_cx + outer_r, lens_cy + outer_r,
            outline=self._blend(self.bg_color, self.accent, 0.25 + 0.2 * pulse),
            width=2,
            fill="",
        )

        # Main lens body
        self._canvas.create_oval(
            lens_cx - lens_r, lens_cy - lens_r,
            lens_cx + lens_r, lens_cy + lens_r,
            fill="#060e18", outline=self.accent, width=3,
        )

        # Inner rings
        for r_factor, color, width in [
            (0.70, self._blend(self.bg_color, self._secondary, 0.55), 1),
            (0.45, self._blend(self.bg_color, self._secondary, 0.35), 1),
        ]:
            r = int(lens_r * r_factor)
            self._canvas.create_oval(
                lens_cx - r, lens_cy - r,
                lens_cx + r, lens_cy + r,
                outline=color, width=width, fill="",
            )

        # Lens highlight (top-left reflection)
        hl_r = int(lens_r * 0.18)
        hl_x = lens_cx - lens_r // 3
        hl_y = lens_cy - lens_r // 3
        self._canvas.create_oval(
            hl_x - hl_r, hl_y - hl_r,
            hl_x + hl_r, hl_y + hl_r,
            fill="#1a3a5a", outline="",
        )

        # ---- Scanning line (sweeps within lens circle) ----
        scan_period = self.FPS * 3  # 3-second sweep
        scan_pos = self._frame % (scan_period * 2)
        if scan_pos < scan_period:
            scan_y = lens_cy - lens_r + int(lens_r * 2 * scan_pos / scan_period)
        else:
            scan_y = lens_cy + lens_r - int(
                lens_r * 2 * (scan_pos - scan_period) / scan_period
            )
        dy = scan_y - lens_cy
        if abs(dy) <= lens_r:
            half_chord = int(math.sqrt(max(0, lens_r ** 2 - dy ** 2)) * 0.97)
            if half_chord > 2:
                self._canvas.create_line(
                    lens_cx - half_chord, scan_y,
                    lens_cx + half_chord, scan_y,
                    fill="#00ffee", width=1,
                )

        # ---- Record indicator (blinking red dot) ----
        blink_on = (self._frame // (self.FPS // 2)) % 2  # 0.5 s blink
        dot_color = "#ff3333" if blink_on else "#550000"
        dot_r = max(6, cam_h // 16)
        dot_x = x + cam_w - dot_r * 2 - 10
        dot_y = body_top + dot_r + 10
        self._canvas.create_oval(
            dot_x - dot_r, dot_y - dot_r,
            dot_x + dot_r, dot_y + dot_r,
            fill=dot_color, outline="",
        )

        # ---- Signal strength bars (left side, 2/4 lit = weak signal) ----
        bar_x = x + 12
        bar_y = body_top + 10
        bar_specs = [(6, 0.15), (9, 0.15), (12, 0.70), (16, 0.70)]
        for i, (bar_h, alpha) in enumerate(bar_specs):
            color = self._blend(self.bg_color, self.accent, alpha)
            bx = bar_x + i * 10
            self._canvas.create_rectangle(
                bx, bar_y + 16 - bar_h, bx + 6, bar_y + 16,
                fill=color, outline="",
            )

    def _draw_text(self, cx: int, y: int) -> None:
        self._canvas.create_text(
            cx, y,
            text="RTSP Remote Video Display",
            font=("Helvetica", 20, "bold"),
            fill=self.accent,
            anchor="center",
        )
        # Animated waiting dots
        n_dots = 1 + (self._frame // (self.FPS // 2)) % 4
        self._canvas.create_text(
            cx, y + 38,
            text="Awaiting feed" + "." * n_dots,
            font=("Helvetica", 12),
            fill=self._blend(self.bg_color, "#aaaaaa", 0.5),
            anchor="center",
        )

    def _draw_corners(self, w: int, h: int, size: int, margin: int) -> None:
        color = self._blend(self.bg_color, self.accent, 0.25)
        t = 2
        m = margin
        corners = [
            # (line1_start, line1_end, line2_start, line2_end)
            ((m, m), (m + size, m), (m, m), (m, m + size)),  # TL
            ((w - m, m), (w - m - size, m), (w - m, m), (w - m, m + size)),  # TR
            ((m, h - m), (m + size, h - m), (m, h - m), (m, h - m - size)),  # BL
            ((w - m, h - m), (w - m - size, h - m), (w - m, h - m), (w - m, h - m - size)),  # BR
        ]
        for (x1, y1), (x2, y2), (x3, y3), (x4, y4) in corners:
            self._canvas.create_line(x1, y1, x2, y2, fill=color, width=t)
            self._canvas.create_line(x3, y3, x4, y4, fill=color, width=t)

    # ------------------------------------------------------------------
    # Colour utility
    # ------------------------------------------------------------------

    def _blend(self, bg: str, fg: str, alpha: float) -> str:
        """Linearly interpolate between *bg* and *fg* by *alpha* (0–1)."""
        def parse(c: str):
            c = c.lstrip("#")
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

        r0, g0, b0 = parse(bg)
        r1, g1, b1 = parse(fg)
        r = max(0, min(255, int(r0 + (r1 - r0) * alpha)))
        g = max(0, min(255, int(g0 + (g1 - g0) * alpha)))
        b = max(0, min(255, int(b0 + (b1 - b0) * alpha)))
        return f"#{r:02x}{g:02x}{b:02x}"
