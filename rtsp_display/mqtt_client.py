"""MQTT client — receives commands and publishes status/heartbeat.

Topic structure
---------------
Subscribe:
    rtsp_display/<device_id>/command        JSON command messages

Publish:
    rtsp_display/<device_id>/status         JSON state snapshot (retained)
    rtsp_display/<device_id>/heartbeat      Timestamp ping

Command payload format
----------------------
    { "action": "show_feed",  "layout": "1x1",  "feeds": [{"slot": 0, "url": "rtsp://..."}] }
    { "action": "show_feed",  "layout": "2x2",  "feeds": [{"slot": 0, "url": "..."}, ...] }
    { "action": "show_preset","name": "front_cameras" }
    { "action": "set_layout", "layout": "2x2" }
    { "action": "clear" }
    { "action": "ping" }

Home Assistant integration example (configuration.yaml)
--------------------------------------------------------
    mqtt:
      button:
        - unique_id: rtsp_clear
          name: "RTSP Display Clear"
          command_topic: rtsp_display/rtsp_display_1/command
          payload_press: '{"action":"clear"}'
"""

import json
import logging
import threading
import time
from typing import Callable, Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTClient:
    """Thin wrapper around paho-mqtt with auto-reconnect and heartbeat."""

    def __init__(self, config, command_handler: Callable[[dict], None]) -> None:
        self._config = config
        self._command_handler = command_handler

        self.device_id: str = config.get("device_id", default="rtsp_display")
        base: str = config.get("mqtt", "base_topic", default="rtsp_display")

        self.cmd_topic = f"{base}/{self.device_id}/command"
        self.status_topic = f"{base}/{self.device_id}/status"
        self.heartbeat_topic = f"{base}/{self.device_id}/heartbeat"

        self._connected: bool = False
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()

        # Build paho client
        self._client = mqtt.Client(
            client_id=self.device_id,
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        username = config.get("mqtt", "username")
        password = config.get("mqtt", "password")
        if username:
            self._client.username_pw_set(username, password)

        # Last-will so HA knows the device went offline unexpectedly
        self._client.will_set(
            self.status_topic,
            payload=json.dumps({"device_id": self.device_id, "state": "offline"}),
            qos=1,
            retain=True,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        host: str = self._config.get("mqtt", "host", default="localhost")
        port: int = int(self._config.get("mqtt", "port", default=1883))
        logger.info("Connecting to MQTT broker at %s:%d …", host, port)
        self._client.connect_async(host, port, keepalive=60)
        self._client.loop_start()

    def disconnect(self) -> None:
        self._heartbeat_stop.set()
        self._client.loop_stop()
        self._client.disconnect()

    # ------------------------------------------------------------------
    # Publish helpers
    # ------------------------------------------------------------------

    def publish_status(
        self,
        state: str = "idle",
        layout: Optional[str] = None,
        feeds: Optional[list] = None,
    ) -> None:
        if not self._connected:
            return
        payload = {
            "device_id": self.device_id,
            "state": state,
            "layout": layout,
            "feeds": feeds or [],
            "timestamp": int(time.time()),
        }
        self._client.publish(
            self.status_topic,
            json.dumps(payload),
            qos=0,
            retain=True,
        )
        logger.debug("Published status: %s", state)

    # ------------------------------------------------------------------
    # paho callbacks
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            logger.info("MQTT connected")
            self._connected = True
            client.subscribe(self.cmd_topic, qos=1)
            logger.info("Subscribed to %s", self.cmd_topic)
            self._start_heartbeat()
            self.publish_status("idle")
        else:
            codes = {
                1: "incorrect protocol version",
                2: "invalid client identifier",
                3: "server unavailable",
                4: "bad credentials",
                5: "not authorised",
            }
            logger.error(
                "MQTT connection refused (rc=%d: %s)", rc, codes.get(rc, "unknown")
            )

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False
        self._heartbeat_stop.set()
        if rc != 0:
            logger.warning("MQTT disconnected unexpectedly (rc=%d); paho will retry", rc)

    def _on_message(self, client, userdata, msg) -> None:
        raw = msg.payload.decode("utf-8", errors="replace")
        logger.debug("MQTT message on %s: %s", msg.topic, raw)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Received non-JSON MQTT payload: %r", raw)
            return
        try:
            self._command_handler(payload)
        except Exception as exc:
            logger.error("Error in command handler: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _start_heartbeat(self) -> None:
        self._heartbeat_stop.clear()
        interval: int = int(self._config.get("mqtt", "heartbeat_interval", default=30))
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        def _loop() -> None:
            while not self._heartbeat_stop.wait(timeout=interval):
                if self._connected:
                    self._client.publish(
                        self.heartbeat_topic,
                        json.dumps({
                            "device_id": self.device_id,
                            "timestamp": int(time.time()),
                        }),
                        qos=0,
                    )

        self._heartbeat_thread = threading.Thread(target=_loop, daemon=True)
        self._heartbeat_thread.start()
