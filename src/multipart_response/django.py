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

from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse

from .core import Multipart, MultipartPart

PartChunk: TypeAlias = object
PartStreamSource: TypeAlias = Iterable[PartChunk] | AsyncIterable[PartChunk]


class _SyncPartStream:
    def __init__(
        self,
        source: Iterable[PartChunk],
        make_bytes: Callable[[object], bytes],
    ) -> None:
        self.source = source
        self.make_bytes = make_bytes

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self.source:
            yield self.make_bytes(chunk)


class _AsyncPartStream:
    def __init__(
        self,
        source: AsyncIterable[PartChunk],
        make_bytes: Callable[[object], bytes],
    ) -> None:
        self.source = source
        self.make_bytes = make_bytes

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self.source:
            yield self.make_bytes(chunk)


class Part:
    """A multipart body part using Django response conventions."""

    content_type: str | None = None

    def __init__(
        self,
        content: Any = b"",
        *,
        content_type: str | None = None,
        charset: str | None = None,
        headers: Mapping[str, object] | None = None,
    ) -> None:
        if isinstance(content, Multipart):
            expected = content.content_type
            if content_type is not None and content_type != expected:
                raise ValueError("Content-Type does not match nested multipart boundary")
            content_types = (
                [str(value) for name, value in headers.items() if name.lower() == "content-type"]
                if headers is not None
                else []
            )
            if content_types and content_types != [expected]:
                raise ValueError("Content-Type does not match nested multipart boundary")
            if content_type is None and not content_types:
                content_type = expected
        elif content_type is None:
            content_type = self.content_type

        response = HttpResponse(
            b"",
            content_type=content_type,
            charset=charset,
            headers=headers,
        )
        self._adopt_response(response)
        self.content = self.render(content)

    def _adopt_response(self, response: HttpResponse) -> None:
        self.headers = response.headers
        self.cookies = response.cookies
        self._charset = response.__dict__.get("_charset")

    charset = cast(Any, HttpResponse.charset)
    serialize_headers = cast(Any, HttpResponse.serialize_headers)
    __setitem__ = cast(Any, HttpResponse.__setitem__)
    __delitem__ = cast(Any, HttpResponse.__delitem__)
    __getitem__ = cast(Any, HttpResponse.__getitem__)
    __contains__ = cast(Any, HttpResponse.__contains__)
    has_header = cast(Any, HttpResponse.has_header)
    items = cast(Any, HttpResponse.items)
    get = cast(Any, HttpResponse.get)
    setdefault = cast(Any, HttpResponse.setdefault)
    set_cookie = cast(Any, HttpResponse.set_cookie)
    set_signed_cookie = cast(Any, HttpResponse.set_signed_cookie)
    delete_cookie = cast(Any, HttpResponse.delete_cookie)
    make_bytes = cast(Any, HttpResponse.make_bytes)

    def render(self, content: Any) -> bytes | _SyncPartStream | _AsyncPartStream | Multipart:
        if isinstance(content, Multipart):
            return content
        if isinstance(content, bytes | memoryview | str):
            return cast(bytes, self.make_bytes(content))

        try:
            source = iter(content)
        except TypeError:
            try:
                async_source = aiter(content)
            except TypeError:
                return cast(bytes, self.make_bytes(content))
            return _AsyncPartStream(async_source, self.make_bytes)
        return _SyncPartStream(source, self.make_bytes)

    def render_headers(self) -> bytes:
        """Render the part headers with CRLF line endings."""
        headers = cast(bytes, self.serialize_headers())
        cookies = b"\r\n".join(
            b"Set-Cookie: " + cookie.output(header="").strip().encode("ascii")
            for cookie in self.cookies.values()
        )
        if headers and cookies:
            headers += b"\r\n" + cookies
        elif cookies:
            headers = cookies
        return headers + (b"\r\n" if headers else b"")

    def as_multipart_part(self) -> MultipartPart:
        """Return the framework-neutral representation of this part."""
        raw_headers = [
            (name.encode("ascii"), value.encode("latin-1")) for name, value in self.items()
        ]
        raw_headers.extend(
            (
                b"Set-Cookie",
                cookie.output(header="").strip().encode("ascii"),
            )
            for cookie in self.cookies.values()
        )
        return MultipartPart(self.content, raw_headers)


class JsonPart(Part):
    def __init__(
        self,
        data: Any,
        encoder: type[json.JSONEncoder] = DjangoJSONEncoder,
        safe: bool = True,
        json_dumps_params: dict[str, Any] | None = None,
        *,
        content_type: str = "application/json",
        charset: str | None = None,
        headers: Mapping[str, object] | None = None,
    ) -> None:
        response = JsonResponse(
            data,
            encoder=encoder,
            safe=safe,
            json_dumps_params=json_dumps_params,
            content_type=content_type,
            charset=charset,
            headers=headers,
        )
        self._adopt_response(response)
        self.content = response.content


PartLike: TypeAlias = Part | MultipartPart | Multipart
PartSource: TypeAlias = Sequence[PartLike] | Iterable[PartLike] | AsyncIterable[PartLike]


def _part_is_async(part: MultipartPart) -> bool:
    body = part.body
    if isinstance(body, Multipart):
        return _multipart_is_async(body)
    return isinstance(body, AsyncIterable) and not isinstance(body, Iterable)


def _multipart_is_async(multipart: Multipart) -> bool:
    parts = multipart.parts
    if isinstance(parts, AsyncIterable) and not isinstance(parts, Iterable):
        return True
    if isinstance(parts, Sequence):
        for part in parts:
            if isinstance(part, MultipartPart):
                serialized = part
            elif isinstance(part, Multipart):
                serialized = part.as_multipart_part()
            else:
                serialized = part.as_multipart_part()
            if _part_is_async(serialized):
                return True
    return False


class MultipartResponse(StreamingHttpResponse):
    """A streaming multipart response for Django."""

    def __init__(
        self,
        content: PartSource,
        *,
        status: int | None = None,
        reason: str | None = None,
        charset: str | None = None,
        headers: Mapping[str, object] | None = None,
        subtype: str = "mixed",
        boundary: bytes | str | None = None,
    ) -> None:
        source_content = content
        source_is_async = False
        if isinstance(source_content, Sequence):
            serialized_parts = [self.make_part(part) for part in source_content]
            source: (
                Sequence[MultipartPart] | Iterable[MultipartPart] | AsyncIterable[MultipartPart]
            ) = serialized_parts
            source_is_async = any(_part_is_async(part) for part in serialized_parts)
        elif isinstance(source_content, AsyncIterable):

            async def async_parts() -> AsyncIterator[MultipartPart]:
                async for part in source_content:
                    yield self.make_part(part)

            source = async_parts()
            source_is_async = True
        else:

            def sync_parts() -> Iterator[MultipartPart]:
                for part in source_content:
                    yield self.make_part(part)

            source = sync_parts()

        multipart = Multipart(source, subtype=subtype, boundary=boundary)
        self.multipart = multipart
        self.boundary = multipart.boundary.decode("ascii")

        body: bytes | None = None
        if multipart.is_static:
            body = multipart.render()
            streaming_content: Iterable[bytes | memoryview] | AsyncIterable[bytes | memoryview] = [
                body
            ]
        elif source_is_async:
            streaming_content = multipart.iterate_async()
        else:
            streaming_content = multipart.iterate()

        super().__init__(
            streaming_content,
            status=status,
            reason=reason,
            charset=charset,
            headers=headers,
            content_type=multipart.content_type,
        )

        if body is not None:
            self.headers.setdefault("Content-Length", len(body))

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


__all__ = [
    "JsonPart",
    "Multipart",
    "MultipartResponse",
    "Part",
]
