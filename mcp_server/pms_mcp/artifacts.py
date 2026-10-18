"""Generated files (charts, spreadsheets, decks, reports) on a directory shared with the agent,
which serves them for download. Files expire after 24 hours."""

import json
import re
import secrets
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

FILE_ID = re.compile(r"^[0-9a-f]{32}$")
TTL_SECONDS = 24 * 3600

MIME_TYPES = {
    "png": "image/png",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


@dataclass
class FileInfo:
    file_id: str
    filename: str
    mime: str
    size: int


def safe_filename(name: str, ext: str) -> str:
    """ASCII, filesystem- and header-safe file name with the given extension."""
    stem = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9 ._-]+", "", stem).strip(" .") or "report"
    stem = re.sub(r"\s+", " ", stem)[:80]
    if stem.lower().endswith("." + ext):
        stem = stem[: -len(ext) - 1]
    return f"{stem}.{ext}"


class ArtifactStore:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, name: str, ext: str) -> FileInfo:
        self._expire()
        info = FileInfo(secrets.token_hex(16), safe_filename(name, ext), MIME_TYPES[ext], len(data))
        (self.dir / info.file_id).write_bytes(data)
        (self.dir / f"{info.file_id}.json").write_text(json.dumps({**asdict(info), "created": time.time()}))
        return info

    def read(self, file_id: str) -> bytes:
        if not FILE_ID.match(file_id) or not (self.dir / file_id).is_file():
            raise KeyError(file_id)
        return (self.dir / file_id).read_bytes()

    def info(self, file_id: str) -> FileInfo:
        if not FILE_ID.match(file_id) or not (self.dir / f"{file_id}.json").is_file():
            raise KeyError(file_id)
        meta = json.loads((self.dir / f"{file_id}.json").read_text())
        return FileInfo(meta["file_id"], meta["filename"], meta["mime"], meta["size"])

    def _expire(self) -> None:
        cutoff = time.time() - TTL_SECONDS
        for meta in self.dir.glob("*.json"):
            try:
                if json.loads(meta.read_text())["created"] < cutoff:
                    (self.dir / meta.stem).unlink(missing_ok=True)
                    meta.unlink(missing_ok=True)
            except (OSError, ValueError, KeyError):
                continue
