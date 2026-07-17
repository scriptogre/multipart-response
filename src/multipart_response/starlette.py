from __future__ import annotations

import json
from collections.abc import (
    AsyncIterable,
    AsyncIterator,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from typing import Any, TypeAlias, cast

from starlette.background import BackgroundTask
from starlette.datastructures import MutableHeaders
from starlette.responses import Response, StreamingResponse

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
        if headers is None:
            raw_headers: list[tuple[bytes, bytes]] = []
            populate_content_length = True
            populate_content_type = True
        else:
            raw_headers = [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in headers.items()
            ]
            keys = [name for name, _ in raw_headers]
            populate_content_length = b"content-length" not in keys
            populate_content_type = b"content-type" not in keys

        if populate_content_length:
            raw_headers.append((b"content-length", str(len(self.body)).encode("latin-1")))

        if self.media_type is not None and populate_content_type:
            content_type = self.media_type
            if content_type.startswith("text/") and "charset=" not in content_type.lower():
                content_type += "; charset=" + self.charset
            raw_headers.append((b"content-type", content_type.encode("latin-1")))

        self.raw_headers = raw_headers

    headers = cast(MutableHeaders, Response.headers)
    set_cookie = cast(Callable[..., None], Response.set_cookie)
    delete_cookie = cast(Callable[..., None], Response.delete_cookie)

    def render_headers(self) -> bytes:
        """Render the part headers with CRLF line endings."""
        return b"".join(name + b": " + value + b"\r\n" for name, value in self.raw_headers)

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


PartLike: TypeAlias = Part | MultipartPart
PartSource: TypeAlias = Sequence[PartLike] | Iterable[PartLike] | AsyncIterable[PartLike]
HTMLPartLike: TypeAlias = PartLike | str | tuple[str, Mapping[str, str]]
HTMLPartSource: TypeAlias = (
    Sequence[HTMLPartLike] | Iterable[HTMLPartLike] | AsyncIterable[HTMLPartLike]
)


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
        """Return the serialized form of an explicit part."""
        if isinstance(content, MultipartPart):
            return content
        if isinstance(content, Part):
            return content.as_multipart_part()

        raise TypeError(
            f"MultipartResponse items must be Part or MultipartPart; got {type(content).__name__}"
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


class HTMLMultipartResponse(MultipartResponse):
    """A multipart response that converts implicit string parts to HTML."""

    def __init__(
        self,
        content: HTMLPartSource,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        subtype: str = "mixed",
        background: BackgroundTask | None = None,
        boundary: bytes | str | None = None,
    ) -> None:
        super().__init__(
            content=cast(PartSource, content),
            status_code=status_code,
            headers=headers,
            subtype=subtype,
            background=background,
            boundary=boundary,
        )

    def make_part(self, content: HTMLPartLike) -> MultipartPart:
        """Convert an HTML string shorthand or return an explicit part."""
        if isinstance(content, str):
            return HTMLPart(content).as_multipart_part()

        if isinstance(content, tuple):
            if (
                len(content) != 2
                or not isinstance(content[0], str)
                or not isinstance(content[1], Mapping)
            ):
                raise TypeError(
                    "HTMLMultipartResponse tuple items must contain an HTML string and headers"
                )

            body, headers = content
            if not all(
                isinstance(name, str) and isinstance(value, str) for name, value in headers.items()
            ):
                raise TypeError("HTMLMultipartResponse headers must map strings to strings")
            return HTMLPart(body, headers=headers).as_multipart_part()

        if isinstance(content, Part | MultipartPart):
            return super().make_part(content)

        raise TypeError(
            "HTMLMultipartResponse items must be str, (str, headers), Part, or MultipartPart; "
            f"got {type(content).__name__}"
        )


__all__ = [
    "HTMLMultipartResponse",
    "HTMLPart",
    "JSONPart",
    "MultipartResponse",
    "Part",
    "TextPart",
]
