from __future__ import annotations

from collections.abc import AsyncIterable, Iterable, Mapping, Sequence
from typing import Any, Protocol, TypeAlias, cast

from fastcore.xml import FT, to_xml  # type: ignore[import-untyped]
from fasthtml.core import JSONResponse as FastHTMLJSONResponse  # type: ignore[import-untyped]
from starlette.background import BackgroundTask

from .core import Multipart, MultipartPart
from .starlette import (
    HTMLMultipartResponse as StarletteHTMLMultipartResponse,
    HTMLPartSource as StarletteHTMLPartSource,
    Part as StarlettePart,
    PartStreamSource,
)


class SupportsFT(Protocol):
    def __ft__(self) -> Any: ...


PartLike: TypeAlias = StarlettePart | MultipartPart | Multipart | str | SupportsFT
PartSource: TypeAlias = Sequence[PartLike] | Iterable[PartLike] | AsyncIterable[PartLike]


def _is_fasthtml_content(content: object) -> bool:
    return isinstance(content, FT) or hasattr(content, "__ft__")


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


class JSONPart(Part):
    """A JSON part using FastHTML serialization."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return cast(bytes, FastHTMLJSONResponse(content).body)


class MultipartResponse(StarletteHTMLMultipartResponse):
    """A multipart response that renders implicit FastHTML components as HTML."""

    def __init__(
        self,
        content: PartSource,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        subtype: str = "mixed",
        background: BackgroundTask | None = None,
        boundary: bytes | str | None = None,
    ) -> None:
        super().__init__(
            content=cast(StarletteHTMLPartSource, content),
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
            raise TypeError("Use Part(content, headers=...) to set FastHTML part headers")
        return super().make_part(content)


__all__ = [
    "JSONPart",
    "Multipart",
    "MultipartResponse",
    "Part",
]
