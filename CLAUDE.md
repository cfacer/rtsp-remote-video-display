# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A fullscreen RTSP camera viewer (kiosk) controlled entirely over MQTT, designed to run headlessly on a dedicated Ubuntu display machine. Displays live RTSP feeds in 1×1 or 2×2 grid layouts and returns to an animated idle logo when no feeds are active.

## Commands

### Development (macOS)
```bash
pip3 install -r requirements.txt
cp config.yaml.example config.yaml
python3 -m rtsp_display.main --debug
```

### Linting (CI)
```bash
flake8 rtsp_display/ --count --select=E9,F63,F7,F82 --show-source --statistics
flake8 rtsp_display/ --count --max-line-length=100 --statistics
```

### Ubuntu Deployment
```bash
bash scripts/install.sh          # one-shot install (packages, systemd service, desktop shortcut)
sudo systemctl start rtsp-display
sudo journalctl -u rtsp-display -f
```

The installer also creates `~/Desktop/rtsp-display.desktop` for manual launching.

## Architecture

The application is **event-driven** with MQTT as the control plane and tkinter as the display layer.

```
MQTT command → MQTTClient → root.after() → RTSPDisplayApp → FeedManager → ffplay subprocess
```

**Thread model**: MQTT runs on its own thread; all UI mutations must go through `root.after()` to reach the tkinter main thread. This is the key architectural constraint to preserve when modifying `app.py` or `mqtt_client.py`.

### Component Responsibilities

| File | Responsibility |
|------|---------------|
| `app.py` | Owns tkinter root; dispatches MQTT commands; builds Frame grid; publishes status |
| `feed_manager.py` | Spawns and supervises ffplay subprocesses (one `FeedSlot` per grid position) |
| `mqtt_client.py` | paho-mqtt wrapper; auto-reconnect; heartbeat; last-will |
| `logo.py` | Animated idle canvas shown when no feeds active |
| `config.py` | YAML loader with deep-merge defaults and `.env` interpolation |
| `utils.py` | Shared `redact_url()` and `redact_credentials()` helpers |

### FeedSlot Supervision

Each `FeedSlot` runs **two background threads**:
- **`_monitor_stderr`** – reads ffplay stderr to update `last_activity` timestamp
- **`_watchdog`** – polls every 5s; detects hard crashes (exit code) and soft stalls (stderr silence >30s); triggers auto-restart

### Linux vs macOS

On Linux, ffplay is embedded into tkinter `Frame` widgets via `ffplay -wid <X11_window_id> -x <W> -y <H>` (frame dimensions are passed so the video scales to fill). If the running ffplay build doesn't support `-wid`, `FeedSlot` detects the error in stderr, sets `_embedding_failed`, and the watchdog restarts without embedding. On macOS (dev mode), ffplay opens a floating window instead — the rest of the app logic is identical.

## MQTT API

**Subscribe:** `rtsp_display/<device_id>/command`
**Publish:** `rtsp_display/<device_id>/status` (retained), `rtsp_display/<device_id>/heartbeat`

Key commands: `show_feed`, `show_preset`, `set_layout`, `clear`, `ping`

Status payload includes per-slot state: `playing | stalled | restarting | error | stopped`

## Configuration

`config.yaml` (gitignored) is created from `config.yaml.example`. Key sections: `mqtt`, `display`, `feeds`, `presets`. Config uses deep-merge: nested dicts overlay on defaults; primitives override.

### Credentials / special characters

Create a `.env` file next to `config.yaml` (also gitignored) with `KEY=value` pairs. Reference them anywhere in `config.yaml` as `${VAR_NAME}`:

```
# .env
CAM1_USER=admin
CAM1_PASS=p@$$w0rd!
```
```yaml
# config.yaml preset
feeds:
  - "rtsp://${CAM1_USER}:${CAM1_PASS}@192.168.1.101/stream1"
```

`config.py` interpolates all `${VAR}` placeholders after loading. MQTT status payloads and all log output always redact credentials as `***:***` via `utils.redact_url()` / `utils.redact_credentials()` — the real values never leave the process.

## Dependencies

- **Runtime**: `paho-mqtt`, `PyYAML`, `python3-tk` (system), `ffmpeg` (system)
- **Linting**: `flake8` (max line length 100)
- **No test suite** — CI runs only flake8 linting via `.github/workflows/lint.yml`
