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
    HTMLMultipartResponse,
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


def test_sequence_is_buffered_with_content_length() -> None:
    response = MultipartResponse(
        [
            TextPart("plain"),
            JSONPart({"status": "ok"}),
            Part(bytearray(b"array"), media_type="application/octet-stream"),
            Part(memoryview(b"view"), media_type="application/octet-stream"),
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


@pytest.mark.parametrize(
    "item",
    [
        "text",
        {"status": "ok"},
        b"bytes",
        bytearray(b"array"),
        memoryview(b"view"),
        ("text", {"X-Part": "value"}),
        123,
    ],
)
def test_multipart_response_requires_explicit_parts(item: object) -> None:
    with pytest.raises(
        TypeError,
        match=rf"MultipartResponse items must be Part or MultipartPart; got {type(item).__name__}",
    ):
        MultipartResponse([item])  # type: ignore[list-item]


def test_html_response_converts_strings_and_header_pairs() -> None:
    response = HTMLMultipartResponse(
        [
            "<p>Loading</p>",
            (
                "<p>Ready</p>",
                {"HX-Target": "#status", "HX-Swap": "innerHTML"},
            ),
        ],
        boundary="html",
    )

    result = get_response(response)

    assert result.headers["content-length"] == str(len(result.content))
    assert parse_multipart(result.content, b"html") == [
        ParsedPart(
            [
                (b"content-length", b"14"),
                (b"content-type", b"text/html; charset=utf-8"),
            ],
            b"<p>Loading</p>",
        ),
        ParsedPart(
            [
                (b"hx-target", b"#status"),
                (b"hx-swap", b"innerHTML"),
                (b"content-length", b"12"),
                (b"content-type", b"text/html; charset=utf-8"),
            ],
            b"<p>Ready</p>",
        ),
    ]


def test_synchronous_html_iterable_streams_implicit_parts() -> None:
    def parts() -> Iterator[str | tuple[str, dict[str, str]]]:
        yield "<p>One</p>"
        yield "<p>Two</p>", {"X-Part": "two"}

    result = get_response(HTMLMultipartResponse(parts(), boundary="html-sync"))

    assert "content-length" not in result.headers
    assert [part.body for part in parse_multipart(result.content, b"html-sync")] == [
        b"<p>One</p>",
        b"<p>Two</p>",
    ]


def test_asynchronous_html_iterable_streams_implicit_parts() -> None:
    async def parts() -> AsyncIterator[str | tuple[str, dict[str, str]]]:
        yield "<p>One</p>"
        yield "<p>Two</p>", {"X-Part": "two"}

    result = get_response(HTMLMultipartResponse(parts(), boundary="html-async"))

    assert "content-length" not in result.headers
    assert [part.body for part in parse_multipart(result.content, b"html-async")] == [
        b"<p>One</p>",
        b"<p>Two</p>",
    ]


def test_html_response_honors_an_explicit_content_type_in_pair_headers() -> None:
    response = HTMLMultipartResponse(
        [("<p>Literal markup</p>", {"Content-Type": "text/plain; charset=utf-8"})],
        boundary="override",
    )

    part = parse_multipart(get_response(response).content, b"override")[0]

    assert part.headers == [
        (b"content-type", b"text/plain; charset=utf-8"),
        (b"content-length", b"21"),
    ]


def test_html_response_passes_explicit_parts_through_unchanged() -> None:
    response = HTMLMultipartResponse(
        [
            Part(b"untyped", headers={"X-Part": "raw"}),
            TextPart("plain"),
            HTMLPart("<p>Explicit</p>"),
            JSONPart({"status": "ready"}),
            MultipartPart(b"custom", [(b"X-Raw", b"yes")]),
        ],
        boundary="explicit",
    )

    parts = parse_multipart(get_response(response).content, b"explicit")

    assert parts == [
        ParsedPart([(b"x-part", b"raw"), (b"content-length", b"7")], b"untyped"),
        ParsedPart(
            [(b"content-length", b"5"), (b"content-type", b"text/plain; charset=utf-8")],
            b"plain",
        ),
        ParsedPart(
            [(b"content-length", b"15"), (b"content-type", b"text/html; charset=utf-8")],
            b"<p>Explicit</p>",
        ),
        ParsedPart(
            [(b"content-length", b"18"), (b"content-type", b"application/json")],
            b'{"status":"ready"}',
        ),
        ParsedPart([(b"X-Raw", b"yes")], b"custom"),
    ]


@pytest.mark.parametrize(
    "item",
    [
        {"status": "ready"},
        b"bytes",
        123,
        ("body",),
        ("body", {}, "extra"),
        (123, {}),
        ("body", []),
        ("body", {"X-Part": 1}),
    ],
)
def test_html_response_rejects_other_implicit_values(item: object) -> None:
    with pytest.raises(TypeError):
        HTMLMultipartResponse([item])  # type: ignore[list-item]


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
    result = get_response(MultipartResponse([TextPart("body")]))
    boundary = response_boundary(result.headers["content-type"])

    assert boundary.startswith(b"multipart-")
    assert parse_multipart(result.content, boundary)[0].body == b"body"


def test_invalid_subtype_and_body_collision_are_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid multipart subtype"):
        MultipartResponse([TextPart("body")], subtype="bad subtype")

    with pytest.raises(ValueError, match="body contains the boundary"):
        MultipartResponse([Part(b"\r\n--collision")], boundary="collision")
