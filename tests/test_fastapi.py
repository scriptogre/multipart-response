from __future__ import annotations

from collections.abc import AsyncIterator

from conftest import ParsedPart, parse_multipart
from fastapi import FastAPI
from fastapi.testclient import TestClient
from python_multipart.multipart import parse_options_header

from multipart_response import Multipart, MultipartPart
from multipart_response.fastapi import (
    HTMLMultipartResponse,
    HTMLPart,
    JSONPart,
    Multipart as FastAPIMultipart,
    MultipartResponse,
    Part,
    TextPart,
)
from multipart_response.starlette import (
    HTMLMultipartResponse as StarletteHTMLMultipartResponse,
    MultipartResponse as StarletteMultipartResponse,
)


def test_fastapi_adapter_reexports_starlette_api() -> None:
    assert FastAPIMultipart is Multipart
    assert MultipartResponse is StarletteMultipartResponse
    assert HTMLMultipartResponse is StarletteHTMLMultipartResponse
    assert Part(b"part").body == b"part"
    assert TextPart("text").body == b"text"
    assert HTMLPart("<p>html</p>").body == b"<p>html</p>"
    assert JSONPart({"json": True}).body == b'{"json":true}'


def test_fastapi_returns_multipart_response() -> None:
    app = FastAPI()

    @app.get("/report")
    async def report() -> MultipartResponse:
        return MultipartResponse(
            [
                JSONPart({"status": "ready"}),
                TextPart("Report complete"),
            ],
            boundary="fastapi",
        )

    with TestClient(app) as client:
        response = client.get("/report")

    media_type, options = parse_options_header(response.headers["content-type"])
    assert media_type == b"multipart/mixed"
    assert options == {b"boundary": b"fastapi"}
    assert parse_multipart(response.content, options[b"boundary"]) == [
        ParsedPart(
            [(b"content-length", b"18"), (b"content-type", b"application/json")],
            b'{"status":"ready"}',
        ),
        ParsedPart(
            [
                (b"content-length", b"15"),
                (b"content-type", b"text/plain; charset=utf-8"),
            ],
            b"Report complete",
        ),
    ]


def test_fastapi_streams_parts_yielded_by_endpoint() -> None:
    app = FastAPI()

    @app.get("/report", response_class=MultipartResponse)
    async def report() -> AsyncIterator[Part]:
        yield TextPart("Preparing report")
        yield JSONPart({"status": "ready"})

    with TestClient(app) as client:
        response = client.get("/report")

    media_type, options = parse_options_header(response.headers["content-type"])
    assert media_type == b"multipart/mixed"
    assert [part.body for part in parse_multipart(response.content, options[b"boundary"])] == [
        b"Preparing report",
        b'{"status":"ready"}',
    ]


def test_fastapi_streams_html_strings_with_per_part_headers() -> None:
    app = FastAPI()

    @app.get("/dashboard", response_class=HTMLMultipartResponse)
    async def dashboard() -> AsyncIterator[str | tuple[str, dict[str, str]]]:
        yield "<p>Ready</p>"
        yield (
            "<li>New report</li>",
            {
                "HX-Target": "#reports",
                "HX-Swap": "beforeend",
            },
        )

    with TestClient(app) as client:
        response = client.get("/dashboard")

    _, options = parse_options_header(response.headers["content-type"])
    parts = parse_multipart(response.content, options[b"boundary"])
    assert parts[0] == ParsedPart(
        [
            (b"content-length", b"12"),
            (b"content-type", b"text/html; charset=utf-8"),
        ],
        b"<p>Ready</p>",
    )
    assert parts[1] == ParsedPart(
        [
            (b"hx-target", b"#reports"),
            (b"hx-swap", b"beforeend"),
            (b"content-length", b"19"),
            (b"content-type", b"text/html; charset=utf-8"),
        ],
        b"<li>New report</li>",
    )


def test_fastapi_streams_one_part_body() -> None:
    app = FastAPI()

    async def body() -> AsyncIterator[bytes]:
        yield b"one"
        yield b"two"

    @app.get("/download", response_class=MultipartResponse)
    async def download() -> AsyncIterator[Part]:
        yield Part(body(), media_type="application/octet-stream")

    with TestClient(app) as client:
        response = client.get("/download")

    _, options = parse_options_header(response.headers["content-type"])
    part = parse_multipart(response.content, options[b"boundary"])[0]
    assert part.headers == [(b"content-type", b"application/octet-stream")]
    assert part.body == b"onetwo"


def test_fastapi_streams_nested_multipart_parts() -> None:
    app = FastAPI()

    @app.get("/nested", response_class=MultipartResponse)
    async def nested() -> AsyncIterator[Multipart]:
        yield Multipart(
            [
                TextPart("Plain text"),
                HTMLPart("<p>HTML</p>"),
            ],
            subtype="alternative",
            boundary="inner",
        )

    with TestClient(app) as client:
        response = client.get("/nested")

    _, options = parse_options_header(response.headers["content-type"])
    outer_part = parse_multipart(response.content, options[b"boundary"])[0]
    assert outer_part.headers[-1] == (
        b"content-type",
        b"multipart/alternative; boundary=inner",
    )
    assert [part.body for part in parse_multipart(outer_part.body, b"inner")] == [
        b"Plain text",
        b"<p>HTML</p>",
    ]


def test_fastapi_html_response_accepts_explicit_parts() -> None:
    app = FastAPI()

    @app.get("/mixed", response_class=HTMLMultipartResponse)
    async def mixed() -> AsyncIterator[Part | MultipartPart]:
        yield TextPart("plain")
        yield JSONPart({"status": "ready"})
        yield MultipartPart(b"raw", [(b"Content-Type", b"application/custom")])

    with TestClient(app) as client:
        response = client.get("/mixed")

    _, options = parse_options_header(response.headers["content-type"])
    assert parse_multipart(response.content, options[b"boundary"]) == [
        ParsedPart(
            [(b"content-length", b"5"), (b"content-type", b"text/plain; charset=utf-8")],
            b"plain",
        ),
        ParsedPart(
            [(b"content-length", b"18"), (b"content-type", b"application/json")],
            b'{"status":"ready"}',
        ),
        ParsedPart([(b"Content-Type", b"application/custom")], b"raw"),
    ]
