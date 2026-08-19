from offline_bili.playback import SpeedController


class FakeBackend:
    def __init__(self):
        self.speed = 1.0
        self.paused = False

    def set_speed(self, speed: float) -> None:
        self.speed = speed

    def set_paused(self, paused: bool) -> None:
        self.paused = paused


def test_wheel_uses_point_zero_five_steps_and_clamps():
    backend = FakeBackend()
    controller = SpeedController(backend)

    assert controller.adjust_wheel(1) == 1.05
    assert controller.adjust_wheel(1000) == 5.0
    assert controller.adjust_wheel(-1000) == 0.0
    assert backend.paused


def test_non_zero_speed_keeps_pause_state_and_reset_restores_one():
    backend = FakeBackend()
    controller = SpeedController(backend)
    controller.set(0)

    controller.adjust_wheel(1)
    reset = controller.reset()

    assert backend.paused
    assert backend.speed == 1.0
    assert reset == 1.0


def test_adjusting_speed_while_manually_paused_does_not_resume():
    backend = FakeBackend()
    backend.paused = True
    controller = SpeedController(backend)

    controller.adjust_wheel(1)

    assert backend.paused
    assert backend.speed == 1.05
