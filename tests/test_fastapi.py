from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime

from conftest import ParsedPart, parse_multipart
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from python_multipart.multipart import parse_options_header

from multipart_response import Multipart, MultipartPart
from multipart_response.fastapi import (
    HTMLMultipartResponse,
    JSONMultipartResponse,
    Multipart as FastAPIMultipart,
    MultipartResponse,
    Part,
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


def test_fastapi_returns_explicit_multipart_response() -> None:
    app = FastAPI()

    @app.get("/report")
    async def report() -> MultipartResponse:
        return MultipartResponse(
            [
                Part(json.dumps({"status": "ready"}), media_type="application/json"),
                Part("Report complete", media_type="text/plain"),
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
            [(b"content-length", b"19"), (b"content-type", b"application/json")],
            b'{"status": "ready"}',
        ),
        ParsedPart(
            [
                (b"content-length", b"15"),
                (b"content-type", b"text/plain; charset=utf-8"),
            ],
            b"Report complete",
        ),
    ]


def test_fastapi_streams_explicit_parts_yielded_by_endpoint() -> None:
    app = FastAPI()

    @app.get("/report", response_class=MultipartResponse)
    async def report() -> AsyncIterator[Part]:
        yield Part("Preparing report", media_type="text/plain")
        yield Part('{"status":"ready"}', media_type="application/json")

    with TestClient(app) as client:
        response = client.get("/report")

    _, options = parse_options_header(response.headers["content-type"])
    assert [part.body for part in parse_multipart(response.content, options[b"boundary"])] == [
        b"Preparing report",
        b'{"status":"ready"}',
    ]


def test_fastapi_streams_implicit_html_parts() -> None:
    app = FastAPI()

    @app.get("/dashboard", response_class=HTMLMultipartResponse)
    async def dashboard() -> AsyncIterator[str | tuple[str, dict[str, str]]]:
        yield "<p>Ready</p>"
        yield "<li>New report</li>", {"HX-Target": "#reports", "HX-Swap": "beforeend"}

    with TestClient(app) as client:
        response = client.get("/dashboard")

    _, options = parse_options_header(response.headers["content-type"])
    assert parse_multipart(response.content, options[b"boundary"]) == [
        ParsedPart(
            [
                (b"content-length", b"12"),
                (b"content-type", b"text/html; charset=utf-8"),
            ],
            b"<p>Ready</p>",
        ),
        ParsedPart(
            [
                (b"hx-target", b"#reports"),
                (b"hx-swap", b"beforeend"),
                (b"content-length", b"19"),
                (b"content-type", b"text/html; charset=utf-8"),
            ],
            b"<li>New report</li>",
        ),
    ]


def test_fastapi_json_response_uses_jsonable_encoder() -> None:
    class Report(BaseModel):
        created: datetime

    app = FastAPI()

    @app.get("/events", response_class=JSONMultipartResponse)
    async def events() -> AsyncIterator[object]:
        yield Report(created=datetime(2025, 1, 2, 3, 4, 5))
        yield {"status": "ready"}
        yield "done"
        yield Part("explicit", media_type="text/plain")

    with TestClient(app) as client:
        response = client.get("/events")

    _, options = parse_options_header(response.headers["content-type"])
    assert parse_multipart(response.content, options[b"boundary"]) == [
        ParsedPart(
            [(b"content-length", b"33"), (b"content-type", b"application/json")],
            b'{"created":"2025-01-02T03:04:05"}',
        ),
        ParsedPart(
            [(b"content-length", b"18"), (b"content-type", b"application/json")],
            b'{"status":"ready"}',
        ),
        ParsedPart(
            [(b"content-length", b"6"), (b"content-type", b"application/json")],
            b'"done"',
        ),
        ParsedPart(
            [(b"content-length", b"8"), (b"content-type", b"text/plain; charset=utf-8")],
            b"explicit",
        ),
    ]


def test_json_response_accepts_one_returned_value() -> None:
    class Report(BaseModel):
        status: str

    responses = [
        JSONMultipartResponse({"status": "mapping"}, boundary="mapping"),
        JSONMultipartResponse("string", boundary="string"),
        JSONMultipartResponse(Report(status="model"), boundary="model"),
        JSONMultipartResponse([1, 2], boundary="sequence"),
    ]

    expected = [b'{"status":"mapping"}', b'"string"', b'{"status":"model"}', b"1", b"2"]
    bodies: list[bytes] = []
    for response in responses:
        client = TestClient(response)
        try:
            result = client.get("/")
        finally:
            client.close()
        bodies.extend(
            part.body for part in parse_multipart(result.content, response.boundary.encode("ascii"))
        )

    assert bodies == expected


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
                Part("Plain text", media_type="text/plain"),
                Part("<p>HTML</p>", media_type="text/html"),
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


def test_specialized_responses_accept_raw_parts() -> None:
    responses = [
        HTMLMultipartResponse([MultipartPart(b"html")], boundary="html"),
        JSONMultipartResponse([MultipartPart(b"json")], boundary="json"),
    ]

    for response in responses:
        client = TestClient(response)
        try:
            result = client.get("/")
        finally:
            client.close()
        assert parse_multipart(result.content, response.boundary.encode("ascii"))[0].body in {
            b"html",
            b"json",
        }
