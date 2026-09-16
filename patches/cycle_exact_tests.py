"""Deterministic smoke checks for the experimental SID-only wrapper.

These checks validate public behavior. They are not hardware-conformance or
cycle-exact test vectors.
"""
from __future__ import annotations

from typing import Any, Dict, List


def run_component_smoke_tests(emulator: Any) -> Dict[str, Any]:
    """Run deterministic checks and return a serializable result summary."""
    results: List[Dict[str, Any]] = []

    def check(name: str, callback) -> None:
        try:
            callback()
        except Exception as exc:
            results.append({'name': name, 'passed': False, 'error': str(exc)})
        else:
            results.append({'name': name, 'passed': True, 'error': ''})

    def reset_is_silent() -> None:
        emulator.reset()
        if emulator.get_sample() != 0:
            raise AssertionError('reset SID must be silent')

    def multi_chip_writes_are_addressable() -> None:
        emulator.reset()
        if len(emulator.sids) > 1:
            emulator.write_register(0x00, 0x55, chip=1)
            if emulator.sids[1].regs[0x00] != 0x55:
                raise AssertionError('write was not delivered to selected chip')

    def invalid_register_is_rejected() -> None:
        try:
            emulator.write_register(0x1D, 0)
        except ValueError:
            return
        raise AssertionError('invalid SID register was accepted')

    def combined_waveforms_follow_configuration() -> None:
        emulator.reset()
        enabled = emulator.config.enable_combined_waveforms
        if emulator.sids[0].cfg.enableCombinedWaveforms is not enabled:
            raise AssertionError('combined waveform setting was not applied')

    check('reset_is_silent', reset_is_silent)
    check('multi_chip_writes_are_addressable', multi_chip_writes_are_addressable)
    check('invalid_register_is_rejected', invalid_register_is_rejected)
    check('combined_waveforms_follow_configuration', combined_waveforms_follow_configuration)

    passed = sum(result['passed'] for result in results)
    return {
        'total': len(results),
        'passed': passed,
        'failed': len(results) - passed,
        'pass_rate': passed / len(results),
        'results': results,
    }
