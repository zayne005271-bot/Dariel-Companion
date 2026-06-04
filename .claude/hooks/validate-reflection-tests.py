"""Auto-trigger test wrapper for PostToolUse hook.

When validate-edit.py is modified, this runs the self-test suite.
If tests fail, it blocks (exit 1) so the bad change is caught immediately.
"""

import subprocess
import sys
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent
TEST_FILE = HOOK_DIR / "test_validate_edit.py"


def main():
    print("[validate-reflection-tests] running test suite...")
    r = subprocess.run(
        [sys.executable, str(TEST_FILE)],
        capture_output=False,
        timeout=30,
    )
    if r.returncode != 0:
        print("\n  🚨 Tests failed! Fix the issue before proceeding.")
        return 1
    print("\n  ✅ All reflection tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
