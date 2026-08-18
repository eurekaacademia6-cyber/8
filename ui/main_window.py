from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import (
    QProcess,
    QTimer,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from timing import CandleClock
from ui.overlay import Overlay


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "Quotex Vision AI - Continuous Live"
        )
        self.resize(
            1180,
            820,
        )

        self.running = False
        self.worker = None
        self.buffer = b""
        self.worker_restarts = 0
        self.last_frame_id = 0
        self.last_worker_message = 0.0
        self.last_current_track_id = -1
        self.last_rect = None
        self.last_candles = []

        self.clock = CandleClock(
            30,
            0,
        )

        self.overlay = Overlay()

        self._build_ui()

        self.watchdog = QTimer(
            self
        )
        self.watchdog.timeout.connect(
            self._watchdog_tick
        )
        self.watchdog.start(1000)

        self.clock_timer = QTimer(
            self
        )
        self.clock_timer.timeout.connect(
            self._update_clock
        )
        self.clock_timer.start(250)

    # =========================================================
    # CONFIG / UI
    # =========================================================
    def _load_config(self):
        return {
            "capture_fps": 5,
            "window_title_contains": "Quotex",
        }

    def _cfg(self):
        return self._load_config()

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(
            central
        )

        title = QLabel(
            "QUOTEX VISION AI — CONTINUOUS LIVE TRACKER"
        )
        title.setStyleSheet(
            "font-size:21px; font-weight:800;"
        )
        root.addWidget(title)

        self.live_status = QLabel(
            "READY — PRESS START"
        )
        self.live_status.setStyleSheet(
            "font-size:15px; font-weight:700;"
        )
        root.addWidget(
            self.live_status
        )

        controls = QHBoxLayout()

        self.start_btn = QPushButton(
            "START LIVE"
        )
        self.start_btn.clicked.connect(
            self.start
        )

        self.stop_btn = QPushButton(
            "STOP"
        )
        self.stop_btn.clicked.connect(
            self.stop
        )

        controls.addWidget(
            self.start_btn
        )
        controls.addWidget(
            self.stop_btn
        )

        self.vision_box = QCheckBox(
            "VISIBLE CANDLE BOXES"
        )
        self.vision_box.setChecked(
            True
        )
        self.vision_box.stateChanged.connect(
            self._toggle_boxes
        )
        controls.addWidget(
            self.vision_box
        )

        self.analysis_box = QCheckBox(
            "LIVE ANALYSIS"
        )
        self.analysis_box.setChecked(
            True
        )
        controls.addWidget(
            self.analysis_box
        )

        controls.addWidget(
            QLabel("Horizon:")
        )

        self.timeframe = QComboBox()
        self.timeframe.addItems([
            "30 seconds",
            "60 seconds",
            "120 seconds",
        ])
        self.timeframe.currentIndexChanged.connect(
            self._timeframe_changed
        )
        controls.addWidget(
            self.timeframe
        )

        controls.addWidget(
            QLabel("Clock:")
        )

        self.offset = QSpinBox()
        self.offset.setRange(
            -120,
            120,
        )
        self.offset.setSuffix(
            " s"
        )
        self.offset.valueChanged.connect(
            self._offset_changed
        )
        controls.addWidget(
            self.offset
        )

        root.addLayout(
            controls
        )

        top = QGridLayout()

        current = QGroupBox(
            "CURRENT CANDLE — LIVE TRACK"
        )
        current_layout = QVBoxLayout(
            current
        )

        self.current_label = QLabel(
            "Current: —"
        )
        self.current_track = QLabel(
            "Track: —"
        )
        self.current_state = QLabel(
            "State: —"
        )
        self.current_conf = QLabel(
            "Vision: —"
        )
        self.current_time = QLabel(
            "Time: —"
        )
        self.current_remaining = QLabel(
            "Remaining: —"
        )

        for label in (
            self.current_label,
            self.current_track,
            self.current_state,
            self.current_conf,
            self.current_time,
            self.current_remaining,
        ):
            current_layout.addWidget(
                label
            )

        prediction = QGroupBox(
            "NEXT CANDLE / NEXT WINDOW"
        )
        prediction_layout = QVBoxLayout(
            prediction
        )

        self.prediction_label = QLabel(
            "WAITING"
        )
        self.prediction_label.setStyleSheet(
            "font-size:28px; font-weight:900;"
        )

        self.prediction_probability = QLabel(
            "UP — | DOWN —"
        )
        self.prediction_confidence = QLabel(
            "Confidence —"
        )
        self.prediction_target = QLabel(
            "Window —"
        )
        self.prediction_reference = QLabel(
            "Reference: current visible price"
        )

        for label in (
            self.prediction_label,
            self.prediction_probability,
            self.prediction_confidence,
            self.prediction_target,
            self.prediction_reference,
        ):
            prediction_layout.addWidget(
                label
            )

        top.addWidget(
            current,
            0,
            0,
        )
        top.addWidget(
            prediction,
            0,
            1,
        )

        root.addLayout(
            top
        )

        tracking = QGroupBox(
            "PERSISTENT CANDLE TRACKING"
        )
        tracking_layout = QVBoxLayout(
            tracking
        )

        self.tracking_summary = QLabel(
            "Tracking: —"
        )
        tracking_layout.addWidget(
            self.tracking_summary
        )

        self.table = QTableWidget(
            0,
            10,
        )
        self.table.setHorizontalHeaderLabels([
            "TRACK",
            "STATE",
            "DIR",
            "VISION",
            "AGE",
            "BODY",
            "UP WICK",
            "LOW WICK",
            "CURRENT",
            "FRAME",
        ])
        self.table.setMaximumHeight(
            270
        )
        tracking_layout.addWidget(
            self.table
        )

        root.addWidget(
            tracking
        )

        audit = QGroupBox(
            "DECISION AUDIT"
        )
        audit_layout = QGridLayout(
            audit
        )

        self.layer_labels = {}

        for row, name in enumerate([
            "L1 Candle Vision",
            "L2 Momentum",
            "L3 Trend",
            "L4 Volatility",
            "L5 Levels",
            "L6 Confirmation",
        ]):
            a = QLabel(name)
            b = QLabel("WAITING")

            audit_layout.addWidget(
                a,
                row,
                0,
            )
            audit_layout.addWidget(
                b,
                row,
                1,
            )

            self.layer_labels[name] = b

        root.addWidget(
            audit
        )

        bottom = QHBoxLayout()

        self.events = QTextEdit()
        self.events.setReadOnly(
            True
        )

        self.diagnostics = QTextEdit()
        self.diagnostics.setReadOnly(
            True
        )

        bottom.addWidget(
            self.events
        )
        bottom.addWidget(
            self.diagnostics
        )

        root.addLayout(
            bottom
        )

        self.setCentralWidget(
            central
        )

    # =========================================================
    # START / STOP
    # =========================================================
    def start(self):
        if self.running:
            return

        self.running = True
        self.worker_restarts = 0
        self.buffer = b""

        self._start_worker()

        self.live_status.setText(
            "STARTING LIVE VISION..."
        )

    def stop(self):
        self.running = False

        if self.worker is not None:
            try:
                self.worker.kill()
            except Exception:
                pass
            self.worker = None

        self.overlay.hide()

        self.live_status.setText(
            "STOPPED"
        )

    def _start_worker(self):
        if not self.running:
            return

        if self.worker is not None:
            try:
                self.worker.kill()
            except Exception:
                pass

        self.worker = QProcess(
            self
        )

        self.worker.setProcessChannelMode(
            QProcess.SeparateChannels
        )

        self.worker.readyReadStandardOutput.connect(
            self._read_worker_output
        )

        self.worker.errorOccurred.connect(
            self._worker_error
        )

        self.worker.finished.connect(
            self._worker_finished
        )

        program = __import__(
            "sys"
        ).executable

        if getattr(
            __import__("sys"),
            "frozen",
            False,
        ):
            arguments = [
                "--worker",
            ]
        else:
            arguments = [
                str(
                    Path(
                        __file__
                    ).resolve().parent.parent
                    / "main.py"
                ),
                "--worker",
            ]

        self.worker.start(
            program,
            arguments,
        )

    # =========================================================
    # WORKER COMMUNICATION
    # =========================================================
    def _read_worker_output(self):
        if self.worker is None:
            return

        self.buffer += bytes(
            self.worker.readAllStandardOutput()
        )

        while b"\n" in self.buffer:
            line, self.buffer = (
                self.buffer.split(
                    b"\n",
                    1,
                )
            )

            line = line.strip()

            if not line:
                continue

            try:
                message = json.loads(
                    line.decode(
                        "utf-8",
                        errors="replace",
                    )
                )
            except Exception as exc:
                self.events.append(
                    "Worker JSON error: "
                    + str(exc)
                )
                continue

            self._handle_worker_message(
                message
            )

    def _worker_error(
        self,
        error,
    ):
        self.live_status.setText(
            f"WORKER ERROR: {error}"
        )

    def _worker_finished(
        self,
        exit_code,
        exit_status,
    ):
        if not self.running:
            return

        self.worker_restarts += 1

        self.live_status.setText(
            "VISION WORKER RESTARTING "
            f"(#{self.worker_restarts})"
        )

        QTimer.singleShot(
            1000,
            self._start_worker,
        )

    # =========================================================
    # MESSAGE HANDLING
    # =========================================================
    def _handle_worker_message(
        self,
        message,
    ):
        self.last_worker_message = (
            time.monotonic()
        )

        kind = message.get(
            "type"
        )

        if kind == "worker_ready":
            self.live_status.setText(
                "LIVE WORKER CONNECTED"
            )
            return

        if kind == "status":
            self.live_status.setText(
                message.get(
                    "status",
                    "LIVE",
                )
            )
            return

        if kind == "frame_error":
            self.live_status.setText(
                "VISION ERROR — WORKER CONTINUES"
            )
            self.events.append(
                "FRAME ERROR: "
                + message.get(
                    "error",
                    "unknown",
                )
            )
            return

        if kind != "frame":
            return

        self.last_frame_id = int(
            message.get(
                "frame_id",
                0,
            )
        )

        self.last_rect = tuple(
            message.get(
                "window_rect",
                [0, 0, 1, 1],
            )
        )

        self.last_candles = (
            message.get(
                "candles",
                [],
            )
        )

        self._update_current(
            message
        )
        self._update_tracking(
            message
        )

        signal = message.get(
            "signal"
        )

        if (
            signal is not None
            and self.analysis_box.isChecked()
        ):
            self._update_prediction(
                message,
                signal,
            )
            self._update_audit(
                signal
            )
        else:
            self.prediction_label.setText(
                "VISION SCAN"
            )

        self._update_overlay(
            message,
            signal,
        )

        event = message.get(
            "candle_event"
        )

        if event:
            self._record_candle_event(
                event,
                message,
            )

        self.live_status.setText(
            "LIVE • FRAME "
            f"{self.last_frame_id}"
        )

    # =========================================================
    # CURRENT CANDLE
    # =========================================================
    def _update_current(
        self,
        message,
    ):
        candles = message.get(
            "candles",
            [],
        )

        current_id = message.get(
            "current_track_id",
            -1,
        )

        current = next(
            (
                candle
                for candle in candles
                if candle.get(
                    "track_id"
                )
                == current_id
            ),
            None,
        )

        if current is None:
            self.current_label.setText(
                "Current: —"
            )
            return

        self.current_label.setText(
            "Current: "
            + (
                "BULLISH"
                if current.get(
                    "bullish"
                )
                else "BEARISH"
            )
        )

        self.current_track.setText(
            "Track: "
            f"T{int(current_id):03d}"
        )

        self.current_state.setText(
            "State: "
            f"{current.get('track_state','CURRENT')}"
            + " • age "
            f"{current.get('track_age',0)}"
        )

        self.current_conf.setText(
            "Vision: "
            f"{float(current.get('confidence',0))*100:.1f}%"
        )

        clock = message.get(
            "clock",
            {},
        )

        self.current_time.setText(
            "Time: "
            f"{clock.get('start','—')}"
            " → "
            f"{clock.get('end','—')}"
        )

        self.current_remaining.setText(
            "Remaining: "
            f"{clock.get('remaining','—')}s"
        )

        self.last_current_track_id = (
            current_id
        )

    # =========================================================
    # TRACKING
    # =========================================================
    def _update_tracking(
        self,
        message,
    ):
        candles = message.get(
            "candles",
            [],
        )

        self.tracking_summary.setText(
            "Tracking: "
            f"{message.get('detected_count',0)} "
            "candles | "
            f"Stable {message.get('stable_tracks',0)} | "
            f"New {message.get('new_tracks',0)} | "
            f"Recovered {message.get('recovered_tracks',0)} | "
            f"Stability "
            f"{message.get('tracking_stability',0)*100:.1f}% | "
            f"Current T"
            f"{message.get('current_track_id',-1):03d}"
        )

        self.table.setRowCount(
            len(candles)
        )

        for row, candle in enumerate(
            candles
        ):
            values = [
                f"T{int(candle.get('track_id',-1)):03d}",
                candle.get(
                    "track_state",
                    "UNKNOWN",
                ),
                (
                    "BULL"
                    if candle.get(
                        "bullish"
                    )
                    else "BEAR"
                ),
                f"{float(candle.get('confidence',0))*100:.1f}%",
                str(
                    candle.get(
                        "track_age",
                        0,
                    )
                ),
                f"{float(candle.get('body_size_px',0)):.1f}",
                f"{float(candle.get('upper_wick_px',0)):.1f}",
                f"{float(candle.get('lower_wick_px',0)):.1f}",
                (
                    "YES"
                    if candle.get(
                        "is_current"
                    )
                    else ""
                ),
                str(
                    candle.get(
                        "last_seen_frame",
                        0,
                    )
                ),
            ]

            for column, value in enumerate(
                values
            ):
                item = QTableWidgetItem(
                    value
                )

                if candle.get(
                    "is_current"
                ):
                    item.setBackground(
                        QColor(
                            255,
                            205,
                            60,
                            100,
                        )
                    )
                elif int(
                    candle.get(
                        "track_age",
                        0,
                    )
                ) >= 3:
                    item.setBackground(
                        QColor(
                            0,
                            190,
                            140,
                            45,
                        )
                    )

                self.table.setItem(
                    row,
                    column,
                    item,
                )

    # =========================================================
    # PREDICTION
    # =========================================================
    def _update_prediction(
        self,
        message,
        signal,
    ):
        self.prediction_label.setText(
            f"NEXT "
            f"{signal.get('horizon_seconds',30)}s: "
            f"{signal.get('label','NO TRADE')}"
        )

        up = float(
            signal.get(
                "up_probability",
                0.5,
            )
        )

        down = float(
            signal.get(
                "down_probability",
                0.5,
            )
        )

        confidence = float(
            signal.get(
                "confidence",
                0.0,
            )
        )

        agreement = float(
            signal.get(
                "agreement",
                0.0,
            )
        )

        self.prediction_probability.setText(
            f"UP {up*100:.1f}% | "
            f"DOWN {down*100:.1f}%"
        )

        self.prediction_confidence.setText(
            f"Confidence {confidence*100:.1f}% | "
            f"Agreement {agreement*100:.1f}%"
        )

        clock = message.get(
            "clock",
            {},
        )

        self.prediction_target.setText(
            "Next window: "
            f"{clock.get('end','—')}"
            " → +"
            f"{signal.get('horizon_seconds',30)}s"
        )

    # =========================================================
    # AUDIT
    # =========================================================
    def _update_audit(
        self,
        signal,
    ):
        for name, label in (
            self.layer_labels.items()
        ):
            label.setText(
                "WAITING"
            )

        for component in (
            signal.get(
                "components",
                [],
            )
        ):
            name = component.get(
                "name",
                "",
            )

            if name in self.layer_labels:
                self.layer_labels[
                    name
                ].setText(
                    f"{component.get('direction','N/A')} "
                    f"{float(component.get('probability_up',.5))*100:.1f}%"
                )

        reasons = signal.get(
            "reasons",
            [],
        )

        gates = signal.get(
            "no_trade_reasons",
            [],
        )

        self.events.setPlainText(
            "LAYER REASONS\n"
            + "\n".join(
                reasons
            )
            + "\n\nNO-TRADE GATES\n"
            + (
                "\n".join(
                    gates
                )
                if gates
                else "None"
            )
        )

        diagnostics = (
            signal.get(
                "diagnostics",
                {},
            )
            or {}
        )

        lines = [
            "REFERENCE: CURRENT VISIBLE PRICE",
            "",
            f"RSI: {diagnostics.get('rsi')}",
            f"MACD histogram: {diagnostics.get('macd_hist')}",
            f"Stochastic: {diagnostics.get('stoch_k')} / {diagnostics.get('stoch_d')}",
            f"CCI: {diagnostics.get('cci')}",
            f"Williams %R: {diagnostics.get('williams_r')}",
            (
                "EMA 9/21/50/200: "
                f"{diagnostics.get('ema9')} / "
                f"{diagnostics.get('ema21')} / "
                f"{diagnostics.get('ema50')} / "
                f"{diagnostics.get('ema200')}"
            ),
            f"ADX: {diagnostics.get('adx')}",
            (
                "Volatility: "
                f"{diagnostics.get('volatility_regime')}"
            ),
            (
                "Support/Resistance: "
                f"{diagnostics.get('support')} / "
                f"{diagnostics.get('resistance')}"
            ),
            f"VWAP: {diagnostics.get('vwap')}",
            (
                "Structure: "
                f"{diagnostics.get('structure')}"
            ),
        ]

        self.diagnostics.setPlainText(
            "\n".join(lines)
        )

    # =========================================================
    # OVERLAY
    # =========================================================
    def _update_overlay(
        self,
        message,
        signal,
    ):
        if not self.vision_box.isChecked():
            self.overlay.hide()
            return

        rect = self.last_rect

        if not rect:
            return

        left, top, right, bottom = (
            rect
        )

        boxes = []

        for candle in (
            message.get(
                "candles",
                [],
            )
        ):
            x = int(
                candle.get(
                    "body_left",
                    0,
                )
            )
            y = int(
                candle.get(
                    "body_top",
                    0,
                )
            )

            w = max(
                2,
                int(
                    candle.get(
                        "body_right",
                        0,
                    )
                    - x
                    + 1
                ),
            )

            h = max(
                3,
                int(
                    candle.get(
                        "body_bottom",
                        0,
                    )
                    - y
                    + 1
                ),
            )

            boxes.append(
                (
                    x - left,
                    y - top,
                    w,
                    h,
                    float(
                        candle.get(
                            "confidence",
                            0,
                        )
                    ),
                    bool(
                        candle.get(
                            "is_current",
                            False,
                        )
                    ),
                    int(
                        candle.get(
                            "track_id",
                            -1,
                        )
                    ),
                    int(
                        candle.get(
                            "track_age",
                            0,
                        )
                    ),
                    str(
                        candle.get(
                            "track_state",
                            "",
                        )
                    ),
                )
            )

        if signal is None:
            label = "SCAN"
            probability = 0.5
            confidence = 0.0
        else:
            label = signal.get(
                "label",
                "NO TRADE",
            )
            probability = float(
                signal.get(
                    "up_probability",
                    0.5,
                )
            )
            confidence = float(
                signal.get(
                    "confidence",
                    0.0,
                )
            )

        status = (
            f"LIVE | "
            f"Tracked "
            f"{len(boxes)} | "
            f"Stability "
            f"{float(message.get('tracking_stability',0))*100:.0f}%"
        )

        self.overlay.setGeometry(
            left,
            top,
            max(
                1,
                right - left,
            ),
            max(
                1,
                bottom - top,
            ),
        )

        self.overlay.set_data(
            boxes,
            label,
            probability,
            confidence,
            status,
            current_index=-1,
            tracking_stability=float(
                message.get(
                    "tracking_stability",
                    0.0,
                )
            ),
            tracked_count=len(boxes),
            frame_id=int(
                message.get(
                    "frame_id",
                    0,
                )
            ),
        )

        self.overlay.show()

    # =========================================================
    # CANDLE EVENTS
    # =========================================================
    def _record_candle_event(
        self,
        event,
        message,
    ):
        closed = event.get(
            "closed_candle"
        )

        if not closed:
            return

        direction = (
            "BULL"
            if closed.get(
                "bullish"
            )
            else "BEAR"
        )

        self.events.append(
            (
                "CANDLE CLOSED  "
                f"T{int(closed.get('track_id',-1)):03d}  "
                f"{direction}  "
                f"Vision "
                f"{float(closed.get('confidence',0))*100:.1f}%  "
                f"Frame "
                f"{closed.get('last_seen_frame',0)}"
            )
        )

    # =========================================================
    # CLOCK / WATCHDOG
    # =========================================================
    def _update_clock(self):
        start, end, remaining = (
            self.clock.formatted()
        )

        if (
            not self.running
            and self.last_candles
        ):
            return

        self.current_time.setText(
            "Time: "
            f"{start} → {end}"
        )

        self.current_remaining.setText(
            "Remaining: "
            f"{remaining}s"
        )

    def _timeframe_changed(
        self,
        index,
    ):
        self.clock.timeframe_seconds = [
            30,
            60,
            120,
        ][index]

    def _offset_changed(
        self,
        value,
    ):
        self.clock.offset_seconds = value

    def _toggle_boxes(
        self,
        state,
    ):
        if state and self.running:
            self.overlay.show()
        else:
            self.overlay.hide()

    def _watchdog_tick(self):
        if not self.running:
            return

        if (
            self.last_worker_message
            and (
                time.monotonic()
                - self.last_worker_message
                > 4.0
            )
        ):
            self.live_status.setText(
                "WORKER HEARTBEAT LOST — "
                "RESTARTING"
            )

            self._restart_worker()

    def _restart_worker(self):
        if not self.running:
            return

        self.worker_restarts += 1

        try:
            if self.worker is not None:
                self.worker.kill()
        except Exception:
            pass

        self.worker = None
        self.buffer = b""

        QTimer.singleShot(
            500,
            self._start_worker,
        )

    def closeEvent(
        self,
        event,
    ):
        self.running = False

        try:
            if self.worker is not None:
                self.worker.kill()
        except Exception:
            pass

        self.overlay.hide()
        event.accept()
