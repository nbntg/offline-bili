from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from decimal import Decimal, ROUND_HALF_UP


class PlaybackBackend(Protocol):
    def set_speed(self, speed: float) -> None: ...
    def set_paused(self, paused: bool) -> None: ...


@dataclass
class SpeedController:
    backend: PlaybackBackend
    speed: Decimal = Decimal("1.00")

    MINIMUM = Decimal("0.00")
    MAXIMUM = Decimal("5.00")
    STEP = Decimal("0.05")

    def adjust_wheel(self, wheel_steps: int) -> float:
        return self.set(self.speed + self.STEP * wheel_steps)

    def reset(self) -> float:
        return self.set(Decimal("1.00"))

    def set(self, value: Decimal | float | str) -> float:
        quantized = Decimal(str(value)).quantize(self.STEP, rounding=ROUND_HALF_UP)
        self.speed = min(self.MAXIMUM, max(self.MINIMUM, quantized))

        if self.speed == 0:
            self.backend.set_paused(True)
        else:
            self.backend.set_speed(float(self.speed))
        return float(self.speed)
