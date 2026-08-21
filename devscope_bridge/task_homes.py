"""Per-schedule task homes with memory and reports."""

from datetime import datetime
from pathlib import Path


_BASE = None


def set_base_dir(path: Path | None) -> None:
    """Override the base directory for task homes (test override)."""
    global _BASE
    _BASE = path


def _get_base_dir() -> Path:
    """Get the current base directory, using default if not overridden."""
    if _BASE is not None:
        return _BASE
    return Path.home() / ".dev-bridge" / "task_homes"


def home_dir(schedule_id: int) -> Path:
    """Get the home directory for a schedule, creating it if needed."""
    path = _get_base_dir() / str(schedule_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_memory(schedule_id: int) -> str:
    """Read the memory file for a schedule, returning empty string if missing."""
    memory_file = home_dir(schedule_id) / "memory.md"
    if not memory_file.exists():
        return ""
    return memory_file.read_text(encoding="utf-8")


def write_memory(schedule_id: int, content: str) -> None:
    """Write the memory file for a schedule."""
    memory_file = home_dir(schedule_id) / "memory.md"
    memory_file.write_text(content, encoding="utf-8")


def append_memory(schedule_id: int, note: str) -> None:
    """Append a note to the memory file under today's date header."""
    memory_file = home_dir(schedule_id) / "memory.md"

    # Read existing content
    if memory_file.exists():
        content = memory_file.read_text(encoding="utf-8")
    else:
        content = ""

    # Get today's date header
    today = datetime.now().strftime("%Y-%m-%d")
    today_header = f"## {today}"

    # Check if the last header is today's
    lines = content.split("\n")
    last_header = None
    for line in reversed(lines):
        if line.startswith("## "):
            last_header = line
            break

    # Append the note
    if last_header == today_header:
        # Just append the note at the end
        if content and not content.endswith("\n"):
            new_content = content + f"\n- {note}\n"
        else:
            new_content = content + f"- {note}\n"
    else:
        # Append new date header and note
        if content:
            new_content = content + f"\n{today_header}\n- {note}\n"
        else:
            new_content = f"{today_header}\n- {note}\n"

    # Ensure exactly one trailing newline
    new_content = new_content.rstrip("\n") + "\n"

    memory_file.write_text(new_content, encoding="utf-8")


def reports_dir(schedule_id: int) -> Path:
    """Get the reports directory for a schedule, creating it if needed."""
    path = home_dir(schedule_id) / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_reports(schedule_id: int) -> list[dict]:
    """List all reports for a schedule, sorted newest-first by mtime."""
    rd = reports_dir(schedule_id)

    if not rd.exists():
        return []

    reports = []
    for file_path in rd.iterdir():
        if file_path.is_file():
            stat = file_path.stat()
            reports.append({
                "name": file_path.name,
                "path": str(file_path.absolute()),
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })

    # Sort by mtime newest first
    reports.sort(key=lambda x: x["mtime"], reverse=True)
    return reports
