from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from conftest import ParsedPart, parse_multipart

from multipart_response import MultipartPart, MultipartWriter


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
