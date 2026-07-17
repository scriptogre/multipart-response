from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator, Sequence
from secrets import token_hex
from typing import Protocol, TypeAlias, runtime_checkable

TOKEN_CHARS = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&'*+-.^_`|~"
BOUNDARY_CHARS = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'()+_,-./:=? "
BOUNDARY_CHARS_NO_SPACE = BOUNDARY_CHARS.rstrip()
HEADER_VALUE_CHARS = b"\t" + bytes(range(32, 127))


class Multipart:
    """A multipart entity that can be rendered or nested inside another part."""

    def __init__(
        self,
        parts: PartSource,
        *,
        subtype: str = "mixed",
        boundary: bytes | str | None = None,
    ) -> None:
        writer = MultipartWriter(boundary)
        self.parts = parts
        self.subtype = subtype
        self.boundary = writer.boundary
        self.content_type = writer.content_type(subtype)

    @property
    def is_static(self) -> bool:
        """Return whether all parts and bodies are available without consuming a stream."""
        if not isinstance(self.parts, Sequence):
            return False
        return all(_coerce_part(part).is_static for part in self.parts)

    def iterate(self) -> Iterator[bytes | memoryview]:
        """Serialize a synchronous multipart entity."""
        if isinstance(self.parts, AsyncIterable):
            raise TypeError("Cannot synchronously serialize an asynchronous part source")

        parts = (_coerce_part(part) for part in self.parts)
        return MultipartWriter(self.boundary).iterate(parts)

    async def iterate_async(self) -> AsyncIterator[bytes | memoryview]:
        """Serialize a synchronous or asynchronous multipart entity."""
        source_parts = self.parts
        if isinstance(source_parts, AsyncIterable):

            async def parts() -> AsyncIterator[MultipartPart]:
                async for part in source_parts:
                    yield _coerce_part(part)

            source: Iterable[MultipartPart] | AsyncIterable[MultipartPart] = parts()
        else:
            source = (_coerce_part(part) for part in source_parts)

        async for chunk in MultipartWriter(self.boundary).iterate_async(source):
            yield chunk

    def render(self) -> bytes:
        """Buffer a synchronous multipart entity."""
        return b"".join(self.iterate())

    async def render_async(self) -> bytes:
        """Buffer a synchronous or asynchronous multipart entity."""
        body = bytearray()
        async for chunk in self.iterate_async():
            body.extend(chunk)
        return bytes(body)

    def as_multipart_part(self) -> MultipartPart:
        """Wrap this entity for nesting inside another multipart entity."""
        return MultipartPart(self)


class MultipartPart:
    """A body part with MIME headers and a static, streamed, or multipart body."""

    def __init__(
        self,
        body: BodySource = b"",
        headers: Iterable[tuple[bytes, bytes]] = (),
    ) -> None:
        if isinstance(body, bytearray):
            body = bytes(body)
        if isinstance(body, str) or not isinstance(
            body,
            bytes | memoryview | Multipart | Iterable | AsyncIterable,
        ):
            raise TypeError(
                f"MultipartPart body must be bytes-like or a body stream; got {type(body).__name__}"
            )

        raw_headers = tuple(headers)
        if isinstance(body, Multipart):
            expected = body.content_type.encode("ascii")
            content_types = [
                value for name, value in raw_headers if name.lower() == b"content-type"
            ]
            if content_types and content_types != [expected]:
                raise ValueError("Content-Type does not match nested multipart boundary")
            if not content_types:
                raw_headers += ((b"Content-Type", expected),)

        self.body = body
        self.headers = raw_headers

    @property
    def is_static(self) -> bool:
        """Return whether the body is static bytes or a static multipart entity."""
        if isinstance(self.body, bytes | memoryview):
            return True
        if isinstance(self.body, Multipart):
            return self.body.is_static
        return False


@runtime_checkable
class SupportsMultipartPart(Protocol):
    def as_multipart_part(self) -> MultipartPart: ...


BodyChunk: TypeAlias = bytes | bytearray | memoryview
BodySource: TypeAlias = BodyChunk | Iterable[BodyChunk] | AsyncIterable[BodyChunk] | Multipart
PartInput: TypeAlias = MultipartPart | Multipart | SupportsMultipartPart
PartSource: TypeAlias = Sequence[PartInput] | Iterable[PartInput] | AsyncIterable[PartInput]


def _coerce_part(part: PartInput) -> MultipartPart:
    if isinstance(part, MultipartPart):
        return part
    if isinstance(part, Multipart):
        return part.as_multipart_part()
    if isinstance(part, SupportsMultipartPart):
        converted = part.as_multipart_part()
        if isinstance(converted, MultipartPart):
            return converted

    raise TypeError(
        "Multipart items must be MultipartPart, Multipart, or implement "
        f"as_multipart_part(); got {type(part).__name__}"
    )


class MultipartWriter:
    """Serialize multipart messages one part at a time.

    The writer emits RFC 2046 framing and validates boundaries, MIME headers,
    and boundary collisions in body chunks.

    Args:
        boundary: The boundary without leading hyphens. A random boundary is
            generated when omitted.
    """

    def __init__(self, boundary: bytes | str | None = None) -> None:
        if boundary is None:
            boundary = f"multipart-{token_hex(16)}".encode("ascii")
        elif isinstance(boundary, str):
            try:
                boundary = boundary.encode("ascii")
            except UnicodeEncodeError:
                raise ValueError("Boundary must contain only ASCII characters") from None

        if not boundary:
            raise ValueError("Boundary must not be empty")
        if len(boundary) > 70:
            raise ValueError("Boundary must not exceed 70 bytes")
        if boundary[-1] not in BOUNDARY_CHARS_NO_SPACE or boundary.translate(None, BOUNDARY_CHARS):
            raise ValueError(f"Invalid boundary {boundary!r}")

        self.boundary = boundary
        self._delimiter = b"\r\n--" + boundary
        self._part_started = False
        self._body_tail = b""
        self._finalized = False

    def content_type(self, subtype: str = "mixed") -> str:
        """Return the multipart Content-Type value for this boundary."""
        try:
            subtype_bytes = subtype.encode("ascii")
        except UnicodeEncodeError:
            raise ValueError("Multipart subtype must contain only ASCII characters") from None

        if not subtype_bytes or subtype_bytes.translate(None, TOKEN_CHARS):
            raise ValueError(f"Invalid multipart subtype {subtype!r}")

        boundary = self.boundary.decode("ascii")
        if self.boundary.translate(None, TOKEN_CHARS):
            boundary = f'"{boundary}"'
        return f"multipart/{subtype}; boundary={boundary}"

    def start_part(self, headers: Iterable[tuple[bytes, bytes]] = ()) -> bytes:
        """Return the boundary and headers that begin the next part."""
        if self._finalized:
            raise RuntimeError("Cannot add a part after the writer is finalized")

        header_block = bytearray()
        for name, value in headers:
            if not name or name.translate(None, TOKEN_CHARS):
                raise ValueError(f"Invalid header name {name!r}")
            if value.translate(None, HEADER_VALUE_CHARS):
                raise ValueError(f"Invalid header value {value!r}")
            if len(name) + len(value) + 2 > 998:
                raise ValueError("Multipart header line must not exceed 998 bytes")
            if name.startswith(b"--" + self.boundary):
                raise ValueError("Multipart header contains the boundary")
            header_block.extend(name + b": " + value + b"\r\n")

        prefix = b"\r\n--" if self._part_started else b"--"
        self._part_started = True
        self._body_tail = b"\r\n"
        return prefix + self.boundary + b"\r\n" + bytes(header_block) + b"\r\n"

    def write_body(self, data: BodyChunk) -> bytes | memoryview:
        """Validate and return a chunk of the current part body."""
        if not self._part_started:
            raise RuntimeError("Cannot write a body before starting a part")
        if self._finalized:
            raise RuntimeError("Cannot write a body after the writer is finalized")

        if isinstance(data, bytearray):
            data = bytes(data)
        if not isinstance(data, bytes | memoryview):
            raise TypeError(f"Multipart body chunks must be bytes-like; got {type(data).__name__}")

        body = data if isinstance(data, bytes) else bytes(data)
        tail_size = len(self._delimiter) - 1
        if self._delimiter in body or self._delimiter in self._body_tail + body[:tail_size]:
            raise ValueError("Multipart body contains the boundary")

        if len(body) >= tail_size:
            self._body_tail = body[-tail_size:]
        else:
            self._body_tail = (self._body_tail + body)[-tail_size:]
        return data

    def finalize(self) -> bytes:
        """Return the closing boundary."""
        if self._finalized:
            raise RuntimeError("Multipart writer is already finalized")

        if not self._part_started:
            raise ValueError("Multipart messages must contain at least one part")

        self._finalized = True
        return self._delimiter + b"--\r\n"

    def iterate_part(self, part: PartInput) -> Iterator[bytes | memoryview]:
        """Serialize one synchronous part without closing the multipart entity."""
        serialized = _coerce_part(part)
        yield self.start_part(serialized.headers)

        body = serialized.body
        if isinstance(body, bytes | bytearray | memoryview):
            yield self.write_body(body)
        elif isinstance(body, Multipart):
            for nested_chunk in body.iterate():
                yield self.write_body(nested_chunk)
        elif isinstance(body, Iterable):
            for body_chunk in body:
                yield self.write_body(body_chunk)
        else:
            raise TypeError("Cannot synchronously serialize an asynchronous body")

    async def iterate_part_async(
        self,
        part: PartInput,
    ) -> AsyncIterator[bytes | memoryview]:
        """Serialize one synchronous or asynchronous part."""
        serialized = _coerce_part(part)
        yield self.start_part(serialized.headers)

        body = serialized.body
        if isinstance(body, bytes | bytearray | memoryview):
            yield self.write_body(body)
        elif isinstance(body, Multipart):
            async for nested_chunk in body.iterate_async():
                yield self.write_body(nested_chunk)
        elif isinstance(body, AsyncIterable):
            async for async_chunk in body:
                yield self.write_body(async_chunk)
        else:
            for sync_chunk in body:
                yield self.write_body(sync_chunk)

    def iterate(self, parts: Iterable[PartInput]) -> Iterator[bytes | memoryview]:
        """Serialize a synchronous iterable of parts."""
        for part in parts:
            yield from self.iterate_part(part)
        yield self.finalize()

    async def iterate_async(
        self,
        parts: Iterable[PartInput] | AsyncIterable[PartInput],
    ) -> AsyncIterator[bytes | memoryview]:
        """Serialize a synchronous or asynchronous iterable of parts."""
        if isinstance(parts, AsyncIterable):
            async for part in parts:
                async for chunk in self.iterate_part_async(part):
                    yield chunk
        else:
            for part in parts:
                async for chunk in self.iterate_part_async(part):
                    yield chunk
        yield self.finalize()

    def render(self, parts: Iterable[PartInput]) -> bytes:
        """Serialize all synchronous parts into one byte string."""
        return b"".join(self.iterate(parts))
