"""PostToolUse hook: syntax check + experience match + auto-learn.

Three layers:
  1. Syntax check (py_compile / json / bash -n / custom rules)
  2. Experience matching (lessons.json triggers vs diff)
  3. Auto-learning (error → candidate → second strike → lesson)

Invoked by Claude Code after every Edit/Write via PostToolUse hook.
"""

import json
import os
import re
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

HOOK_DIR = Path(__file__).resolve().parent
LESSONS_FILE = HOOK_DIR / "lessons.json"
CANDIDATES_FILE = HOOK_DIR / "lesson_candidates.json"
DECAY_DAYS = 90
CANDIDATE_TTL_DAYS = 30
MAX_WEIGHT = 10


# ---------------------------------------------------------------------------
# Layer 1: Syntax checks
# ---------------------------------------------------------------------------

def _py_check(filepath: str, content: str) -> list[str]:
    """Compile-check a Python file. Returns error lines."""
    errors = []
    import py_compile
    import tempfile
    try:
        py_compile.compile(filepath, doraise=True)
    except py_compile.PyCompileError as e:
        errors.append(f"[py_compile] {e}")
    return errors


def _json_check(filepath: str, content: str) -> list[str]:
    """Parse JSON. Returns error lines."""
    errors = []
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        errors.append(f"[json] {e}")
    return errors


def _shell_check(filepath: str, content: str) -> list[str]:
    """bash -n check. Returns error lines."""
    errors = []
    try:
        r = subprocess.run(
            ["bash", "-n", "-"],
            input=content, capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            errors.append(f"[bash -n] {r.stderr.strip()}")
    except FileNotFoundError:
        pass  # bash not available on this platform
    except Exception as e:
        errors.append(f"[bash -n] {e}")
    return errors


# Map extension → checker
CHECKERS = {
    ".py": _py_check,
    ".pyi": _py_check,
    ".json": _json_check,
    ".jsonc": _json_check,
    ".sh": _shell_check,
    ".bash": _shell_check,
}


# ---------------------------------------------------------------------------
# Layer 2: Experience matching
# ---------------------------------------------------------------------------

def _load_lessons() -> list[dict]:
    if not LESSONS_FILE.exists():
        return []
    try:
        return json.loads(LESSONS_FILE.read_text(encoding="utf-8")).get("lessons", [])
    except (json.JSONDecodeError, KeyError):
        return []


def _save_lessons(lessons: list[dict]):
    LESSONS_FILE.write_text(
        json.dumps({"lessons": lessons}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_candidates() -> list[dict]:
    if not CANDIDATES_FILE.exists():
        return []
    try:
        return json.loads(CANDIDATES_FILE.read_text(encoding="utf-8")).get("candidates", [])
    except (json.JSONDecodeError, KeyError):
        return []


def _save_candidates(candidates: list[dict]):
    CANDIDATES_FILE.write_text(
        json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _match_trigger(trigger: str, content: str) -> bool:
    """Check if trigger matches content. Supports 'regex:' prefix."""
    if trigger.startswith("regex:"):
        try:
            return bool(re.search(trigger[6:], content))
        except re.error:
            return False
    return trigger in content


def match_lessons(filepath: str, content: str) -> list[dict]:
    """Return lessons whose triggers fire on content. Updates hit stats."""
    lessons = _load_lessons()
    if not lessons:
        return []

    matched = []
    changed = False
    fn = Path(filepath).name

    for L in lessons:
        scope = L.get("scope", "*")
        if not _scope_match(scope, fn):
            continue

        triggers = L.get("triggers", [])
        if any(_match_trigger(t, content) for t in triggers):
            L["hits"] = L.get("hits", 0) + 1
            L["last_hit"] = int(time.time())
            w = L.get("weight", 1)
            L["weight"] = min(w + 1, MAX_WEIGHT)
            L.pop("last_decay_at", None)  # hit resets the 90-day clock
            matched.append(L)
            changed = True

    if changed:
        _save_lessons(lessons)

    return matched


def _scope_match(scope: str, filename: str) -> bool:
    """Simple glob match for scope against filename."""
    import fnmatch
    return fnmatch.fnmatch(filename, scope)


# ---------------------------------------------------------------------------
# Layer 3: Auto-learning from error signals
# ---------------------------------------------------------------------------

def _extract_trigger_from_error(filepath: str, content: str, error: str) -> str | None:
    """Heuristic to extract a trigger string from an error message.
    Example: 'DankeTheme.secondaryText does not exist' → 'DankeTheme.secondaryText'
    Example: "NameError: name 'foo' is not defined" → 'foo'
    """
    # Custom rule errors already have the identifier
    m = re.search(r"(\S+)\s+does not exist", error)
    if m:
        return m.group(1)

    # Python name/attribute errors
    m = re.search(r"name ['\"](\w+)['\"] is not defined", error)
    if m:
        return m.group(1)

    m = re.search(r"has no attribute ['\"](\w+)['\"]", error)
    if m:
        return m.group(1)

    # Import errors
    m = re.search(r"No module named ['\"](\S+)['\"]", error)
    if m:
        return m.group(1)

    return None


def record_errors(filepath: str, content: str, errors: list[str]):
    """Record syntax/custom errors into candidate pool. Second strike → lesson."""
    candidates = _load_candidates()
    lessons = _load_lessons()
    now = int(time.time())

    for err in errors:
        trigger = _extract_trigger_from_error(filepath, content, err)
        if not trigger:
            continue

        # Check existing candidates for second strike
        existing = None
        for c in candidates:
            if c.get("trigger") == trigger and c.get("scope") == filepath_ext(filepath):
                existing = c
                break

        if existing:
            # Second strike → promote to lesson
            existing["hits"] = existing.get("hits", 0) + 1
            existing["last_hit"] = now
            if existing["hits"] >= 2:
                # Promote
                new_lesson = {
                    "scope": existing["scope"],
                    "triggers": [existing["trigger"]],
                    "lesson": existing.get("lesson", f"Avoid: {trigger}"),
                    "weight": 2,
                    "hits": 2,
                    "last_hit": now,
                    "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }
                # Avoid duplicates
                dup = False
                for L in lessons:
                    if (L.get("scope") == new_lesson["scope"]
                            and set(L.get("triggers", [])) == set(new_lesson["triggers"])):
                        L["weight"] = min(L.get("weight", 1) + 1, MAX_WEIGHT)
                        L["hits"] = L.get("hits", 0) + 1
                        L["last_hit"] = now
                        dup = True
                        break
                if not dup:
                    lessons.append(new_lesson)
                    print(f"\n   auto-learned: '{trigger}' → new lesson (weight=2)")
                # Remove from candidates
                candidates = [c for c in candidates if c is not existing]
        else:
            # First strike → add to candidate pool
            candidates.append({
                "scope": filepath_ext(filepath),
                "trigger": trigger,
                "lesson": f"Avoid: {trigger}",
                "hits": 1,
                "last_hit": now,
                "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })

    # Clean expired candidates (30 days)
    cutoff = now - CANDIDATE_TTL_DAYS * 86400
    candidates = [c for c in candidates if c.get("last_hit", 0) > cutoff]

    _save_candidates(candidates)
    _save_lessons(lessons)


def filepath_ext(filepath: str) -> str:
    """Return '*.ext' for a filepath."""
    return f"*{Path(filepath).suffix}"


# ---------------------------------------------------------------------------
# Decay (run periodically)
# ---------------------------------------------------------------------------

def decay_lessons():
    """Decrease weight for lessons not hit within 90 days. Clean weight=0."""
    lessons = _load_lessons()
    now = int(time.time())
    cutoff = now - DECAY_DAYS * 86400
    changed = False

    for L in lessons:
        last = L.get("last_hit", 0)
        # Missing last_hit means fresh — treat as "now"
        if last == 0:
            last = now
        if last < cutoff:
            last_decay = L.get("last_decay_at", 0)
            # Only decay once per 90-day window
            if last_decay < cutoff:
                L["weight"] = max(L.get("weight", 1) - 1, 0)
                L["last_decay_at"] = now
                changed = True

    # Remove weight=0
    new_lessons = [L for L in lessons if L.get("weight", 1) > 0]
    if len(new_lessons) < len(lessons):
        removed = len(lessons) - len(new_lessons)
        print(f"\n   auto-cleaned: {removed} lesson(s) decayed to weight=0")
        changed = True

    if changed:
        _save_lessons(new_lessons)


# ---------------------------------------------------------------------------
# Main hook entry point
# ---------------------------------------------------------------------------

def main():
    # Claude Code passes the edited file path via stdin or env
    # PostToolUse gives us tool_input via CLAUDE_TOOL_INPUT env
    tool_input = os.environ.get("CLAUDE_TOOL_INPUT", "")
    tool_name = os.environ.get("CLAUDE_TOOL_NAME", "")

    # Parse file path from environment or args
    filepath = None
    if tool_input:
        try:
            data = json.loads(tool_input)
            filepath = data.get("file_path", "")
        except json.JSONDecodeError:
            pass

    if not filepath:
        filepath = sys.argv[1] if len(sys.argv) > 1 else ""

    if not filepath or not os.path.isfile(filepath):
        return 0

    # Never process hook data files (prevent self-modification loop)
    fpath = Path(filepath).resolve()
    if str(HOOK_DIR) in str(fpath):
        return 0

    ext = Path(filepath).suffix.lower()

    # Read current file content
    try:
        content = Path(filepath).read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return 0  # binary or inaccessible

    all_errors = []

    # Layer 1: Syntax check
    checker = CHECKERS.get(ext)
    if checker:
        syntax_errors = checker(filepath, content)
        all_errors.extend(syntax_errors)
        for e in syntax_errors:
            print(f"\n   Syntax error in {filepath}: {e}")

    # Run custom rules (extensible)
    custom_errors = run_custom_rules(filepath, content)
    all_errors.extend(custom_errors)

    # Layer 2: Experience matching
    matched = match_lessons(filepath, content)
    for m in matched:
        w = m.get("weight", 1)
        print(f"\n    反思(权重{w}): {m.get('lesson', '')}")

    # Layer 3: Record errors for auto-learning
    if all_errors:
        record_errors(filepath, content, all_errors)

    # Periodically run decay (roughly once per session)
    decay_lessons()

    # Fail on syntax errors so Claude Code can react
    if all_errors:
        print(f"\n   {len(all_errors)} error(s) detected. Check and fix.\n")

    return 0  # Don't block Claude — warn but don't stop


# ---------------------------------------------------------------------------
# Custom rules registry (project-specific checks)
# ---------------------------------------------------------------------------

def run_custom_rules(filepath: str, content: str) -> list[str]:
    """Extensible custom rule runner. Add your own rules here."""
    errors = []

    # Rule: Check for common Windows path issues in Python code
    ext = Path(filepath).suffix.lower()
    if ext == ".py":
        # Detect backslash paths in string literals (should use forward slash)
        if re.search(r'["\'].*\\\\', content):
            errors.append("[custom] Backslash in string path detected - use forward slashes")

        # Detect os.system / os.popen (prefer subprocess)
        if re.search(r'\bos\.(system|popen)\b', content):
            errors.append("[custom] os.system/os.popen usage - prefer subprocess.run")

        # Detect bare except
        if re.search(r'\bexcept\s*:', content):
            errors.append("[custom] Bare 'except:' - catch specific exceptions")

    return errors


if __name__ == "__main__":
    sys.exit(main())
