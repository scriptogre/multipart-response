from __future__ import annotations

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


def test_fastapi_returns_and_documents_multipart_response() -> None:
    app = FastAPI()

    @app.get("/report", response_class=MultipartResponse)
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
        schema = client.get("/openapi.json").json()

    media_type, options = parse_options_header(response.headers["content-type"])
    assert media_type == b"multipart/mixed"
    assert options == {b"boundary": b"fastapi"}
    assert parse_multipart(response.content, options[b"boundary"]) == [
        ParsedPart([(b"content-type", b"application/json")], b'{"status":"ready"}'),
        ParsedPart(
            [(b"content-type", b"text/plain; charset=utf-8")],
            b"Report complete",
        ),
    ]
    assert "multipart/mixed" in schema["paths"]["/report"]["get"]["responses"]["200"]["content"]
