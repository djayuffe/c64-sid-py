#!/usr/bin/env python3
"""Verify patch installation"""

import sys

def verify():
    try:
        from patches.integration import create_test_emulator
        from patches.cycle_exact_tests import run_component_smoke_tests

        print("Creating test emulator...")
        emu = create_test_emulator()
        print("✓ Emulator created successfully")

        print("Running deterministic component smoke checks...")
        results = run_component_smoke_tests(emu)

        print("\nComponent smoke-check results:")
        print(f"  Tests passed: {results['passed']}/{results['total']}")
        print(f"  Pass rate: {results['pass_rate']*100:.1f}%")

        return results['failed'] == 0
    except Exception as e:
        print(f"✗ Installation verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = verify()
    sys.exit(0 if success else 1)
