from models.vrr_repaint_coalescing import (
    ACTIVE_CADENCE_LIMIT_NS,
    STOCK_DELAY_NS,
    RepaintAction,
    decide_repaint,
    frame_interval_ns,
)


def decision(game_hz: float, output_hz: float = 240, **overrides):
    arguments = {
        "exact_kernel_gate": True,
        "coalescing_enabled": True,
        "vrr_or_tearing": True,
        "foreground_damage": False,
        "active_frame_interval_ns": frame_interval_ns(game_hz),
        "output_refresh_interval_ns": frame_interval_ns(output_hz),
    }
    arguments.update(overrides)
    return decide_repaint(**arguments)


def test_foreground_damage_is_always_immediate():
    result = decision(240, foreground_damage=True)
    assert result.action is RepaintAction.IMMEDIATE
    assert result.delay_ns == 0


def test_non_vrr_path_is_untouched():
    result = decision(240, vrr_or_tearing=False)
    assert result.action is RepaintAction.IMMEDIATE


def test_240_hz_game_coalesces_to_one_240_hz_frame():
    result = decision(240)
    assert result.action is RepaintAction.COALESCE
    assert result.delay_ns == frame_interval_ns(240)


def test_480_fps_is_clamped_to_physical_240_hz_output():
    result = decision(480)
    assert result.delay_ns == frame_interval_ns(240)


def test_observed_game_cadence_controls_fallback():
    assert decision(120).delay_ns == frame_interval_ns(120)
    assert decision(60).delay_ns == frame_interval_ns(60)
    assert decision(30).delay_ns == ACTIVE_CADENCE_LIMIT_NS


def test_fallback_is_phase_aligned_to_last_presentation():
    cadence = frame_interval_ns(240)
    result = decision(240, elapsed_since_presentation_ns=cadence // 2)
    assert result.delay_ns == cadence - cadence // 2


def test_missed_foreground_deadline_falls_through_immediately():
    cadence = frame_interval_ns(240)
    result = decision(240, elapsed_since_presentation_ns=cadence * 2)
    assert result.delay_ns == 0


def test_inactive_surface_does_not_enter_coalescing_policy():
    result = decision(29)
    assert result.action is RepaintAction.IMMEDIATE


def test_missing_exact_kernel_gate_preserves_stock_policy():
    result = decision(240, exact_kernel_gate=False)
    assert result.action is RepaintAction.STOCK_DELAY
    assert result.delay_ns == STOCK_DELAY_NS


def test_explicit_opt_in_is_required():
    result = decision(240, coalescing_enabled=False)
    assert result.action is RepaintAction.STOCK_DELAY
    assert result.delay_ns == STOCK_DELAY_NS


def test_each_output_uses_its_own_refresh_interval():
    main = decision(480, output_hz=240)
    secondary = decision(480, output_hz=60)
    assert main.delay_ns == frame_interval_ns(240)
    assert secondary.delay_ns == frame_interval_ns(60)
