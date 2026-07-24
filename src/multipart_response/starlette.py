from __future__ import annotations

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
from starlette.concurrency import iterate_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.responses import Response, StreamingResponse

from .core import Multipart, MultipartPart

PartChunk: TypeAlias = str | bytes | bytearray | memoryview
PartStreamSource: TypeAlias = Iterable[PartChunk] | AsyncIterable[PartChunk]


class _PartStream:
    def __init__(
        self,
        source: PartStreamSource,
        render_chunk: Callable[[PartChunk], bytes | memoryview],
    ) -> None:
        self.source = source
        self.render_chunk = render_chunk

    def __iter__(self) -> Iterator[bytes | memoryview]:
        if isinstance(self.source, AsyncIterable):
            raise TypeError("Cannot synchronously serialize an asynchronous body")

        for chunk in self.source:
            yield self.render_chunk(chunk)

    async def __aiter__(self) -> AsyncIterator[bytes | memoryview]:
        source = self.source
        if isinstance(source, AsyncIterable):
            async for chunk in source:
                yield self.render_chunk(chunk)
        else:
            async for chunk in iterate_in_threadpool(source):
                yield self.render_chunk(chunk)


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
        if isinstance(content, Multipart):
            expected = content.content_type
            if media_type is not None and media_type != expected:
                raise ValueError("Content-Type does not match nested multipart boundary")
            if headers is not None:
                content_types = [
                    value for name, value in headers.items() if name.lower() == "content-type"
                ]
                if content_types and content_types != [expected]:
                    raise ValueError("Content-Type does not match nested multipart boundary")
            self.media_type = expected
        elif media_type is not None:
            self.media_type = media_type

        self.body = self.render(content)
        self.init_headers(headers)

    def render(
        self,
        content: Any,
    ) -> bytes | memoryview | PartStreamSource | Multipart:
        if content is None:
            return b""
        if isinstance(content, Multipart):
            return content.render() if content.is_static else content
        if isinstance(content, bytes | memoryview):
            return content
        if isinstance(content, bytearray):
            return bytes(content)
        if isinstance(content, AsyncIterable):
            return content
        if isinstance(content, Iterable) and not isinstance(content, Mapping | str):
            return content
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

        if populate_content_length and isinstance(self.body, bytes | memoryview):
            length = self.body.nbytes if isinstance(self.body, memoryview) else len(self.body)
            raw_headers.append((b"content-length", str(length).encode("latin-1")))

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

    def render_chunk(self, chunk: PartChunk) -> bytes | memoryview:
        """Render one streamed body chunk."""
        if isinstance(chunk, str):
            return chunk.encode(self.charset)
        if isinstance(chunk, bytearray):
            return bytes(chunk)
        if isinstance(chunk, bytes | memoryview):
            return chunk
        raise TypeError(f"Part stream chunks must be str or bytes-like; got {type(chunk).__name__}")

    def as_multipart_part(self) -> MultipartPart:
        """Return the framework-neutral representation of this part."""
        body = self.body
        if isinstance(body, Iterable | AsyncIterable) and not isinstance(
            body,
            bytes | memoryview | Multipart,
        ):
            body = _PartStream(body, self.render_chunk)
        return MultipartPart(body, self.raw_headers)


PartLike: TypeAlias = Part | MultipartPart | Multipart
PartSource: TypeAlias = Sequence[PartLike] | Iterable[PartLike] | AsyncIterable[PartLike]
HTMLPartLike: TypeAlias = PartLike | str | tuple[str, Mapping[str, str]]
HTMLPartSource: TypeAlias = (
    Sequence[HTMLPartLike] | Iterable[HTMLPartLike] | AsyncIterable[HTMLPartLike]
)
HTMLResponseContent: TypeAlias = HTMLPartSource | str | tuple[str, Mapping[str, str]]


def _is_html_header_pair(content: object) -> bool:
    return (
        isinstance(content, tuple)
        and len(content) == 2
        and isinstance(content[0], str)
        and isinstance(content[1], Mapping)
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
        source_content = content
        if isinstance(source_content, Sequence):
            source: Sequence[MultipartPart] | AsyncIterable[MultipartPart] = [
                self.make_part(part) for part in source_content
            ]
        elif isinstance(source_content, AsyncIterable):

            async def async_parts() -> AsyncIterator[MultipartPart]:
                async for part in source_content:
                    yield self.make_part(part)

            source = async_parts()
        else:

            async def threaded_parts() -> AsyncIterator[MultipartPart]:
                async for part in iterate_in_threadpool(source_content):
                    yield self.make_part(part)

            source = threaded_parts()

        multipart = Multipart(source, subtype=subtype, boundary=boundary)
        self.multipart = multipart
        self.boundary = multipart.boundary.decode("ascii")

        if multipart.is_static:
            self.body = multipart.render()
            body_iterator: Iterable[bytes | memoryview] | AsyncIterable[bytes | memoryview] = [
                self.body
            ]
        else:
            body_iterator = multipart.iterate_async()

        super().__init__(
            content=body_iterator,
            status_code=status_code,
            headers=headers,
            media_type=multipart.content_type,
            background=background,
        )

    def make_part(self, content: PartLike) -> MultipartPart:
        """Return the serialized form of an explicit part."""
        if isinstance(content, MultipartPart):
            return content
        if isinstance(content, Multipart):
            return Part(content).as_multipart_part()
        if isinstance(content, Part):
            return content.as_multipart_part()

        raise TypeError(
            "MultipartResponse items must be Part, MultipartPart, or Multipart; "
            f"got {type(content).__name__}"
        )


class HTMLMultipartResponse(MultipartResponse):
    """A multipart response that converts implicit string parts to HTML."""

    def __init__(
        self,
        content: HTMLResponseContent,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        subtype: str = "mixed",
        background: BackgroundTask | None = None,
        boundary: bytes | str | None = None,
    ) -> None:
        if isinstance(content, str) or _is_html_header_pair(content):
            content = [cast(HTMLPartLike, content)]

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
            return Part(content, media_type="text/html").as_multipart_part()

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
            return Part(body, headers=headers, media_type="text/html").as_multipart_part()

        if isinstance(content, Part | MultipartPart | Multipart):
            return super().make_part(content)

        raise TypeError(
            "HTMLMultipartResponse items must be str, (str, headers), Part, "
            f"MultipartPart, or Multipart; got {type(content).__name__}"
        )


__all__ = [
    "HTMLMultipartResponse",
    "Multipart",
    "MultipartResponse",
    "Part",
]
