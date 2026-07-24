from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from conftest import ParsedPart, parse_multipart
from fasthtml.common import Div, FastHTML, P  # type: ignore[import-untyped]
from httpx2 import Response
from python_multipart.multipart import parse_options_header
from starlette.responses import StreamingResponse
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from multipart_response import Multipart, MultipartPart
from multipart_response.fasthtml import (
    HTMLMultipartResponse,
    Multipart as FastHTMLMultipart,
    MultipartResponse,
    Part,
)


def get_response(response: StreamingResponse) -> Response:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await response(scope, receive, send)

    client = TestClient(app)
    try:
        return client.get("/")
    finally:
        client.close()


def test_fasthtml_adapter_reexports_core_multipart() -> None:
    assert FastHTMLMultipart is Multipart


def test_part_defaults_to_html_and_renders_fasthtml_components() -> None:
    class Component:
        def __ft__(self) -> object:
            return P("Custom")

    part = Part(P("Ready"))
    assert part.body == b"<p>Ready</p>\n"
    assert part.headers["content-type"] == "text/html; charset=utf-8"
    assert Part(Component()).body == b"<p>Custom</p>\n"
    assert Part("plain", media_type="text/plain").headers["content-type"] == (
        "text/plain; charset=utf-8"
    )


def test_fasthtml_route_streams_explicit_parts() -> None:
    app = FastHTML(secret_key="test")
    route = app.route
    consumed: list[str] = []

    def get() -> MultipartResponse:
        def parts() -> Iterator[Part]:
            consumed.append("ready")
            yield Part(P("Ready"))
            consumed.append("done")
            yield Part(Div("Done"), headers={"HX-Target": "#status"})
            yield Part('{"status":"done"}', media_type="application/json")

        response = MultipartResponse(parts(), boundary="fasthtml")
        assert consumed == []
        return response

    route("/updates")(get)

    with TestClient(app) as client:
        response = client.get("/updates")

    assert consumed == ["ready", "done"]
    assert "content-length" not in response.headers
    assert parse_multipart(response.content, b"fasthtml") == [
        ParsedPart(
            [
                (b"content-length", b"13"),
                (b"content-type", b"text/html; charset=utf-8"),
            ],
            b"<p>Ready</p>\n",
        ),
        ParsedPart(
            [
                (b"hx-target", b"#status"),
                (b"content-length", b"16"),
                (b"content-type", b"text/html; charset=utf-8"),
            ],
            b"<div>Done</div>\n",
        ),
        ParsedPart(
            [(b"content-length", b"17"), (b"content-type", b"application/json")],
            b'{"status":"done"}',
        ),
    ]


def test_multipart_response_requires_explicit_parts() -> None:
    with pytest.raises(TypeError, match="must be Part"):
        MultipartResponse([P("Ready")])


def test_html_response_accepts_components_strings_headers_and_raw_parts() -> None:
    response = HTMLMultipartResponse(
        [
            P("Ready"),
            "<p>String</p>",
            (Div("Done"), {"HX-Target": "#status"}),
            MultipartPart(b"raw"),
        ],
        boundary="html",
    )

    result = get_response(response)
    assert [part.body for part in parse_multipart(result.content, b"html")] == [
        b"<p>Ready</p>\n",
        b"<p>String</p>",
        b"<div>Done</div>\n",
        b"raw",
    ]


@pytest.mark.parametrize("content", [P("Ready"), "Ready", (P("Ready"), {"X-Part": "yes"})])
def test_html_response_accepts_one_implicit_part(content: object) -> None:
    response = HTMLMultipartResponse(content, boundary="one-html")
    result = get_response(response)
    assert len(parse_multipart(result.content, b"one-html")) == 1


def test_html_response_rejects_invalid_header_pairs() -> None:
    with pytest.raises(TypeError, match="HTML content and headers"):
        HTMLMultipartResponse([("body",)])
    with pytest.raises(TypeError, match="map strings to strings"):
        HTMLMultipartResponse([("body", {"X-Part": 1})])


def test_fasthtml_route_streams_implicit_html_parts() -> None:
    app = FastHTML(secret_key="test")
    route = app.route

    async def get() -> HTMLMultipartResponse:
        async def parts() -> AsyncIterator[Any]:
            yield P("One")
            yield P("Two"), {"HX-Target": "#status"}

        return HTMLMultipartResponse(parts())

    route("/html")(get)

    with TestClient(app) as client:
        response = client.get("/html")

    _, options = parse_options_header(response.headers["content-type"])
    assert [part.body for part in parse_multipart(response.content, options[b"boundary"])] == [
        b"<p>One</p>\n",
        b"<p>Two</p>\n",
    ]
