from __future__ import annotations

from collections.abc import AsyncIterable, Iterable, Mapping
from typing import Any, cast

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse

from .core import Multipart, MultipartPart
from .starlette import HTMLMultipartResponse, MultipartResponse, Part


class JSONMultipartResponse(MultipartResponse):
    """A multipart response that converts implicit values to JSON parts."""

    def __init__(
        self,
        content: Any,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        subtype: str = "mixed",
        background: BackgroundTask | None = None,
        boundary: bytes | str | None = None,
    ) -> None:
        if isinstance(content, Mapping | BaseModel | str | bytes) or not isinstance(
            content,
            Iterable | AsyncIterable,
        ):
            content = [content]

        super().__init__(
            content=content,
            status_code=status_code,
            headers=headers,
            subtype=subtype,
            background=background,
            boundary=boundary,
        )

    def make_part(self, content: Any) -> MultipartPart:
        """Convert an implicit value to JSON or return an explicit part."""
        if isinstance(content, Part | MultipartPart | Multipart):
            return super().make_part(content)
        body = cast(bytes, JSONResponse(jsonable_encoder(content)).body)
        return Part(body, media_type="application/json").as_multipart_part()


__all__ = [
    "HTMLMultipartResponse",
    "JSONMultipartResponse",
    "Multipart",
    "MultipartResponse",
    "Part",
]
