from __future__ import annotations

from collections.abc import AsyncIterable, Iterable, Mapping
from typing import Any, cast

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse

from .core import Multipart, MultipartPart
from .starlette import HTMLMultipartResponse, MultipartResponse, Part


def _is_header_pair(content: object) -> bool:
    return isinstance(content, tuple) and len(content) == 2 and isinstance(content[1], Mapping)


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
        if (
            isinstance(content, Mapping | BaseModel | str | bytes)
            or _is_header_pair(content)
            or not isinstance(content, Iterable | AsyncIterable)
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

        headers = None
        if _is_header_pair(content):
            content, headers = content
            if not all(
                isinstance(name, str) and isinstance(value, str) for name, value in headers.items()
            ):
                raise TypeError("JSONMultipartResponse headers must map strings to strings")
            headers = cast(Mapping[str, str], headers)

        body = cast(bytes, JSONResponse(jsonable_encoder(content)).body)
        return Part(body, headers=headers, media_type="application/json").as_multipart_part()


__all__ = [
    "HTMLMultipartResponse",
    "JSONMultipartResponse",
    "Multipart",
    "MultipartResponse",
    "Part",
]
