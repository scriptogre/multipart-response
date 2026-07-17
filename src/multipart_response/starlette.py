from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator, Mapping, Sequence
from typing import Any, TypeAlias

from starlette.background import BackgroundTask
from starlette.datastructures import MutableHeaders
from starlette.responses import StreamingResponse

from .core import MultipartPart, MultipartWriter


class Part:
    """A multipart body part using Starlette response conventions."""

    media_type: str | None = None
    charset = "utf-8"

    def __init__(
        self,
        content: Any = None,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
    ) -> None:
        if media_type is not None:
            self.media_type = media_type

        self.body = self.render(content)
        self.init_headers(headers)

    def render(self, content: Any) -> bytes | memoryview:
        if content is None:
            return b""
        if isinstance(content, bytes | memoryview):
            return content
        if isinstance(content, bytearray):
            return bytes(content)
        body: bytes = content.encode(self.charset)
        return body

    def init_headers(self, headers: Mapping[str, str] | None = None) -> None:
        raw_headers = (
            []
            if headers is None
            else [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in headers.items()
            ]
        )

        if self.media_type is not None and b"content-type" not in {name for name, _ in raw_headers}:
            content_type = self.media_type
            if content_type.startswith("text/") and "charset=" not in content_type.lower():
                content_type += "; charset=" + self.charset
            raw_headers.append((b"content-type", content_type.encode("latin-1")))

        self.raw_headers: list[tuple[bytes, bytes]] = raw_headers

    @property
    def headers(self) -> MutableHeaders:
        if not hasattr(self, "_headers"):
            self._headers = MutableHeaders(raw=self.raw_headers)
        return self._headers

    def as_multipart_part(self) -> MultipartPart:
        """Return the framework-neutral representation of this part."""
        return MultipartPart(self.body, self.raw_headers)


class TextPart(Part):
    media_type = "text/plain"


class HTMLPart(Part):
    media_type = "text/html"


class JSONPart(Part):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


PartLike: TypeAlias = Part | MultipartPart | str | bytes | bytearray | memoryview | dict[str, Any]
PartSource: TypeAlias = Sequence[PartLike] | Iterable[PartLike] | AsyncIterable[PartLike]


class MultipartResponse(StreamingResponse):
    """A streaming multipart response for Starlette."""

    media_type = "multipart/mixed"

    def __init__(
        self,
        content: PartSource,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        subtype: str = "mixed",
        background: BackgroundTask | None = None,
        boundary: bytes | str | None = None,
    ) -> None:
        writer = MultipartWriter(boundary)
        self.boundary = writer.boundary.decode("ascii")

        if isinstance(content, Sequence):
            self.body = b"".join(self.iterate(content, writer))
            body_iterator: Iterable[bytes] | AsyncIterable[bytes] = [self.body]
        elif isinstance(content, AsyncIterable):
            body_iterator = self.iterate_async(content, writer)
        else:
            body_iterator = self.iterate(content, writer)

        super().__init__(
            content=body_iterator,
            status_code=status_code,
            headers=headers,
            media_type=writer.content_type(subtype),
            background=background,
        )

    def make_part(self, content: PartLike) -> MultipartPart:
        """Convert Starlette-friendly values into a serialized part."""
        if isinstance(content, MultipartPart):
            return content
        if isinstance(content, Part):
            return content.as_multipart_part()
        if isinstance(content, str):
            return TextPart(content).as_multipart_part()
        if isinstance(content, dict):
            return JSONPart(content).as_multipart_part()
        if isinstance(content, bytes | bytearray | memoryview):
            return Part(content, media_type="application/octet-stream").as_multipart_part()

        raise TypeError(
            "MultipartResponse items must be Part, MultipartPart, str, dict, or bytes-like; "
            f"got {type(content).__name__}"
        )

    def iterate(
        self,
        content: Iterable[PartLike],
        writer: MultipartWriter,
    ) -> Iterator[bytes]:
        """Serialize a synchronous source."""
        for item in content:
            part = self.make_part(item)
            yield writer.start_part(part.headers)
            yield bytes(writer.write_body(part.body))
        yield writer.finalize()

    async def iterate_async(
        self,
        content: AsyncIterable[PartLike],
        writer: MultipartWriter,
    ) -> AsyncIterator[bytes]:
        """Serialize an asynchronous source."""
        async for item in content:
            part = self.make_part(item)
            yield writer.start_part(part.headers)
            yield bytes(writer.write_body(part.body))
        yield writer.finalize()


__all__ = [
    "HTMLPart",
    "JSONPart",
    "MultipartResponse",
    "Part",
    "TextPart",
]
