# multipart-response

Stream one HTTP response as multiple MIME parts. For FastAPI, Starlette, and Django.

## FastAPI

```console
uv add "multipart-response[fastapi]"
```

Yield HTML shorthand and explicit parts from one path operation:

```python
from fastapi import FastAPI
from multipart_response.fastapi import HTMLMultipartResponse, JSONPart, Part

app = FastAPI()


@app.get("/updates", response_class=HTMLMultipartResponse)
async def updates():
    yield "<p>Ready</p>", {"HX-Target": "#status"}
    yield JSONPart({"status": "ready"})
    yield Part(chunk_stream(), media_type="video/mp4")
```

- `HTMLMultipartResponse` accepts HTML strings, `(HTML, headers)`, and explicit parts.
- `Part(content, headers=..., media_type=...)` exposes `headers`, `set_cookie()`, and `delete_cookie()`.
- `MultipartResponse` accepts `status_code`, `headers`, `subtype`, `background`, and `boundary`.
- Return `MultipartResponse([...])` directly to set outer response options.

## Starlette

```console
uv add "multipart-response[starlette]"
```

Return a Starlette response from an endpoint:

```python
from multipart_response.starlette import MultipartResponse, Part


async def updates(request):
    part = Part("Ready", media_type="text/plain", headers={"Content-ID": "status"})
    part.headers["HX-Target"] = "#status"
    part.set_cookie("seen", "yes")

    return MultipartResponse(
        [part],
        status_code=200,
        headers={"X-Stream": "updates"},
    )
```

- `Part(content, headers=..., media_type=...)` exposes `headers`, `set_cookie()`, and `delete_cookie()`.
- `HTMLMultipartResponse`, `HTMLPart`, `TextPart`, and `JSONPart` provide content shortcuts.
- `MultipartResponse` subclasses `StreamingResponse` and accepts `status_code`, `headers`, `subtype`, `background`, and `boundary`.

## Django

```console
uv add "multipart-response[django]"
```

Return explicit parts from a Django view:

```python
from multipart_response.django import JsonPart, MultipartResponse, Part


def updates(request):
    def parts():
        part = Part(
            "Ready",
            content_type="text/plain",
            charset="utf-8",
            headers={"Content-ID": "status"},
        )
        part["HX-Target"] = "#status"
        part.headers["HX-Swap"] = "innerHTML"
        part.set_cookie("seen", "yes")

        yield part
        yield JsonPart({"status": "ready"})

    return MultipartResponse(
        parts(),
        status=200,
        reason="OK",
        headers={"X-Stream": "updates"},
    )
```

- `Part(content, content_type=..., charset=..., headers=...)` defaults to HTML.
- `Part.content` contains the rendered content or stream.
- Parts support Django's header mapping, `has_header()`, `get()`, `setdefault()`, `set_cookie()`, `set_signed_cookie()`, and `delete_cookie()`.
- `JsonPart` accepts `encoder`, `safe`, `json_dumps_params`, `content_type`, `charset`, and `headers`.
- `MultipartResponse` accepts `status`, `reason`, `charset`, `headers`, `subtype`, and `boundary`.

Use an async part source under ASGI:

```python
async def updates(request):
    async def parts():
        yield Part("<p>Ready</p>")
        yield Part("<p>Done</p>")

    return MultipartResponse(parts())
```

`MultipartResponse` subclasses Django's [`StreamingHttpResponse`](https://docs.djangoproject.com/en/6.0/ref/request-response/#django.http.StreamingHttpResponse). Django 4.2 or later is required.

## Nested parts

`MultipartResponse` accepts `Part`, `MultipartPart`, and nested `Multipart` values:

```python
from multipart_response.fastapi import HTMLPart, Multipart, TextPart

alternative = Multipart(
    [TextPart("Plain text"), HTMLPart("<p>HTML</p>")],
    subtype="alternative",
)
```

A sequence is buffered. A sync or async iterable streams.

## htmx

The [hx-multipart](https://four.htmx.org/extensions/hx-multipart) extension swaps each part as it arrives. Set `HX-Target` and `HX-Swap` on that part.

## Core

The dependency-free core exports `Multipart`, `MultipartPart`, and `MultipartWriter`.

- Boundaries and MIME headers are validated against RFC 2046 limits.
- Body chunks are checked for boundary collisions.
- Static, streamed, and nested multipart content is supported.

## License

BSD-3-Clause
