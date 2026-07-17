from __future__ import annotations

from collections.abc import AsyncIterator

from conftest import ParsedPart, parse_multipart
from fastapi import FastAPI
from fastapi.testclient import TestClient
from python_multipart.multipart import parse_options_header

from multipart_response.fastapi import (
    HTMLPart,
    JSONPart,
    MultipartResponse,
    Part,
    TextPart,
)
from multipart_response.starlette import MultipartResponse as StarletteMultipartResponse


def test_fastapi_adapter_reexports_starlette_api() -> None:
    assert MultipartResponse is StarletteMultipartResponse
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


def test_fastapi_streams_per_part_htmx_headers() -> None:
    app = FastAPI()

    @app.get("/dashboard", response_class=MultipartResponse)
    async def dashboard() -> AsyncIterator[HTMLPart]:
        yield HTMLPart(
            "<p>Ready</p>",
            headers={"HX-Target": "#status", "HX-Swap": "innerHTML"},
        )
        yield HTMLPart(
            "<li>New report</li>",
            headers={"HX-Target": "#reports", "HX-Swap": "beforeend"},
        )

    with TestClient(app) as client:
        response = client.get("/dashboard")

    _, options = parse_options_header(response.headers["content-type"])
    parts = parse_multipart(response.content, options[b"boundary"])
    assert parts[0] == ParsedPart(
        [
            (b"hx-target", b"#status"),
            (b"hx-swap", b"innerHTML"),
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
