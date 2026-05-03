"""
Runtime test: run_all_tests.py
Runs all runtime tests in sequence and reports results.
Run from project root: python "run-time test/run_all_tests.py"
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# All test modules in this directory (in dependency order)
TEST_MODULES = [
    "test_models",
    "test_layout_store",
    "test_field_detector",
    "test_layout_analyzer",
    "test_reader_registry",
    "test_generator_registry",
    "test_db",
]

_tests_dir = Path(__file__).parent
sys.path.insert(0, str(_tests_dir))


def run_all() -> None:
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    for module_name in TEST_MODULES:
        print(f"\n{'='*60}")
        print(f"  Running: {module_name}")
        print(f"{'='*60}")
        try:
            mod = importlib.import_module(module_name)
            # Call all functions starting with "test_"
            test_fns = [
                (name, fn)
                for name, fn in vars(mod).items()
                if name.startswith("test_") and callable(fn)
            ]
            for name, fn in test_fns:
                fn()
            passed.append(module_name)
        except Exception:  # noqa: BLE001
            failed.append((module_name, traceback.format_exc()))

    print(f"\n{'='*60}")
    print(f"RESULTS: {len(passed)} passed, {len(failed)} failed")
    print(f"{'='*60}")

    for name, tb in failed:
        print(f"\n✗ FAILED: {name}")
        print(tb)

    if failed:
        sys.exit(1)
    else:
        print("\n✓ All tests passed.")


if __name__ == "__main__":
    run_all()
