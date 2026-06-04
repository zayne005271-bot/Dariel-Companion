"""Self-test suite for validate-edit.py — 10+ assertions.

Run via:
  python .claude/hooks/test_validate_edit.py
  python .claude/hooks/validate-reflection-tests.py  (wrapper that runs this)
"""

import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent

# Load validate-edit.py via importlib (filename has a hyphen)
spec = importlib.util.spec_from_file_location("validate_edit", HOOK_DIR / "validate-edit.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)

PASS = 0
FAIL = 0


def t(name: str):
    global PASS, FAIL
    return name


def ok(cond, msg=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {msg}" if msg else "  [PASS]")
    else:
        FAIL += 1
        print(f"  [FAIL] {msg}" if msg else "  [FAIL]")


def test_hit_increases_weight():
    """Lesson hit increments weight, hits, last_hit."""
    print(f"\n Test: lesson hit increases weight")
    lesson = {
        "scope": "*.py",
        "triggers": ["test_marker_xyz"],
        "lesson": "test lesson",
        "weight": 2,
        "hits": 0,
        "created": "2026-05-23",
    }
    v._save_lessons([lesson])

    matched = v.match_lessons("test.py", "this contains test_marker_xyz")
    ok(len(matched) == 1, "matched 1 lesson")
    ok(matched[0]["weight"] == 3, "weight increased (2→3)")
    ok(matched[0]["hits"] == 1, "hits = 1")
    ok("last_hit" in matched[0], "last_hit set")

    # Cleanup
    v._save_lessons([])


def test_decay_and_anti_consecutive():
    """Decay reduces weight once per 90-day window."""
    print(f"\n Test: decay + last_decay_at prevents consecutive decay")
    now = int(time.time())
    old = now - 91 * 86400  # 91 days ago
    lesson = {
        "scope": "*.py",
        "triggers": ["decay_marker_xyz"],
        "lesson": "decay test",
        "weight": 3,
        "hits": 1,
        "last_hit": old,
        "created": "2026-05-23",
    }
    v._save_lessons([lesson])

    # First decay
    v.decay_lessons()
    lessons = v._load_lessons()
    ok(len(lessons) == 1, "lesson still exists after 1st decay")
    ok(lessons[0]["weight"] == 2, "weight decayed 3→2")
    ok("last_decay_at" in lessons[0], "last_decay_at set")

    # Second decay immediately — should NOT decay again
    v.decay_lessons()
    lessons = v._load_lessons()
    ok(lessons[0]["weight"] == 2, "weight stays 2 (anti-consecutive decay)")

    # Cleanup
    v._save_lessons([])


def test_decay_to_zero_removes():
    """Decay to weight=0 removes lesson."""
    print(f"\n Test: decay to 0 auto-cleans lesson")
    now = int(time.time())
    old = now - 91 * 86400
    lesson = {
        "scope": "*.py",
        "triggers": ["cleanup_marker_xyz"],
        "lesson": "will be cleaned",
        "weight": 1,
        "hits": 1,
        "last_hit": old,
        "created": "2026-05-23",
    }
    v._save_lessons([lesson])

    v.decay_lessons()
    lessons = v._load_lessons()
    ok(len(lessons) == 0, "weight=0 lesson cleaned up")

    # Cleanup
    v._save_lessons([])


def test_regex_trigger():
    """Regex trigger matches pattern."""
    print(f"\n Test: regex trigger matching")
    lesson = {
        "scope": "*.py",
        "triggers": ["regex:import\\s+os\\.path"],
        "lesson": "use pathlib",
        "weight": 2,
        "hits": 0,
        "created": "2026-05-23",
    }
    v._save_lessons([lesson])

    matched = v.match_lessons("test.py", "import os.path as p")
    ok(len(matched) == 1, "regex trigger matches 'import os.path'")

    v._save_lessons([])


def test_scope_filter():
    """Scope filters by file extension."""
    print(f"\n Test: scope filter")
    lesson = {
        "scope": "*.swift",
        "triggers": ["some_swift_thing"],
        "lesson": "swift only",
        "weight": 2,
        "hits": 0,
        "created": "2026-05-23",
    }
    v._save_lessons([lesson])

    matched = v.match_lessons("test.py", "some_swift_thing")
    ok(len(matched) == 0, "*.swift lesson does not fire on .py file")

    matched = v.match_lessons("test.swift", "some_swift_thing")
    ok(len(matched) == 1, "*.swift lesson fires on .swift file")

    v._save_lessons([])


def test_json_syntax_check():
    """JSON checker catches syntax errors."""
    print(f"\n Test: JSON syntax check")
    errors = v._json_check("test.json", '{"key": "value",}')
    ok(len(errors) > 0, "trailing comma caught by JSON checker")

    errors = v._json_check("test.json", '{"key": "value"}')
    ok(len(errors) == 0, "valid JSON passes")


def test_candidate_promotion():
    """Second strike promotes candidate to lesson."""
    print(f"\n Test: candidate promotion on second strike")
    v._save_lessons([])
    v._save_candidates([])

    # First strike
    v.record_errors("test.py", "", ["DankeTheme.secondaryText does not exist"])
    candidates = v._load_candidates()
    ok(len(candidates) == 1, "first strike → candidate")
    ok(candidates[0]["hits"] == 1, "candidate hits = 1")

    # Second strike
    v.record_errors("test.py", "", ["DankeTheme.secondaryText does not exist"])
    candidates = v._load_candidates()
    ok(len(candidates) == 0, "second strike → promoted, removed from candidates")

    lessons = v._load_lessons()
    ok(
        any("DankeTheme.secondaryText" in L.get("triggers", []) for L in lessons),
        "lesson created with correct trigger",
    )

    # Cleanup
    v._save_lessons([])
    v._save_candidates([])


def test_extract_trigger():
    """Trigger extraction from error messages."""
    print(f"\n Test: error→trigger extraction")
    t = v._extract_trigger_from_error("test.py", "", "DankeTheme.primaryText does not exist")
    ok(t == "DankeTheme.primaryText", "custom rule trigger extracted")

    t = v._extract_trigger_from_error("test.py", "", "NameError: name 'spam' is not defined")
    ok(t == "spam", "NameError trigger extracted")

    t = v._extract_trigger_from_error("test.py", "", "No module named 'requests'")
    ok(t == "requests", "import error trigger extracted")


def test_custom_rules():
    """Custom rules detect bad patterns."""
    print(f"\n Test: custom rules")
    errs = v.run_custom_rules("test.py", "os.system('rm -rf /')")
    ok(any("os.system" in e for e in errs), "os.system detected")

    errs = v.run_custom_rules("test.py", "try:\n  x=1\nexcept:\n  pass")
    ok(any("Bare 'except:'" in e for e in errs), "bare except detected")


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

def main():
    global PASS, FAIL
    print("=" * 50)
    print("  [validate-edit.py self-test suite]")
    print("=" * 50)

    test_hit_increases_weight()
    test_decay_and_anti_consecutive()
    test_decay_to_zero_removes()
    test_regex_trigger()
    test_scope_filter()
    test_json_syntax_check()
    test_candidate_promotion()
    test_extract_trigger()
    test_custom_rules()

    print(f"\n{'=' * 50}")
    print(f"  Results:  {PASS} passed,  {FAIL} failed")
    print(f"{'=' * 50}")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
