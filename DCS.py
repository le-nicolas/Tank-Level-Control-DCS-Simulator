"""Simple DCS dashboard for multi-tank level control simulation."""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from typing import Dict, List

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class SpillAnimationWidget(QWidget):
    """Animated falling droplets used when a tank is in overflow."""

    def __init__(self, parent: QWidget | None = None, drop_count: int = 12):
        super().__init__(parent)
        self._rng = random.Random()
        self._drop_count = drop_count
        self._drops: List[Dict[str, float]] = []
        self._active = False
        self._paused = False

        self.setMinimumHeight(52)
        self.setMaximumHeight(52)
        self.setStyleSheet("background-color: #ECF7FF; border: 1px solid #BFD9F3; border-radius: 8px;")

        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._advance)

    def set_active(self, is_active: bool) -> None:
        if self._active == is_active:
            return

        self._active = is_active
        if is_active:
            self._seed_drops()
            if not self._paused:
                self._timer.start()
        else:
            self._timer.stop()
            self._drops.clear()

        self.update()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if not self._active:
            return

        if paused:
            self._timer.stop()
        else:
            self._timer.start()

    def _seed_drops(self) -> None:
        width = max(80, self.width())
        height = max(40, self.height())
        self._drops = [self._new_drop(width, height, randomize_height=True) for _ in range(self._drop_count)]

    def _new_drop(self, width: int, height: int, randomize_height: bool = False) -> Dict[str, float]:
        return {
            "x": self._rng.uniform(10, max(12, width - 12)),
            "y": self._rng.uniform(-height, 0) if randomize_height else self._rng.uniform(-16, 0),
            "vx": self._rng.uniform(-0.8, 0.8),
            "vy": self._rng.uniform(2.8, 6.2),
            "size": self._rng.uniform(3.0, 5.8),
        }

    def _advance(self) -> None:
        if not self._drops:
            self._seed_drops()

        width = max(80, self.width())
        height = self.height()

        for drop in self._drops:
            drop["x"] += drop["vx"]
            drop["y"] += drop["vy"]

            # Keep droplets inside horizontal bounds with a small bounce.
            if drop["x"] < 8:
                drop["x"] = 8
                drop["vx"] = abs(drop["vx"])
            elif drop["x"] > width - 8:
                drop["x"] = width - 8
                drop["vx"] = -abs(drop["vx"])

            if drop["y"] > height + drop["size"]:
                drop.update(self._new_drop(width, height))

        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Small overflow lip at the top.
        painter.setPen(QPen(QColor("#2D6EA3"), 2))
        painter.drawLine(8, 6, self.width() - 8, 6)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(43, 152, 255, 180))
        for drop in self._drops:
            x = int(drop["x"])
            y = int(drop["y"])
            width = int(drop["size"])
            height = int(drop["size"] * 1.7)
            painter.drawEllipse(x, y, width, height)

    def resizeEvent(self, _event) -> None:
        if self._active:
            self._seed_drops()
        super().resizeEvent(_event)


@dataclass
class TankState:
    """Simulation state for a single tank."""

    tank_id: int
    level: int = 50
    target_level: int = 50
    tolerance: int = 10
    pending_disturbance: int = 0

    @property
    def min_level(self) -> int:
        return max(0, self.target_level - self.tolerance)

    @property
    def max_level(self) -> int:
        return min(100, self.target_level + self.tolerance)

    def apply_disturbance(self, amount: int) -> None:
        self.pending_disturbance += amount

    def step(self, rng: random.Random) -> None:
        # Base process fluctuation + operator/environment disturbance.
        self.level += rng.randint(-3, 3) + self.pending_disturbance
        self.pending_disturbance = 0

        # Local control action to push level toward target range.
        if self.level < self.min_level:
            self.level += rng.randint(5, 10)
        elif self.level > self.max_level:
            self.level -= rng.randint(5, 10)

        self.level = max(0, min(100, self.level))


@dataclass
class TankCard:
    level_label: QLabel
    status_label: QLabel
    range_label: QLabel
    spill_label: QLabel
    spill_animation: SpillAnimationWidget
    slider: QSlider


class DCSApp(QMainWindow):
    """PyQt dashboard simulating distributed tank level control."""

    def __init__(self, tank_count: int = 4, update_interval_ms: int = 1500):
        super().__init__()
        self.setWindowTitle("Algebra to DCS - Multi-Tank Monitoring")
        self.setGeometry(100, 100, 980, 640)

        self.rng = random.Random()
        self.tanks: List[TankState] = [TankState(tank_id=index + 1) for index in range(tank_count)]
        self.cards: List[TankCard] = []
        self.is_running = True

        self._build_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_tanks)
        self.timer.start(update_interval_ms)
        self.statusBar().showMessage("Simulation running", 3000)

        for index in range(len(self.tanks)):
            self.refresh_tank_display(index)

    def _build_ui(self) -> None:
        container = QWidget()
        root_layout = QVBoxLayout()
        root_layout.setSpacing(12)

        title = QLabel("Distributed Control System Dashboard")
        title.setStyleSheet("font-size: 24px; font-weight: 700; color: #1B263B;")
        subtitle = QLabel(
            "Each tank has local control. Adjust target levels and inject disturbances to observe behavior."
        )
        subtitle.setStyleSheet("font-size: 14px; color: #415A77;")

        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.pause_button = QPushButton("Pause Simulation")
        self.pause_button.clicked.connect(self.toggle_simulation)

        reset_button = QPushButton("Reset Tanks")
        reset_button.clicked.connect(self.reset_tanks)

        controls.addWidget(self.pause_button)
        controls.addWidget(reset_button)
        controls.addStretch(1)

        grid = QGridLayout()
        grid.setSpacing(12)

        for index, tank in enumerate(self.tanks):
            card_frame, card = self._create_tank_card(index, tank)
            self.cards.append(card)
            row = index // 2
            col = index % 2
            grid.addWidget(card_frame, row, col)

        root_layout.addWidget(title)
        root_layout.addWidget(subtitle)
        root_layout.addLayout(controls)
        root_layout.addLayout(grid)
        root_layout.addStretch(1)

        container.setLayout(root_layout)
        self.setCentralWidget(container)

    def _create_tank_card(self, index: int, tank: TankState):
        card_frame = QFrame()
        card_frame.setFrameShape(QFrame.StyledPanel)
        card_frame.setStyleSheet(
            "QFrame {"
            "background-color: #F8FAFC;"
            "border: 1px solid #D7DFE8;"
            "border-radius: 10px;"
            "padding: 10px;"
            "}"
        )

        layout = QVBoxLayout()
        layout.setSpacing(8)

        name_label = QLabel(f"Tank-{tank.tank_id}")
        name_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #0D1B2A;")

        level_label = QLabel("Level: --%")
        level_label.setStyleSheet("font-size: 16px; font-weight: 600;")

        status_label = QLabel("Status: --")
        status_label.setStyleSheet("font-size: 14px;")

        range_label = QLabel("Target/Range: --")
        range_label.setStyleSheet("font-size: 13px; color: #495057;")

        spill_label = QLabel("Overflow spill: inactive")
        spill_label.setStyleSheet("font-size: 13px; color: #4A5568;")

        spill_animation = SpillAnimationWidget()
        spill_animation.hide()

        slider = QSlider(Qt.Horizontal)
        slider.setRange(20, 80)
        slider.setValue(tank.target_level)
        slider.valueChanged.connect(
            lambda value, tank_index=index: self.update_threshold(tank_index, value)
        )

        disturbance_button = QPushButton("Inject Disturbance")
        disturbance_button.clicked.connect(
            lambda _checked=False, tank_index=index: self.simulate_disturbance(tank_index)
        )

        spill_test_button = QPushButton("Trigger Spill Sample")
        spill_test_button.clicked.connect(
            lambda _checked=False, tank_index=index: self.trigger_spill_sample(tank_index)
        )

        layout.addWidget(name_label)
        layout.addWidget(level_label)
        layout.addWidget(status_label)
        layout.addWidget(range_label)
        layout.addWidget(spill_label)
        layout.addWidget(spill_animation)
        layout.addWidget(slider)
        layout.addWidget(disturbance_button)
        layout.addWidget(spill_test_button)
        card_frame.setLayout(layout)

        return card_frame, TankCard(
            level_label=level_label,
            status_label=status_label,
            range_label=range_label,
            spill_label=spill_label,
            spill_animation=spill_animation,
            slider=slider,
        )

    def update_tanks(self) -> None:
        for index, tank in enumerate(self.tanks):
            tank.step(self.rng)
            self.refresh_tank_display(index)

    def refresh_tank_display(self, tank_index: int) -> None:
        tank = self.tanks[tank_index]
        card = self.cards[tank_index]
        is_overflow = tank.level > tank.max_level

        if tank.level < tank.min_level or tank.level > tank.max_level:
            state_text = "ALARM"
            color = "#B00020"
        elif tank.level <= tank.min_level + 3 or tank.level >= tank.max_level - 3:
            state_text = "Warning"
            color = "#9A6700"
        else:
            state_text = "Stable"
            color = "#1A7F37"

        card.level_label.setText(f"Level: {tank.level}%")
        card.level_label.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {color};")
        card.status_label.setText(f"Status: {state_text}")
        card.status_label.setStyleSheet(f"font-size: 14px; color: {color};")
        card.range_label.setText(
            f"Target: {tank.target_level}%  |  Control Range: {tank.min_level}-{tank.max_level}%"
        )

        if is_overflow:
            card.spill_label.setText("Overflow spill: active")
            card.spill_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #0065B3;")
            card.spill_animation.show()
            card.spill_animation.set_active(True)
            card.spill_animation.set_paused(not self.is_running)
        else:
            card.spill_label.setText("Overflow spill: inactive")
            card.spill_label.setStyleSheet("font-size: 13px; color: #4A5568;")
            card.spill_animation.set_active(False)
            card.spill_animation.hide()

    def update_threshold(self, tank_index: int, value: int) -> None:
        tank = self.tanks[tank_index]
        tank.target_level = value
        self.refresh_tank_display(tank_index)
        self.statusBar().showMessage(
            f"Tank-{tank.tank_id} target changed to {value}% (range {tank.min_level}-{tank.max_level}%)",
            3500,
        )

    def simulate_disturbance(self, tank_index: int) -> None:
        tank = self.tanks[tank_index]
        disturbance = self.rng.randint(-20, 20)
        tank.apply_disturbance(disturbance)
        tank.step(self.rng)
        self.refresh_tank_display(tank_index)
        self.statusBar().showMessage(
            f"Applied disturbance to Tank-{tank.tank_id}: {disturbance:+d}",
            3500,
        )

    def trigger_spill_sample(self, tank_index: int) -> None:
        tank = self.tanks[tank_index]
        overflow_push = self.rng.randint(24, 34)
        tank.apply_disturbance(overflow_push)
        tank.step(self.rng)
        self.refresh_tank_display(tank_index)
        self.statusBar().showMessage(
            f"Spill sample triggered for Tank-{tank.tank_id}: +{overflow_push}",
            3500,
        )

    def toggle_simulation(self) -> None:
        if self.is_running:
            self.timer.stop()
            self.pause_button.setText("Resume Simulation")
            self.statusBar().showMessage("Simulation paused", 2500)
        else:
            self.timer.start()
            self.pause_button.setText("Pause Simulation")
            self.statusBar().showMessage("Simulation running", 2500)

        for card in self.cards:
            card.spill_animation.set_paused(self.is_running)

        self.is_running = not self.is_running

    def reset_tanks(self) -> None:
        for index, tank in enumerate(self.tanks):
            tank.level = 50
            tank.target_level = 50
            tank.pending_disturbance = 0

            slider = self.cards[index].slider
            slider.blockSignals(True)
            slider.setValue(50)
            slider.blockSignals(False)

            self.refresh_tank_display(index)

        self.statusBar().showMessage("Tank states reset to defaults", 3000)


def main() -> int:
    app = QApplication(sys.argv)
    window = DCSApp()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
