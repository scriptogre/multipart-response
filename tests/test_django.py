from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from conftest import ParsedPart, parse_multipart
from django.conf import settings

if not settings.configured:
    settings.configure(
        ALLOWED_HOSTS=["testserver"],
        DEFAULT_CHARSET="utf-8",
        ROOT_URLCONF=__name__,
        SECRET_KEY="test-secret",
    )

from django.http import HttpResponse, StreamingHttpResponse
from django.test import AsyncClient, Client
from django.urls import path

from multipart_response import Multipart, MultipartPart
from multipart_response.django import (
    Multipart as DjangoMultipart,
    MultipartResponse,
    Part,
)


def consume(response: Any) -> bytes:
    return b"".join(response)


async def consume_async(response: Any) -> bytes:
    body = bytearray()
    async for chunk in response:
        body.extend(chunk)
    return bytes(body)


def test_part_binds_django_response_api() -> None:
    assert Part.charset is HttpResponse.charset
    assert Part.serialize_headers is HttpResponse.serialize_headers
    assert Part.__setitem__ is HttpResponse.__setitem__
    assert Part.__delitem__ is HttpResponse.__delitem__
    assert Part.__getitem__ is HttpResponse.__getitem__
    assert Part.__contains__ is HttpResponse.__contains__
    assert Part.has_header is HttpResponse.has_header
    assert Part.items is HttpResponse.items
    assert Part.get is HttpResponse.get
    assert Part.setdefault is HttpResponse.setdefault
    assert Part.set_cookie is HttpResponse.set_cookie
    assert Part.set_signed_cookie is HttpResponse.set_signed_cookie
    assert Part.delete_cookie is HttpResponse.delete_cookie
    assert Part.make_bytes is HttpResponse.make_bytes


def test_part_uses_django_header_and_charset_behavior() -> None:
    expected = HttpResponse(
        b"",
        content_type="text/custom",
        charset="iso-8859-1",
        headers={"X-Number": 1, "X-Text": "välue"},
    )
    part = Part(
        "héllo",
        content_type="text/custom",
        charset="iso-8859-1",
        headers={"X-Number": 1, "X-Text": "välue"},
    )

    assert type(part.headers) is type(expected.headers)
    assert list(part.items()) == list(expected.items())
    assert part.charset == expected.charset
    assert part.content == b"h\xe9llo"
    assert part.serialize_headers() == expected.serialize_headers()

    part["X-Set"] = 2
    assert part["x-set"] == "2"
    assert "X-Set" in part
    assert part.has_header("x-set")
    assert part.get("X-Set") == "2"
    assert part.get("Missing", "fallback") == "fallback"
    part.setdefault("X-Set", 3)
    part.setdefault("X-Default", 4)
    assert part["X-Set"] == "2"
    assert part["X-Default"] == "4"
    del part["X-Set"]
    del part["Missing"]
    assert "X-Set" not in part


def test_part_uses_django_content_type_defaults_and_conflicts() -> None:
    assert list(Part().items()) == [("Content-Type", "text/html; charset=utf-8")]
    assert Part("body", content_type="text/plain")["Content-Type"] == "text/plain"
    assert Part("body", headers={"Content-Type": "text/special"})["Content-Type"] == "text/special"

    with pytest.raises(ValueError, match="headers.*Content-Type"):
        Part(
            "body",
            content_type="text/plain",
            headers={"Content-Type": "text/plain"},
        )


def test_part_uses_django_scalar_and_stream_conversion() -> None:
    assert Part(None).content == b"None"
    assert Part(b"bytes").content == b"bytes"
    assert Part(memoryview(b"view")).content == b"view"
    assert Part(123).content == b"123"

    bytearray_part = Part(bytearray(b"ab"), content_type="application/octet-stream")
    assert consume(MultipartResponse([bytearray_part], boundary="array"))
    assert (
        parse_multipart(
            consume(MultipartResponse([Part(bytearray(b"ab"))], boundary="array-two")),
            b"array-two",
        )[0].body
        == b"9798"
    )


def test_part_streams_sync_chunks_through_django_make_bytes() -> None:
    consumed: list[object] = []

    def body() -> Iterator[object]:
        for chunk in ["hé", b"llo", memoryview(b"!"), 123]:
            consumed.append(chunk)
            yield chunk

    part = Part(body(), content_type="text/plain")
    response = MultipartResponse([part], boundary="sync-body")

    assert consumed == []
    parsed = parse_multipart(consume(response), b"sync-body")[0]
    assert parsed.body == b"h\xc3\xa9llo!123"
    assert consumed == ["hé", b"llo", memoryview(b"!"), 123]


def test_part_streams_async_chunks_through_django_make_bytes() -> None:
    async def body() -> AsyncIterator[object]:
        yield "one"
        yield b"two"
        yield 3

    response = MultipartResponse(
        [Part(body(), content_type="text/plain")],
        boundary="async-body",
    )

    assert response.is_async
    parsed = parse_multipart(asyncio.run(consume_async(response)), b"async-body")[0]
    assert parsed.body == b"onetwo3"


def test_part_cookies_use_django_behavior_and_mime_headers() -> None:
    part = Part("body")
    part.set_cookie("session", "value", httponly=True, samesite="Lax")
    part.set_signed_cookie("signed", "value")
    part.delete_cookie("obsolete")

    rendered = part.render_headers()
    assert rendered.startswith(b"Content-Type: text/html; charset=utf-8\r\n")
    assert b"Set-Cookie: session=value; HttpOnly; Path=/; SameSite=Lax\r\n" in rendered
    assert b"Set-Cookie: signed=" in rendered
    assert b"Set-Cookie: obsolete=" in rendered

    parsed = parse_multipart(
        consume(MultipartResponse([part], boundary="cookies")),
        b"cookies",
    )[0]
    assert [name for name, _ in parsed.headers].count(b"Set-Cookie") == 3


def test_part_render_headers_without_normal_headers() -> None:
    part = Part("body")
    del part["Content-Type"]
    assert part.render_headers() == b""

    part.set_cookie("session", "value")
    assert part.render_headers() == b"Set-Cookie: session=value; Path=/\r\n"


def test_django_adapter_reexports_core_multipart() -> None:
    assert DjangoMultipart is Multipart


def test_static_response_uses_django_envelope_options() -> None:
    response = MultipartResponse(
        [Part("created")],
        status=201,
        reason="Made",
        charset="iso-8859-1",
        headers={"X-Response": 1},
        subtype="alternative",
        boundary="options",
    )
    body = consume(response)

    assert isinstance(response, StreamingHttpResponse)
    assert response.status_code == 201
    assert response.reason_phrase == "Made"
    assert response.charset == "iso-8859-1"
    assert response["X-Response"] == "1"
    assert response["Content-Type"] == "multipart/alternative; boundary=options"
    assert response["Content-Length"] == str(len(body))
    assert response.boundary == "options"
    assert response.multipart.content_type == "multipart/alternative; boundary=options"


def test_response_rejects_conflicting_envelope_content_type() -> None:
    with pytest.raises(ValueError, match="headers.*Content-Type"):
        MultipartResponse(
            [Part("body")],
            headers={"Content-Type": "multipart/custom"},
        )


def test_sync_part_source_streams_lazily() -> None:
    consumed: list[str] = []

    def parts() -> Iterator[Part]:
        consumed.append("one")
        yield Part("one")
        consumed.append("two")
        yield Part("two")

    response = MultipartResponse(parts(), boundary="sync")
    assert consumed == []
    assert "Content-Length" not in response
    assert [part.body for part in parse_multipart(consume(response), b"sync")] == [
        b"one",
        b"two",
    ]
    assert consumed == ["one", "two"]


def test_async_part_source_streams_lazily() -> None:
    consumed: list[str] = []

    async def parts() -> AsyncIterator[Part]:
        consumed.append("one")
        yield Part("one")
        consumed.append("two")
        yield Part("two")

    response = MultipartResponse(parts(), boundary="async")
    assert consumed == []
    assert response.is_async
    assert "Content-Length" not in response
    body = asyncio.run(consume_async(response))
    assert [part.body for part in parse_multipart(body, b"async")] == [b"one", b"two"]
    assert consumed == ["one", "two"]


def test_response_accepts_raw_and_nested_parts() -> None:
    nested = Multipart(
        [Part("plain", content_type="text/plain"), Part("<p>HTML</p>")],
        subtype="alternative",
        boundary="inner",
    )
    response = MultipartResponse(
        [
            Part(b"part", headers={"X-Part": "yes"}),
            MultipartPart(b"raw", [(b"Content-Type", b"application/custom")]),
            nested,
        ],
        boundary="outer",
    )
    parts = parse_multipart(consume(response), b"outer")

    assert parts[0].body == b"part"
    assert parts[1] == ParsedPart([(b"Content-Type", b"application/custom")], b"raw")
    assert parts[2].headers == [(b"Content-Type", b"multipart/alternative; boundary=inner")]
    assert [part.body for part in parse_multipart(parts[2].body, b"inner")] == [
        b"plain",
        b"<p>HTML</p>",
    ]


def test_nested_async_multipart_selects_async_response() -> None:
    async def body() -> AsyncIterator[str]:
        yield "one"
        yield "two"

    nested = Multipart([Part(body())], boundary="inner-async")
    response = MultipartResponse([nested], boundary="outer-async")

    assert response.is_async
    outer = parse_multipart(asyncio.run(consume_async(response)), b"outer-async")[0]
    assert parse_multipart(outer.body, b"inner-async")[0].body == b"onetwo"


def test_nested_async_raw_part_selects_async_response() -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"body"

    nested = Multipart([MultipartPart(body())], boundary="inner-raw")
    response = MultipartResponse([nested], boundary="outer-raw")

    assert response.is_async
    outer = parse_multipart(asyncio.run(consume_async(response)), b"outer-raw")[0]
    assert parse_multipart(outer.body, b"inner-raw")[0].body == b"body"


def test_nested_async_part_source_selects_async_response() -> None:
    async def parts() -> AsyncIterator[Part]:
        yield Part("body")

    nested = Multipart(parts(), boundary="inner-source")
    response = MultipartResponse([nested], boundary="outer-source")

    assert response.is_async
    outer = parse_multipart(asyncio.run(consume_async(response)), b"outer-source")[0]
    assert parse_multipart(outer.body, b"inner-source")[0].body == b"body"


def test_nested_multipart_inside_multipart_is_detected() -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"body"

    inner = Multipart([MultipartPart(body())], boundary="deep-inner")
    middle = Multipart([inner], boundary="middle")
    response = MultipartResponse([middle], boundary="deep-outer")

    assert response.is_async
    outer = parse_multipart(asyncio.run(consume_async(response)), b"deep-outer")[0]
    middle_part = parse_multipart(outer.body, b"middle")[0]
    assert parse_multipart(middle_part.body, b"deep-inner")[0].body == b"body"


def test_part_rejects_conflicting_nested_content_type() -> None:
    nested = Multipart([Part("body")], boundary="inner")

    with pytest.raises(ValueError, match="does not match nested multipart"):
        Part(nested, content_type="multipart/mixed; boundary=wrong")

    with pytest.raises(ValueError, match="does not match nested multipart"):
        Part(nested, headers={"Content-Type": "multipart/mixed; boundary=wrong"})

    with pytest.raises(ValueError, match="headers.*Content-Type"):
        Part(
            nested,
            content_type=nested.content_type,
            headers={"Content-Type": nested.content_type},
        )


@pytest.mark.parametrize("item", ["text", b"bytes", 123, {"status": "ready"}])
def test_multipart_response_requires_explicit_parts(item: object) -> None:
    with pytest.raises(TypeError, match="MultipartResponse items must be"):
        MultipartResponse([item])  # type: ignore[list-item]


def test_empty_invalid_subtype_and_boundary_collision_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one part"):
        MultipartResponse([], boundary="empty")

    with pytest.raises(ValueError, match="Invalid multipart subtype"):
        MultipartResponse([Part("body")], subtype="bad subtype")

    with pytest.raises(ValueError, match="body contains the boundary"):
        MultipartResponse([Part(b"\r\n--collision")], boundary="collision")


def test_generated_boundary_matches_content_type() -> None:
    response = MultipartResponse([Part("body")])
    assert response.boundary.startswith("multipart-")
    assert f"boundary={response.boundary}" in response["Content-Type"]
    assert parse_multipart(consume(response), response.boundary)[0].body == b"body"


def sync_view(request: object) -> MultipartResponse:
    def parts() -> Iterator[Part]:
        yield Part("one")
        yield Part(json.dumps({"part": 2}), content_type="application/json")

    return MultipartResponse(parts(), boundary="wsgi")


async def async_view(request: object) -> MultipartResponse:
    async def parts() -> AsyncIterator[Part]:
        yield Part("one")
        yield Part(json.dumps({"part": 2}), content_type="application/json")

    return MultipartResponse(parts(), boundary="asgi")


urlpatterns = [
    path("sync/", sync_view),
    path("async/", async_view),
]


def test_django_wsgi_client_streams_response() -> None:
    response = Client().get("/sync/")
    assert response.status_code == 200
    assert [part.body for part in parse_multipart(consume(response), b"wsgi")] == [
        b"one",
        b'{"part": 2}',
    ]


def test_django_asgi_client_streams_response() -> None:
    async def request() -> tuple[int, bytes]:
        response = await AsyncClient().get("/async/")
        return response.status_code, await consume_async(response)

    status, body = asyncio.run(request())
    assert status == 200
    assert [part.body for part in parse_multipart(body, b"asgi")] == [
        b"one",
        b'{"part": 2}',
    ]
