from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from conftest import ParsedPart, parse_multipart
from fasthtml.common import Div, FastHTML, P  # type: ignore[import-untyped]
from python_multipart.multipart import parse_options_header
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from multipart_response import Multipart, MultipartPart
from multipart_response.fasthtml import (
    JSONPart,
    Multipart as FastHTMLMultipart,
    MultipartResponse,
    Part,
)


def test_fasthtml_adapter_reexports_shared_api() -> None:
    class Value:
        def __str__(self) -> str:
            return "custom"

    assert FastHTMLMultipart is Multipart
    assert JSONPart({"value": Value()}).body == b'{"value":"custom"}'


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


def test_fasthtml_route_streams_components_and_explicit_parts() -> None:
    app = FastHTML(secret_key="test")
    route = app.route
    consumed: list[str] = []

    def get() -> MultipartResponse:
        def parts() -> Iterator[Any]:
            consumed.append("ready")
            yield P("Ready")
            consumed.append("done")
            yield Part(Div("Done"), headers={"HX-Target": "#status"})
            yield JSONPart({"status": "done"})

        response = MultipartResponse(parts(), boundary="fasthtml")
        assert consumed == []
        return response

    route("/updates")(get)

    with TestClient(app) as client:
        response = client.get("/updates")

    assert consumed == ["ready", "done"]
    assert response.status_code == 200
    assert response.headers["content-type"] == "multipart/mixed; boundary=fasthtml"
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


def test_fasthtml_route_streams_async_components() -> None:
    app = FastHTML(secret_key="test")
    route = app.route

    async def get() -> MultipartResponse:
        async def parts() -> AsyncIterator[Any]:
            yield P("One")
            yield P("Two")

        return MultipartResponse(parts(), boundary="fasthtml-async")

    route("/updates")(get)

    with TestClient(app) as client:
        response = client.get("/updates")

    _, options = parse_options_header(response.headers["content-type"])
    assert [part.body for part in parse_multipart(response.content, options[b"boundary"])] == [
        b"<p>One</p>\n",
        b"<p>Two</p>\n",
    ]


def test_html_response_accepts_strings_and_shared_parts() -> None:
    response = MultipartResponse(
        [
            "<p>HTML</p>",
            Part("plain", media_type="text/plain"),
            MultipartPart(b"raw"),
        ],
        boundary="shared",
    )

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await response(scope, receive, send)

    client = TestClient(app)
    try:
        result = client.get("/")
    finally:
        client.close()

    assert [part.body for part in parse_multipart(result.content, b"shared")] == [
        b"<p>HTML</p>",
        b"plain",
        b"raw",
    ]


@pytest.mark.parametrize("content", [P("Ready"), "Ready"])
def test_html_response_requires_explicit_part_for_headers(content: object) -> None:
    with pytest.raises(TypeError, match=r"Part\(content, headers=\.\.\.\)"):
        MultipartResponse([(content, {"HX-Target": "#status"})])  # type: ignore[list-item]
