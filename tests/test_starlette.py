from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from conftest import ParsedPart, parse_multipart
from httpx2 import Response
from python_multipart.multipart import parse_options_header
from starlette.background import BackgroundTask
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from multipart_response import MultipartPart
from multipart_response.starlette import (
    HTMLPart,
    JSONPart,
    MultipartResponse,
    Part,
    TextPart,
)


def get_response(response: MultipartResponse) -> Response:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await response(scope, receive, send)

    client = TestClient(app)
    try:
        result: Response = client.get("/")
        return result
    finally:
        client.close()


def response_boundary(content_type: str) -> bytes:
    media_type, options = parse_options_header(content_type)
    assert media_type.startswith(b"multipart/")
    return options[b"boundary"]


def test_part_uses_starlette_rendering_and_headers() -> None:
    assert Part().body == b""
    assert Part(b"bytes").body == b"bytes"
    assert bytes(Part(memoryview(b"view")).body) == b"view"
    assert Part(bytearray(b"array")).body == b"array"
    assert Part("text", media_type="text/custom").body == b"text"

    part = Part(
        "text",
        headers={"Content-Type": "text/special", "X-Part": "value"},
        media_type="text/ignored",
    )
    assert part.headers["content-type"] == "text/special"
    assert part.headers["x-part"] == "value"
    part.headers["Content-ID"] = "<part>"
    assert part.headers["content-id"] == "<part>"
    assert part.headers is part.headers
    assert part.headers["content-length"] == "4"

    part.set_cookie("session", "value", httponly=True)
    part.delete_cookie("obsolete")
    assert len(part.headers.getlist("set-cookie")) == 2
    assert b"content-id: <part>\r\n" in part.render_headers()
    assert b"set-cookie: session=value" in part.render_headers()


def test_part_convenience_classes() -> None:
    assert TextPart("héllo").raw_headers == [
        (b"content-length", b"6"),
        (b"content-type", b"text/plain; charset=utf-8"),
    ]
    assert HTMLPart("<p>Hello</p>").raw_headers == [
        (b"content-length", b"12"),
        (b"content-type", b"text/html; charset=utf-8"),
    ]
    assert JSONPart({"message": "héllo"}).body == b'{"message":"h\xc3\xa9llo"}'
    assert JSONPart({"ok": True}).raw_headers == [
        (b"content-length", b"11"),
        (b"content-type", b"application/json"),
    ]

    with pytest.raises(ValueError):
        JSONPart({"value": float("nan")})


def test_sequence_is_buffered_with_content_length_and_value_coercion() -> None:
    response = MultipartResponse(
        [
            "plain",
            {"status": "ok"},
            bytearray(b"array"),
            memoryview(b"view"),
            HTMLPart("<strong>HTML</strong>"),
            MultipartPart(b"raw", [(b"Content-Type", b"application/custom")]),
        ],
        boundary="fixed",
    )

    result = get_response(response)

    assert result.status_code == 200
    assert result.headers["content-type"] == "multipart/mixed; boundary=fixed"
    assert result.headers["content-length"] == str(len(result.content))
    assert result.content == response.body
    assert parse_multipart(result.content, b"fixed") == [
        ParsedPart(
            [(b"content-length", b"5"), (b"content-type", b"text/plain; charset=utf-8")],
            b"plain",
        ),
        ParsedPart(
            [(b"content-length", b"15"), (b"content-type", b"application/json")],
            b'{"status":"ok"}',
        ),
        ParsedPart(
            [(b"content-length", b"5"), (b"content-type", b"application/octet-stream")],
            b"array",
        ),
        ParsedPart(
            [(b"content-length", b"4"), (b"content-type", b"application/octet-stream")],
            b"view",
        ),
        ParsedPart(
            [
                (b"content-length", b"21"),
                (b"content-type", b"text/html; charset=utf-8"),
            ],
            b"<strong>HTML</strong>",
        ),
        ParsedPart([(b"Content-Type", b"application/custom")], b"raw"),
    ]


def test_synchronous_iterable_streams_without_content_length() -> None:
    def parts() -> Iterator[TextPart]:
        yield TextPart("one")
        yield TextPart("two")

    response = MultipartResponse(parts(), boundary="sync")
    result = get_response(response)

    assert "content-length" not in result.headers
    assert [part.body for part in parse_multipart(result.content, b"sync")] == [b"one", b"two"]


def test_asynchronous_iterable_streams_without_content_length() -> None:
    async def parts() -> AsyncIterator[JSONPart]:
        yield JSONPart({"part": 1})
        yield JSONPart({"part": 2})

    response = MultipartResponse(parts(), boundary="async")
    result = get_response(response)

    assert "content-length" not in result.headers
    assert [part.body for part in parse_multipart(result.content, b"async")] == [
        b'{"part":1}',
        b'{"part":2}',
    ]


def test_empty_response_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one part"):
        MultipartResponse([], boundary="empty")


def test_response_options_and_background_task() -> None:
    completed: list[bool] = []
    response = MultipartResponse(
        [TextPart("created")],
        status_code=201,
        headers={"X-Response": "value"},
        subtype="alternative",
        background=BackgroundTask(completed.append, True),
        boundary="options",
    )

    result = get_response(response)

    assert result.status_code == 201
    assert result.headers["x-response"] == "value"
    assert result.headers["content-type"] == "multipart/alternative; boundary=options"
    assert completed == [True]


def test_generated_boundary_matches_content_type() -> None:
    result = get_response(MultipartResponse(["body"]))
    boundary = response_boundary(result.headers["content-type"])

    assert boundary.startswith(b"multipart-")
    assert parse_multipart(result.content, boundary)[0].body == b"body"


def test_invalid_item_is_rejected() -> None:
    with pytest.raises(TypeError, match="got int"):
        MultipartResponse([123])  # type: ignore[list-item]


def test_invalid_subtype_and_body_collision_are_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid multipart subtype"):
        MultipartResponse(["body"], subtype="bad subtype")

    with pytest.raises(ValueError, match="body contains the boundary"):
        MultipartResponse([Part(b"\r\n--collision")], boundary="collision")
