from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from secrets import token_hex

TOKEN_CHARS = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$%&'*+-.^_`|~"
BOUNDARY_CHARS = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'()+_,-./:=? "
BOUNDARY_CHARS_NO_SPACE = BOUNDARY_CHARS.rstrip()
HEADER_VALUE_CHARS = b"\t" + bytes(range(32, 127))


class MultipartPart:
    """A serialized body part with its MIME headers."""

    def __init__(
        self,
        body: bytes | bytearray | memoryview = b"",
        headers: Iterable[tuple[bytes, bytes]] = (),
    ) -> None:
        if isinstance(body, bytearray):
            body = bytes(body)
        if not isinstance(body, bytes | memoryview):
            raise TypeError(f"MultipartPart body must be bytes-like; got {type(body).__name__}")

        self.body = body
        self.headers = tuple(headers)


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

    def write_body(self, data: bytes | bytearray | memoryview) -> bytes | memoryview:
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

    def iterate(self, parts: Iterable[MultipartPart]) -> Iterator[bytes | memoryview]:
        """Serialize a synchronous iterable of parts."""
        for part in parts:
            yield self.start_part(part.headers)
            yield self.write_body(part.body)
        yield self.finalize()

    async def iterate_async(
        self,
        parts: AsyncIterable[MultipartPart],
    ) -> AsyncIterator[bytes | memoryview]:
        """Serialize an asynchronous iterable of parts."""
        async for part in parts:
            yield self.start_part(part.headers)
            yield self.write_body(part.body)
        yield self.finalize()

    def render(self, parts: Iterable[MultipartPart]) -> bytes:
        """Serialize all parts into one byte string."""
        return b"".join(self.iterate(parts))
