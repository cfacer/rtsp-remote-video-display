#!/usr/bin/env python3
"""RTSP Remote Video Display — entry point.

Usage::

    python3 -m rtsp_display.main
    python3 -m rtsp_display.main --config /path/to/config.yaml
    python3 -m rtsp_display.main --debug
"""

import argparse
import logging
import sys

from rtsp_display.config import Config
from rtsp_display.app import RTSPDisplayApp


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RTSP Remote Video Display — MQTT-controlled fullscreen RTSP viewer"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="PATH",
        help="Path to YAML config file (default: config.yaml)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s  [%(name)-28s]  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    config = Config(args.config)
    app = RTSPDisplayApp(config, config_path=args.config)
    app.run()


if __name__ == "__main__":
    main()
