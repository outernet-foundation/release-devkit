from __future__ import annotations

from pydantic import BaseModel

DIGEST_PROJECT = "images-digests"
DIGEST_PLATFORM = "all"
DIGEST_FILE_NAME = "images-digests.json"


class DigestEntry(BaseModel):
    ref: str
    digest: str
    tags: list[str]
