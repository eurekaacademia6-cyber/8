from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

from analysis.engine import AnalysisEngine
from capture import WindowCapture, find_window
from timing import CandleClock
from vision.detector import CandleDetector, DetectorConfig
from vision.tracker import CandleTracker


DEFAULTS = {
    "window_title_contains": "Quotex",
    "capture_fps": 5,
    "min_candles": 10,
    "max_candles": 30,
    "min_body_width_px": 2,
    "chart_roi": {
        "left": 0.08,
        "top": 0.18,
        "right": 0.98,
        "bottom": 0.96,
    },
}


def emit(obj):
    sys.stdout.write(
        json.dumps(
            obj,
            separators=(",", ":"),
        )
        + "\n"
    )
    sys.stdout.flush()


def fatal_log(exc):
    try:
        base = (
            Path.home()
            / "AppData"
            / "Local"
            / "QuotexVisionAI"
            / "logs"
        )
        base.mkdir(
            parents=True,
            exist_ok=True,
        )
        with (
            base / "worker.log"
        ).open(
            "a",
            encoding="utf-8",
        ) as f:
            f.write(
                "\n"
                + "=" * 80
                + "\n"
            )
            f.write(
                time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                + "\n"
            )
            f.write(
                traceback.format_exc()
            )
            f.write("\n")
    except Exception:
        pass


def candle_dict(c):
    return {
        "track_id": int(c.track_id),
        "track_age": int(c.track_age),
        "track_state": str(c.track_state),
        "is_current": bool(c.is_current),
        "confidence": float(c.confidence),
        "bullish": bool(c.bullish),
        "body_left": float(c.body_left),
        "body_right": float(c.body_right),
        "body_top": float(c.body_top),
        "body_bottom": float(c.body_bottom),
        "high": float(c.high),
        "low": float(c.low),
        "open_px": float(c.open_px),
        "close_px": float(c.close_px),
        "body_size_px": float(c.body_size_px),
        "upper_wick_px": float(c.upper_wick_px),
        "lower_wick_px": float(c.lower_wick_px),
        "close_position": float(c.close_position),
        "last_seen_frame": int(c.last_seen_frame),
    }


def signal_dict(s):
    if s is None:
        return None

    return {
        "label": str(s.label),
        "up_probability": float(s.up_probability),
        "down_probability": float(s.down_probability),
        "confidence": float(s.confidence),
        "agreement": float(s.agreement),
        "horizon_seconds": int(
            getattr(s, "horizon_seconds", 30)
        ),
        "reasons": list(
            getattr(s, "reasons", [])
        ),
        "no_trade_reasons": list(
            getattr(s, "no_trade_reasons", [])
        ),
        "components": [
            {
                "name": str(c.name),
                "probability_up": float(
                    c.probability_up
                ),
                "direction": str(
                    c.direction
                ),
                "weight": float(
                    c.weight
                ),
                "available": bool(
                    c.available
                ),
                "reason": str(
                    c.reason
                ),
            }
            for c in s.components
        ],
        "diagnostics": (
            getattr(s, "diagnostics", {})
            or {}
        ),
    }


def run_worker():
    roi = (
        DEFAULTS["chart_roi"]["left"],
        DEFAULTS["chart_roi"]["top"],
        DEFAULTS["chart_roi"]["right"],
        DEFAULTS["chart_roi"]["bottom"],
    )

    capture = None
    detector = CandleDetector(
        DetectorConfig(
            min_candles=DEFAULTS[
                "min_candles"
            ],
            max_candles=DEFAULTS[
                "max_candles"
            ],
            min_body_width_px=DEFAULTS[
                "min_body_width_px"
            ],
        )
    )
    tracker = CandleTracker(
        max_match_distance=40.0,
        max_missed=3,
        history_limit=120,
    )
    engine = AnalysisEngine()
    clock = CandleClock(30, 0)

    last_current_track = -1
    frame_id = 0
    last_emit = 0.0
    fps = max(
        2,
        int(DEFAULTS["capture_fps"]),
    )

    emit(
        {
            "type": "worker_ready",
            "pid": int(
                __import__("os").getpid()
            ),
            "fps": fps,
        }
    )

    while True:
        loop_started = time.monotonic()
        frame_id += 1

        try:
            hwnd = find_window(
                DEFAULTS[
                    "window_title_contains"
                ]
            )

            if not hwnd:
                emit(
                    {
                        "type": "status",
                        "status": "QUOTEX WINDOW NOT FOUND",
                        "frame_id": frame_id,
                    }
                )
                time.sleep(0.5)
                continue

            if capture is None:
                capture = WindowCapture()

            frame, rect = (
                capture.capture_window(hwnd)
            )

            detection = detector.detect(
                frame,
                roi,
            )

            tracking = tracker.update(
                detection.candles
            )

            detection.candles = (
                tracking.candles
            )
            detection.current_index = (
                len(tracking.candles) - 1
                if tracking.candles
                else -1
            )

            signal = None

            if detection.usable:
                signal = engine.analyze(
                    detection.candles,
                    detection.quality,
                    timeframe_minutes=(
                        clock.timeframe_seconds
                        / 60.0
                    ),
                    volume_available=False,
                    higher_tf_available=False,
                )

            current_track = (
                tracking.current_track_id
            )

            candle_event = None

            if (
                current_track >= 0
                and current_track
                != last_current_track
                and last_current_track >= 0
            ):
                previous = next(
                    (
                        c
                        for c in detection.candles
                        if c.track_id
                        == last_current_track
                    ),
                    None,
                )

                candle_event = {
                    "closed_track_id": last_current_track,
                }

                if previous is not None:
                    candle_event[
                        "closed_candle"
                    ] = candle_dict(previous)

            last_current_track = current_track

            now = time.monotonic()

            emit(
                {
                    "type": "frame",
                    "frame_id": frame_id,
                    "window_rect": list(rect),
                    "detection_quality": float(
                        detection.quality
                    ),
                    "detected_count": len(
                        detection.candles
                    ),
                    "tracking_stability": float(
                        tracking.tracking_stability
                    ),
                    "stable_tracks": int(
                        tracking.stable_tracks
                    ),
                    "new_tracks": int(
                        tracking.new_tracks
                    ),
                    "recovered_tracks": int(
                        tracking.recovered_tracks
                    ),
                    "current_track_id": int(
                        tracking.current_track_id
                    ),
                    "candles": [
                        candle_dict(c)
                        for c in detection.candles
                    ],
                    "signal": signal_dict(
                        signal
                    ),
                    "clock": {
                        "start": clock.formatted()[0],
                        "end": clock.formatted()[1],
                        "remaining": clock.formatted()[2],
                    },
                    "candle_event": candle_event,
                }
            )

            elapsed = (
                time.monotonic()
                - loop_started
            )
            delay = max(
                0.02,
                (1.0 / fps) - elapsed,
            )
            time.sleep(delay)

        except Exception as exc:
            fatal_log(exc)

            emit(
                {
                    "type": "frame_error",
                    "frame_id": frame_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

            # Recreate capture object after a capture/OpenCV exception.
            capture = None

            time.sleep(0.35)


if __name__ == "__main__":
    run_worker()
