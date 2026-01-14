from typing import Any


def parse_tag_list(raw_tags: str | None) -> list[str]:
    if not raw_tags:
        return []
    parts = [part.strip() for part in raw_tags.split(",")]
    tags: list[str] = []
    seen = set()
    for part in parts:
        if part and part not in seen:
            tags.append(part)
            seen.add(part)
    return tags


def normalize_tags(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        tags: list[str] = []
        seen = set()
        for item in value:
            tag = str(item).strip()
            if tag and tag not in seen:
                tags.append(tag)
                seen.add(tag)
        return tags
    if isinstance(value, str):
        return parse_tag_list(value)
    return []


def merge_tags(existing_tags: list[str] | None, new_tags: list[str]) -> list[str]:
    merged: list[str] = []
    seen = set()
    for tag in existing_tags or []:
        if tag and tag not in seen:
            merged.append(tag)
            seen.add(tag)
    for tag in new_tags:
        if tag and tag not in seen:
            merged.append(tag)
            seen.add(tag)
    return merged
