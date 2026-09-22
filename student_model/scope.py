"""Explicit chapter-scope exclusions for prerequisite presentation."""


def outside_chapter(value):
    if isinstance(value, dict):
        return any(outside_chapter(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(outside_chapter(v) for v in value)
    return isinstance(value, str) and '本章不展开' in ''.join(value.split())
