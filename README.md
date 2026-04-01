# RTSP Remote Video Display

A fullscreen RTSP camera viewer controlled entirely over MQTT — designed to run headlessly on a dedicated Ubuntu display machine and integrate with Home Assistant automations.

---

## Features

- **Animated idle logo** — a camera-themed canvas animation plays when no feeds are active
- **1×1 and 2×2 layouts** — switch between a single fullscreen feed and a 2×2 quad view via MQTT
- **ffplay rendering** — leverages ffplay (part of ffmpeg) for hardware-accelerated RTSP decoding embedded directly into the application window
- **Stall detection & auto-restart** — monitors feed activity; automatically restarts stalled or crashed streams
- **Named presets** — define camera groupings in config, trigger them with a single MQTT message
- **MQTT status reporting** — publishes state, active feeds, uptime, and restart counts; Home Assistant can read and act on them
- **Heartbeat** — regular MQTT ping so HA knows the display is alive

---

## Architecture Overview

```
Home Assistant  ──MQTT──▶  MQTTClient  ──▶  RTSPDisplayApp  ──▶  LogoAnimation
                                                    │
                                                    └──▶  FeedManager
                                                                │
                                                   ┌───────────┴───────────┐
                                                FeedSlot 0           FeedSlot N
                                               (ffplay -wid)        (ffplay -wid)
```

The tkinter window owns the screen.  When feeds are requested, it creates a grid of `Frame` widgets, passes their X11 window IDs to `FeedManager`, and ffplay embeds into each frame via the `-wid` flag.

---

## MQTT API

### Topics

| Direction | Topic | Purpose |
|-----------|-------|---------|
| Subscribe | `rtsp_display/<device_id>/command` | Receive commands |
| Publish | `rtsp_display/<device_id>/status` | Current state snapshot (retained) |
| Publish | `rtsp_display/<device_id>/heartbeat` | Periodic ping |

### Commands

All commands are JSON objects sent to the command topic.

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
    { "slot": 0, "url": "rtsp://...", "status": "playing", "restart_count": 0, "uptime_s": 320 },
    { "slot": 1, "url": "rtsp://...", "status": "stalled", "restart_count": 2, "uptime_s": 12 }
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

## Mac Developer Setup (first time)

### 1. Install Git

Open **Terminal** and run:

```bash
git --version
```

If Git is not installed, macOS will offer to install the **Xcode Command Line Tools** — click Install and wait for it to complete.  Then run `git --version` again to confirm.

### 2. Configure Git

```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
git config --global init.defaultBranch main
```

### 3. Generate an SSH key for GitHub

```bash
ssh-keygen -t ed25519 -C "your@email.com"
# Press Enter to accept the default path (~/.ssh/id_ed25519)
# Set a passphrase if you want extra security

# Add the key to your SSH agent
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519

# Copy the public key to your clipboard
cat ~/.ssh/id_ed25519.pub | pbcopy
```

### 4. Add the key to GitHub

1. Go to **github.com → Settings → SSH and GPG keys → New SSH key**
2. Give it a title (e.g. "MacBook") and paste the key
3. Click **Add SSH key**

Test the connection:
```bash
ssh -T git@github.com
# Expected: "Hi <username>! You've successfully authenticated…"
```

### 5. Create the GitHub repository

1. Go to **github.com → New repository**
2. Name it `rtsp-remote-video-display`
3. Set it to **Public** or **Private** as you prefer
4. **Do not** add a README, .gitignore, or licence (the project includes its own)
5. Click **Create repository**

### 6. Clone and push the project

```bash
# Clone the empty repo
git clone git@github.com:YOUR_USERNAME/rtsp-remote-video-display.git
cd rtsp-remote-video-display

# Copy the project files into this directory
# (replace ~/Downloads/rtsp-remote-video-display with wherever you saved the files)
cp -r ~/Downloads/rtsp-remote-video-display/. .

# Initial commit
git add .
git commit -m "Initial commit: RTSP Remote Video Display v0.1.0"
git push -u origin main
```

### 7. Mac development testing

Install Python dependencies on your Mac:

```bash
pip3 install -r requirements.txt
```

> **Note:** `python3-tk` is included in the Python.org macOS installer.  If you installed Python via Homebrew run `brew install python-tk`.

Copy the example config and edit it:

```bash
cp config.yaml.example config.yaml
nano config.yaml   # set your MQTT broker IP
```

Run the app:

```bash
python3 -m rtsp_display.main --debug
```

On macOS, ffplay will open in its own floating window (the X11 embedding is Linux-only).  All MQTT logic, stall detection, and layout management work identically.

---

## Ubuntu Display Machine Setup

### Prerequisites
- Ubuntu 22.04 LTS (or 20.04)
- Auto-login configured for your user
- Network access to MQTT broker and cameras

### Deploy from GitHub

```bash
# On the Ubuntu display machine:
git clone git@github.com:YOUR_USERNAME/rtsp-remote-video-display.git
cd rtsp-remote-video-display

# Run the installer (must be run with sudo available)
bash scripts/install.sh
```

The installer will:
1. Install `ffmpeg`, `python3-tk`, and other dependencies
2. Disable Wayland (required for ffplay X11 embedding)
3. Install Python requirements
4. Create `config.yaml` from the example
5. Install and enable a systemd service

### Configure

```bash
nano config.yaml
# Set:  mqtt.host, mqtt.username, mqtt.password
# Add your camera presets under the presets: section
```

### Start the service

```bash
sudo systemctl start rtsp-display

# Check logs
sudo journalctl -u rtsp-display -f
```

The service is set to start automatically after every boot.

### Manual test run

```bash
python3 -m rtsp_display.main --debug
```

---

## Repository structure

```
rtsp-remote-video-display/
├── .github/
│   └── workflows/lint.yml       # GitHub Actions CI
├── rtsp_display/
│   ├── __init__.py
│   ├── main.py                  # Entry point / argument parsing
│   ├── app.py                   # tkinter root, MQTT dispatch, layout management
│   ├── logo.py                  # Animated idle logo (tkinter Canvas)
│   ├── feed_manager.py          # ffplay subprocess management + stall detection
│   ├── mqtt_client.py           # paho-mqtt wrapper, heartbeat, status publish
│   └── config.py                # YAML config loader with defaults
├── scripts/
│   ├── install.sh               # Ubuntu one-shot installer
│   └── rtsp-display.service     # systemd unit template
├── .gitignore
├── config.yaml.example          # Annotated config template (committed)
├── config.yaml                  # Your config (git-ignored, create from example)
└── requirements.txt
```

---

## Development workflow (after initial setup)

```bash
# Make changes on your Mac
git add -p             # interactively stage your changes
git commit -m "feat: add something"
git push

# On the Ubuntu machine — pull and restart
git pull
sudo systemctl restart rtsp-display
```

---

## Roadmap / future work

- Replace MQTT with native Home Assistant WebSocket API for richer integration
- Add more layout options (1×2, 3×3)
- GPU-accelerated decoding via ffplay `-vf` hwdec options
- On-screen overlay (feed name, status indicator per slot)
- Web UI for configuration
