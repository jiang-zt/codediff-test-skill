from dataclasses import dataclass


@dataclass
class ChangedFile:
    path: str
    old_path: str
    status: str
    patch: str
    added_lines: int = 0
    removed_lines: int = 0


@dataclass
class ChangeContext:
    base_sha: str
    head_sha: str
    title: str
    description: str
    files: list[ChangedFile]
    full_patch: str