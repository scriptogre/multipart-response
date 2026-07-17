from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from conftest import ParsedPart, parse_multipart

from multipart_response import Multipart, MultipartPart, MultipartWriter


def test_render_exact_multipart_body() -> None:
    writer = MultipartWriter("boundary")

    body = writer.render(
        [
            MultipartPart(b"hello", [(b"Content-Type", b"text/plain")]),
            MultipartPart(
                memoryview(b'{"ok":true}'),
                [
                    (b"Content-Type", b"application/json"),
                    (b"Content-ID", b"<metadata>"),
                ],
            ),
        ]
    )

    assert body == (
        b"--boundary\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"hello\r\n"
        b"--boundary\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-ID: <metadata>\r\n"
        b"\r\n"
        b'{"ok":true}\r\n'
        b"--boundary--\r\n"
    )


@pytest.mark.parametrize("chunk_size", [None, 1, 2, 7, 64])
def test_writer_round_trips_through_python_multipart(chunk_size: int | None) -> None:
    writer = MultipartWriter("round-trip")
    body = writer.render(
        [
            MultipartPart(
                b"first\x00body",
                [
                    (b"X-Repeated", b"one"),
                    (b"X-Repeated", b"two"),
                ],
            ),
            MultipartPart(bytearray(b"second body")),
        ]
    )

    assert parse_multipart(body, writer.boundary, chunk_size=chunk_size) == [
        ParsedPart(
            [(b"X-Repeated", b"one"), (b"X-Repeated", b"two")],
            b"first\x00body",
        ),
        ParsedPart([], b"second body"),
    ]


def test_empty_multipart_body_is_rejected() -> None:
    writer = MultipartWriter("empty")

    with pytest.raises(ValueError, match="at least one part"):
        writer.render([])


def test_generated_boundary_is_valid_and_random() -> None:
    first = MultipartWriter()
    second = MultipartWriter()

    assert first.boundary.startswith(b"multipart-")
    assert len(first.boundary) == 42
    assert first.boundary != second.boundary
    assert first.content_type() == f"multipart/mixed; boundary={first.boundary.decode('ascii')}"


def test_content_type_quotes_boundary_when_required() -> None:
    writer = MultipartWriter("contains:colon")

    assert writer.content_type("alternative") == (
        'multipart/alternative; boundary="contains:colon"'
    )


@pytest.mark.parametrize("boundary", [b"", b"a" * 71, b"trailing ", b'bad"quote'])
def test_invalid_boundary(boundary: bytes) -> None:
    with pytest.raises(ValueError):
        MultipartWriter(boundary)


def test_non_ascii_boundary() -> None:
    with pytest.raises(ValueError, match="only ASCII"):
        MultipartWriter("böundary")


@pytest.mark.parametrize("subtype", ["", "mixed response", "mixed/other"])
def test_invalid_subtype(subtype: str) -> None:
    with pytest.raises(ValueError, match="Invalid multipart subtype"):
        MultipartWriter("boundary").content_type(subtype)


def test_non_ascii_subtype() -> None:
    with pytest.raises(ValueError, match="only ASCII"):
        MultipartWriter("boundary").content_type("mïxed")


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ([(b"", b"value")], "Invalid header name"),
        ([(b"bad name", b"value")], "Invalid header name"),
        ([(b"X-Test", b"bad\nvalue")], "Invalid header value"),
        ([(b"X-Test", b"\x80")], "Invalid header value"),
        ([(b"X-Test", b"x" * 991)], "must not exceed 998 bytes"),
        ([(b"--boundary-header", b"value")], "contains the boundary"),
    ],
)
def test_invalid_part_headers(
    headers: list[tuple[bytes, bytes]],
    message: str,
) -> None:
    writer = MultipartWriter("boundary")

    with pytest.raises(ValueError, match=message):
        writer.start_part(headers)


def test_body_chunks_preserve_bytes_like_types() -> None:
    writer = MultipartWriter("boundary")
    writer.start_part()

    bytearray_chunk = writer.write_body(bytearray(b"one"))
    memoryview_chunk = writer.write_body(memoryview(b"two"))

    assert bytearray_chunk == b"one"
    assert isinstance(bytearray_chunk, bytes)
    assert bytes(memoryview_chunk) == b"two"
    assert isinstance(memoryview_chunk, memoryview)


def test_invalid_part_and_body_types() -> None:
    with pytest.raises(TypeError, match="MultipartPart body must be bytes-like"):
        MultipartPart("body")  # type: ignore[arg-type]

    writer = MultipartWriter("boundary")
    writer.start_part()
    with pytest.raises(TypeError, match="body chunks must be bytes-like"):
        writer.write_body("body")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "chunks",
    [
        [b"--boundary"],
        [b"before\r\n--boundary"],
        [b"before\r\n--bound", b"ary"],
    ],
)
def test_boundary_collision_is_rejected(chunks: list[bytes]) -> None:
    writer = MultipartWriter("boundary")
    writer.start_part()

    with pytest.raises(ValueError, match="body contains the boundary"):
        for chunk in chunks:
            writer.write_body(chunk)


def test_writer_state_errors() -> None:
    writer = MultipartWriter("boundary")

    with pytest.raises(RuntimeError, match="before starting a part"):
        writer.write_body(b"body")

    writer.start_part()
    writer.write_body(b"body")
    writer.finalize()

    with pytest.raises(RuntimeError, match="after the writer is finalized"):
        writer.start_part()
    with pytest.raises(RuntimeError, match="after the writer is finalized"):
        writer.write_body(b"body")
    with pytest.raises(RuntimeError, match="already finalized"):
        writer.finalize()


def test_iterate_serializes_parts() -> None:
    writer = MultipartWriter("sync")

    chunks = list(writer.iterate([MultipartPart(b"body")]))

    assert b"".join(chunks) == b"--sync\r\n\r\nbody\r\n--sync--\r\n"


def test_iterate_async_serializes_parts() -> None:
    async def parts() -> AsyncIterator[MultipartPart]:
        yield MultipartPart(b"one")
        yield MultipartPart(b"two")

    async def collect() -> bytes:
        writer = MultipartWriter("async")
        return b"".join([bytes(chunk) async for chunk in writer.iterate_async(parts())])

    assert asyncio.run(collect()) == (b"--async\r\n\r\none\r\n--async\r\n\r\ntwo\r\n--async--\r\n")


def test_sync_part_body_streams_chunks() -> None:
    def body() -> Iterator[bytes | memoryview]:
        yield b"one"
        yield memoryview(b"two")

    multipart = Multipart(
        [MultipartPart(body(), [(b"Content-Type", b"application/octet-stream")])],
        boundary="stream",
    )

    assert b"".join(multipart.iterate()) == (
        b"--stream\r\nContent-Type: application/octet-stream\r\n\r\nonetwo\r\n--stream--\r\n"
    )
    assert not multipart.is_static


def test_async_part_body_streams_chunks() -> None:
    async def body() -> AsyncIterator[bytes | bytearray]:
        yield b"one"
        yield bytearray(b"two")

    multipart = Multipart([MultipartPart(body())], boundary="async-body")

    assert asyncio.run(multipart.render_async()) == (
        b"--async-body\r\n\r\nonetwo\r\n--async-body--\r\n"
    )
    assert not multipart.is_static


def test_async_serializer_accepts_sync_and_async_sources_at_every_level() -> None:
    def sync_body() -> Iterator[bytes]:
        yield b"sync"

    async def async_body() -> AsyncIterator[bytes]:
        yield b"async"

    async def parts() -> AsyncIterator[MultipartPart]:
        yield MultipartPart(sync_body())
        yield MultipartPart(async_body())

    multipart = Multipart(parts(), boundary="mixed-streams")

    assert not multipart.is_static
    assert asyncio.run(multipart.render_async()) == (
        b"--mixed-streams\r\n\r\nsync\r\n--mixed-streams\r\n\r\nasync\r\n--mixed-streams--\r\n"
    )


def test_sync_serializer_rejects_async_sources() -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"body"

    with pytest.raises(TypeError, match="asynchronous body"):
        Multipart([MultipartPart(body())], boundary="sync-only").render()

    async def parts() -> AsyncIterator[MultipartPart]:
        yield MultipartPart(b"body")

    with pytest.raises(TypeError, match="asynchronous part source"):
        Multipart(parts(), boundary="sync-only").render()


def test_invalid_stream_chunks_are_rejected() -> None:
    multipart = Multipart(
        [MultipartPart([b"valid", "invalid"])],  # type: ignore[list-item]
        boundary="invalid-sync",
    )

    with pytest.raises(TypeError, match="body chunks must be bytes-like; got str"):
        multipart.render()

    async def body() -> AsyncIterator[bytes]:
        yield "invalid"  # type: ignore[misc]

    with pytest.raises(TypeError, match="body chunks must be bytes-like; got str"):
        asyncio.run(Multipart([MultipartPart(body())], boundary="invalid-async").render_async())


def test_multipart_entity_exposes_framing_values() -> None:
    parts = [MultipartPart(b"body")]
    multipart = Multipart(
        parts,
        subtype="alternative",
        boundary="inner:boundary",
    )

    assert multipart.parts is parts
    assert multipart.subtype == "alternative"
    assert multipart.boundary == b"inner:boundary"
    assert multipart.content_type == ('multipart/alternative; boundary="inner:boundary"')


def test_static_multipart_entity_renders_and_converts_to_part() -> None:
    multipart = Multipart(
        [MultipartPart(b"one"), MultipartPart(b"two")],
        boundary="static",
    )

    assert multipart.is_static
    assert multipart.render() == (b"--static\r\n\r\none\r\n--static\r\n\r\ntwo\r\n--static--\r\n")
    part = multipart.as_multipart_part()
    assert part.body is multipart
    assert part.headers == ((b"Content-Type", b"multipart/mixed; boundary=static"),)


def test_nested_multipart_is_framed_recursively() -> None:
    inner = Multipart(
        [
            MultipartPart(b"plain", [(b"Content-Type", b"text/plain")]),
            MultipartPart(b"<p>HTML</p>", [(b"Content-Type", b"text/html")]),
        ],
        subtype="alternative",
        boundary="inner",
    )
    outer = Multipart([inner], boundary="outer")

    body = outer.render()
    outer_part = parse_multipart(body, b"outer")[0]

    assert outer_part.headers == [(b"Content-Type", b"multipart/alternative; boundary=inner")]
    assert parse_multipart(outer_part.body, b"inner") == [
        ParsedPart([(b"Content-Type", b"text/plain")], b"plain"),
        ParsedPart([(b"Content-Type", b"text/html")], b"<p>HTML</p>"),
    ]
    assert outer.is_static


def test_nested_multipart_can_have_part_headers() -> None:
    inner = Multipart([MultipartPart(b"body")], boundary="inner")
    outer = Multipart(
        [MultipartPart(inner, [(b"Content-ID", b"<versions>")])],
        boundary="outer",
    )

    part = parse_multipart(outer.render(), b"outer")[0]

    assert part.headers == [
        (b"Content-ID", b"<versions>"),
        (b"Content-Type", b"multipart/mixed; boundary=inner"),
    ]


def test_conflicting_nested_content_type_is_rejected() -> None:
    inner = Multipart([MultipartPart(b"body")], boundary="inner")

    with pytest.raises(ValueError, match="does not match nested multipart"):
        MultipartPart(
            inner,
            [(b"Content-Type", b"multipart/mixed; boundary=wrong")],
        )


def test_nested_streams_serialize_recursively() -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"one"
        yield b"two"

    inner = Multipart([MultipartPart(body())], boundary="inner")
    outer = Multipart([inner], boundary="outer")

    rendered = asyncio.run(outer.render_async())
    outer_part = parse_multipart(rendered, b"outer")[0]

    assert parse_multipart(outer_part.body, b"inner")[0].body == b"onetwo"
    assert not inner.is_static
    assert not outer.is_static


def test_nested_boundary_prefix_collision_is_rejected() -> None:
    inner = Multipart([MultipartPart(b"body")], boundary="outer-inner")
    outer = Multipart([inner], boundary="outer")

    with pytest.raises(ValueError, match="body contains the boundary"):
        outer.render()


def test_multipart_accepts_convertible_part_objects() -> None:
    class ConvertiblePart:
        def as_multipart_part(self) -> MultipartPart:
            return MultipartPart(b"converted", [(b"X-Part", b"yes")])

    multipart = Multipart([ConvertiblePart()], boundary="convertible")

    assert parse_multipart(multipart.render(), b"convertible") == [
        ParsedPart([(b"X-Part", b"yes")], b"converted")
    ]


def test_multipart_rejects_invalid_part_objects() -> None:
    with pytest.raises(TypeError, match="Multipart items must be"):
        Multipart([object()], boundary="invalid-part").render()  # type: ignore[list-item]


def test_multipart_part_rejects_invalid_body_source() -> None:
    with pytest.raises(TypeError, match="body must be bytes-like or a body stream"):
        MultipartPart("body")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="body must be bytes-like or a body stream"):
        MultipartPart(123)  # type: ignore[arg-type]
