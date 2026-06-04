"""Lesson maintenance: merge overlapping lessons, distill patterns, cleanup.

Run manually or via cron:
  python .claude/hooks/lesson_maintenance.py --merge
  python .claude/hooks/lesson_maintenance.py --distill  (dry-run, suggests only)
  python .claude/hooks/lesson_maintenance.py --cleanup
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

HOOK_DIR = Path(__file__).resolve().parent
LESSONS_FILE = HOOK_DIR / "lessons.json"


def load():
    try:
        return json.loads(LESSONS_FILE.read_text(encoding="utf-8")).get("lessons", [])
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return []


def save(lessons):
    LESSONS_FILE.write_text(
        json.dumps({"lessons": lessons}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def merge(lessons=None):
    """Merge lessons with >=2 overlapping triggers in same scope."""
    if lessons is None:
        lessons = load()
    changed = False

    # Group by scope
    by_scope = {}
    for L in lessons:
        by_scope.setdefault(L.get("scope", "*"), []).append(L)

    merged = []
    for scope, group in by_scope.items():
        skip = set()
        for i, a in enumerate(group):
            if i in skip:
                continue
            for j, b in enumerate(group):
                if j <= i or j in skip:
                    continue
                ta = set(a.get("triggers", []))
                tb = set(b.get("triggers", []))
                if len(ta & tb) >= 2:
                    # Merge b into a
                    a["triggers"] = list(ta | tb)
                    a["weight"] = max(a.get("weight", 1), b.get("weight", 1))
                    a["hits"] = a.get("hits", 0) + b.get("hits", 0)
                    a["lesson"] = f"{a['lesson']}; {b['lesson']}"
                    skip.add(j)
                    changed = True
                    print(f"   merged: {a['triggers']}")
            merged.append(a)
        for j in skip:
            pass  # already removed

    if changed:
        all_lessons = []
        seen_ids = set()
        for L in merged:
            tid = tuple(sorted(L.get("triggers", [])))
            if tid not in seen_ids:
                all_lessons.append(L)
                seen_ids.add(tid)
        save(all_lessons)

    return merged


def distill(lessons=None):
    """Suggest pattern distillation when 5+ lessons exist in same scope."""
    if lessons is None:
        lessons = load()
    by_scope = {}
    for L in lessons:
        by_scope.setdefault(L.get("scope", "*"), []).append(L)

    for scope, group in by_scope.items():
        if len(group) >= 5:
            print(f"\n   [distill suggestion] scope={scope} has {len(group)} lessons:")
            for L in group:
                print(f"      - ({L.get('weight')}) {L.get('lesson')}")
            print(f"    Consider running with --distill to auto-refine.\n")


def cleanup(lessons=None):
    """Remove lessons with weight=0."""
    if lessons is None:
        lessons = load()
    new = [L for L in lessons if L.get("weight", 1) > 0]
    if len(new) < len(lessons):
        save(new)
        print(f"   cleaned {len(lessons) - len(new)} weight=0 lesson(s)")
    return new


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--merge" in argv:
        merge()
    elif "--distill" in argv:
        distill()
    elif "--cleanup" in argv:
        cleanup()
    else:
        print("Usage: lesson_maintenance.py [--merge|--distill|--cleanup]")
        # Run all as default
        L = load()
        L = merge(L)
        distill(L)
        cleanup(L)
