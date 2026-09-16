#!/usr/bin/env python3
"""Verify patch installation"""

def verify():
    try:
        from patches.integration import create_test_emulator
        from patches.cycle_exact_tests import CycleExactTestVectors, TestRunner

        print("Creating test emulator...")
        emu = create_test_emulator()
        print("✓ Emulator created successfully")

        print("Loading test vectors...")
        vectors = CycleExactTestVectors()
        print(f"✓ Loaded {len(vectors.vectors)} test vectors")

        print("Running tests...")
        runner = TestRunner(emu)
        results = runner.run_all(vectors.vectors)

        print(f"\n✓ Installation verified!")
        print(f"  Tests passed: {results['passed']}/{results['total']}")
        print(f"  Pass rate: {results['pass_rate']*100:.1f}%")

        return results['pass_rate'] > 0.8
    except Exception as e:
        print(f"✗ Installation verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = verify()
    sys.exit(0 if success else 1)
