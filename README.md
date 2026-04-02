# RTSP Remote Video Display

A fullscreen RTSP camera viewer controlled entirely over MQTT — designed to run headlessly on a dedicated display machine and integrate with Home Assistant automations.

---

## Features

- **Animated idle logo** — a camera-themed canvas animation plays when no feeds are active
- **1×1 and 2×2 layouts** — switch between a single fullscreen feed and a 2×2 quad view via MQTT
- **OpenCV/PIL rendering** — RTSP frames are decoded by OpenCV and rendered directly into the tkinter window; no external subprocess windows
- **Stall detection & auto-restart** — monitors feed activity; automatically reconnects stalled or dropped streams
- **Named presets** — define camera groupings in config, trigger them with a single MQTT message
- **MQTT status reporting** — publishes state, active feeds, uptime, and restart counts; Home Assistant can read and act on them
- **Heartbeat** — regular MQTT ping so HA knows the display is alive
- **Credential safety** — credentials stored in a gitignored `.env` file; never appear in logs or MQTT payloads

---

## Architecture Overview

```
Home Assistant  ──MQTT──▶  MQTTClient  ──▶  RTSPDisplayApp  ──▶  LogoAnimation
                                                    │
                                                    └──▶  FeedManager
                                                                │
                                                   ┌───────────┴───────────┐
                                                FeedSlot 0           FeedSlot N
                                              (OpenCV + PIL)       (OpenCV + PIL)
```

Each `FeedSlot` owns a `tk.Canvas` widget. A background thread reads RTSP frames via `cv2.VideoCapture`; a `root.after()` loop on the main thread converts them to `ImageTk.PhotoImage` and paints them onto the canvas. Everything renders inside the single fullscreen tkinter window.

---

## MQTT API

### Topics

| Direction | Topic | Purpose |
|-----------|-------|---------|
| Subscribe | `rtsp_display/<device_id>/command` | Receive commands |
| Publish | `rtsp_display/<device_id>/status` | Current state snapshot (retained) |
| Publish | `rtsp_display/<device_id>/heartbeat` | Periodic ping |

### Commands

**Show one or more feeds**
```json
{
  "action": "show_feed",
  "layout": "1x1",
  "feeds": [
    { "slot": 0, "url": "rtsp://admin:pass@192.168.1.100/stream1" }
  ]
}
```

**2×2 quad view**
```json
{
  "action": "show_feed",
  "layout": "2x2",
  "feeds": [
    { "slot": 0, "url": "rtsp://camera1/stream" },
    { "slot": 1, "url": "rtsp://camera2/stream" },
    { "slot": 2, "url": "rtsp://camera3/stream" },
    { "slot": 3, "url": "rtsp://camera4/stream" }
  ]
}
```

**Load a named preset**
```json
{ "action": "show_preset", "name": "front_cameras" }
```

**Change layout (keeps existing URLs)**
```json
{ "action": "set_layout", "layout": "2x2" }
```

**Clear feeds (return to logo)**
```json
{ "action": "clear" }
```

**Ping (triggers immediate status publish)**
```json
{ "action": "ping" }
```

### Status payload example
```json
{
  "device_id": "rtsp_display_1",
  "state": "playing",
  "layout": "2x2",
  "feeds": [
    { "slot": 0, "url": "rtsp://***:***@...", "status": "playing", "restart_count": 0, "uptime_s": 320 },
    { "slot": 1, "url": "rtsp://***:***@...", "status": "stalled", "restart_count": 2, "uptime_s": 12 }
  ],
  "timestamp": 1711900800
}
```

### Home Assistant example

```yaml
# configuration.yaml
mqtt:
  button:
    - unique_id: rtsp_clear
      name: "Display — Clear"
      command_topic: rtsp_display/rtsp_display_1/command
      payload_press: '{"action":"clear"}'

    - unique_id: rtsp_front_cameras
      name: "Display — Front Cameras"
      command_topic: rtsp_display/rtsp_display_1/command
      payload_press: '{"action":"show_preset","name":"front_cameras"}'

  sensor:
    - unique_id: rtsp_display_state
      name: "Display State"
      state_topic: rtsp_display/rtsp_display_1/status
      value_template: "{{ value_json.state }}"
```

---

## Ubuntu Setup

### Prerequisites
- Ubuntu 22.04 LTS (or 20.04)
- Auto-login configured for your user (Settings → Users → Automatic Login)
- Network access to MQTT broker and cameras

### Install

```bash
git clone <your-repo-url> rtsp-remote-video-display
cd rtsp-remote-video-display
bash scripts/install.sh
```

The installer will:
1. Install system packages (`ffmpeg`, `python3-tk`, `python3-pil.imagetk`, `libgl1`, etc.)
2. Disable Wayland in GDM3 (forces X11 for reliable tkinter fullscreen)
3. Install Python requirements
4. Create `config.yaml` from the example
5. Install and enable a systemd service
6. Create a desktop shortcut at `~/Desktop/rtsp-display.desktop`

### Configure

```bash
cp .env.example .env
nano .env          # set MQTT_USER, MQTT_PASS, camera credentials
nano config.yaml   # set mqtt.host, add presets
```

### Run as a service

```bash
sudo systemctl start rtsp-display

# View logs
sudo journalctl -u rtsp-display -f

# Stop / restart
sudo systemctl stop rtsp-display
sudo systemctl restart rtsp-display
```

The service starts automatically on every boot.

### Manual test run

```bash
cd /path/to/rtsp-remote-video-display
python3 -m rtsp_display.main --debug
```

---

## Raspberry Pi Setup

### Prerequisites
- Raspberry Pi 4 or 5 recommended (Pi 3 may struggle with 2×2 at high resolutions)
- Raspberry Pi OS Bookworm **Desktop** (not Lite)
- Auto-login and X11 mode enabled (see below)
- Network access to MQTT broker and cameras

### 1. Enable auto-login and X11

Open a terminal and run:

```bash
sudo raspi-config
```

Navigate to:
- **System Options → Boot / Auto Login → Desktop Autologin**
- **Advanced Options → Wayland → X11**

Then reboot:

```bash
sudo reboot
```

### 2. Install

```bash
git clone <your-repo-url> rtsp-remote-video-display
cd rtsp-remote-video-display
bash scripts/install.sh
```

The installer runs identically to Ubuntu. If GDM3 is not present (Pi uses LightDM), the Wayland step is skipped — that's fine since you already switched to X11 via `raspi-config`.

### 3. Configure

```bash
cp .env.example .env
nano .env          # set MQTT_USER, MQTT_PASS, camera credentials
nano config.yaml   # set mqtt.host, add presets
```

### 4. Run as a service

```bash
sudo systemctl start rtsp-display

# View logs
sudo journalctl -u rtsp-display -f

# Stop / restart
sudo systemctl stop rtsp-display
sudo systemctl restart rtsp-display
```

The service starts automatically on every boot.

### 5. Manual test run

```bash
cd /path/to/rtsp-remote-video-display
python3 -m rtsp_display.main --debug
```

### Performance notes

| Hardware | 1×1 | 2×2 |
|----------|-----|-----|
| Pi 5 | Excellent | Excellent |
| Pi 4 (4GB) | Excellent | Good |
| Pi 4 (2GB) | Good | May drop frames at 1080p |
| Pi 3 | Adequate at 720p | Not recommended |

If feeds drop frames, lower the source stream resolution or set `rtsp_transport: udp` in `config.yaml` for lower latency.

---

## Configuration

`config.yaml` (gitignored) is created from `config.yaml.example`. Key sections:

```yaml
device_id: rtsp_display_1

mqtt:
  host: 192.168.1.x
  username: ${MQTT_USER}    # from .env
  password: ${MQTT_PASS}    # from .env

feeds:
  rtsp_transport: tcp       # tcp or udp
  reconnect_delay: 5
  stall_timeout: 30

presets:
  front_cameras:
    layout: "2x2"
    feeds:
      - "rtsp://${CAM1_USER}:${CAM1_PASS}@192.168.1.101/stream1"
      - "rtsp://${CAM1_USER}:${CAM1_PASS}@192.168.1.102/stream1"
```

### Credentials

Create `.env` next to `config.yaml` (gitignored):

```
MQTT_USER=mqtt_user
MQTT_PASS=s3cr3t!
CAM1_USER=admin
CAM1_PASS=p@$$w0rd
```

See `.env.example` for a full template.

---

## Updating

```bash
git pull
sudo systemctl restart rtsp-display
```

---

## Repository structure

```
rtsp-remote-video-display/
├── .github/
│   └── workflows/lint.yml       # CI: flake8 linting
├── rtsp_display/
│   ├── main.py                  # Entry point / argument parsing
│   ├── app.py                   # tkinter root, MQTT dispatch, layout management
│   ├── logo.py                  # Animated idle logo (tkinter Canvas)
│   ├── feed_manager.py          # OpenCV RTSP capture + PIL Canvas rendering
│   ├── mqtt_client.py           # paho-mqtt wrapper, heartbeat, status publish
│   ├── config.py                # YAML config loader with .env interpolation
│   └── utils.py                 # Credential redaction helpers
├── scripts/
│   ├── install.sh               # One-shot installer (Ubuntu + Raspberry Pi)
│   └── rtsp-display.service     # systemd unit template
├── .env.example                 # Credential template (copy to .env)
├── config.yaml.example          # Annotated config template (copy to config.yaml)
└── requirements.txt
```

---

## Roadmap

- Add more layout options (1×2, 3×3)
- On-screen overlay (feed name, status indicator per slot)
- Web UI for configuration
