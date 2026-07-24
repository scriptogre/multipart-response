from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastcore.xml import FT, to_xml  # type: ignore[import-untyped]
from starlette.background import BackgroundTask

from .core import Multipart, MultipartPart
from .starlette import (
    HTMLMultipartResponse as StarletteHTMLMultipartResponse,
    MultipartResponse as StarletteMultipartResponse,
    Part as StarlettePart,
    PartStreamSource,
)


def _is_fasthtml_content(content: object) -> bool:
    return isinstance(content, FT) or hasattr(content, "__ft__")


def _is_header_pair(content: object) -> bool:
    return (
        isinstance(content, tuple)
        and len(content) == 2
        and (_is_fasthtml_content(content[0]) or isinstance(content[0], str))
        and isinstance(content[1], Mapping)
    )


class Part(StarlettePart):
    """An HTML part that renders FastHTML components."""

    media_type = "text/html"

    def render(
        self,
        content: Any,
    ) -> bytes | memoryview | PartStreamSource | Multipart:
        if _is_fasthtml_content(content):
            content = to_xml(content)
        return super().render(content)


class MultipartResponse(StarletteMultipartResponse):
    """A streaming multipart response for FastHTML."""


class HTMLMultipartResponse(StarletteHTMLMultipartResponse):
    """A multipart response that converts implicit FastHTML components to HTML parts."""

    def __init__(
        self,
        content: Any,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        subtype: str = "mixed",
        background: BackgroundTask | None = None,
        boundary: bytes | str | None = None,
    ) -> None:
        if _is_fasthtml_content(content) or isinstance(content, str) or _is_header_pair(content):
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
        """Convert a FastHTML component or return another supported part."""
        if _is_fasthtml_content(content):
            return Part(content).as_multipart_part()
        if isinstance(content, tuple):
            if not _is_header_pair(content):
                raise TypeError(
                    "HTMLMultipartResponse tuple items must contain HTML content and headers"
                )
            body, headers = content
            if not all(
                isinstance(name, str) and isinstance(value, str) for name, value in headers.items()
            ):
                raise TypeError("HTMLMultipartResponse headers must map strings to strings")
            return Part(body, headers=headers).as_multipart_part()
        return super().make_part(content)


__all__ = [
    "HTMLMultipartResponse",
    "Multipart",
    "MultipartResponse",
    "Part",
]
