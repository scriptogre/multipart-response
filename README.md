# Multipart Response

Stream multipart responses from FastAPI and Starlette.

```python
from fastapi import FastAPI
from multipart_response.fastapi import HTMLMultipartResponse

app = FastAPI()


@app.get("/updates", response_class=HTMLMultipartResponse)
async def updates():
    yield "<p>Ready</p>"
    yield "<p>Done</p>"
```

## Install

Choose an adapter:

```console
uv add "multipart-response[fastapi]"
uv add "multipart-response[starlette]"
```

## Stream from FastAPI

With FastAPI 0.134.0 or later, yield each part from the path operation:

```python
from fastapi import FastAPI
from multipart_response.fastapi import JSONPart, MultipartResponse, TextPart

app = FastAPI()


@app.get("/report", response_class=MultipartResponse)
async def report():
    yield TextPart("Preparing report")
    yield JSONPart({"status": "ready"})
```

The server sends each part as it arrives:

```http
Content-Type: multipart/mixed; boundary=multipart-...

--multipart-...
content-length: 16
content-type: text/plain; charset=utf-8

Preparing report
--multipart-...
content-length: 18
content-type: application/json

{"status":"ready"}
--multipart-...--
```

Return `MultipartResponse` directly when you need to set the status or outer headers:

```python
@app.get("/summary")
async def summary() -> MultipartResponse:
    return MultipartResponse(
        [
            TextPart("Summary"),
            JSONPart({"complete": True}),
        ],
        status_code=200,
        headers={"X-Report": "summary"},
    )
```

## Target each htmx swap

Yield `(content, headers)` to set headers on one HTML part:

```python
from multipart_response.fastapi import HTMLMultipartResponse


@app.get("/dashboard", response_class=HTMLMultipartResponse)
async def dashboard():
    yield (
        "<p>Ready</p>",
        {
            "HX-Target": "#status",
            "HX-Swap": "innerHTML",
        },
    )
    yield (
        "<li>New report</li>",
        {
            "HX-Target": "#reports",
            "HX-Swap": "beforeend",
        },
    )
```

The first part replaces `#status`. The second appends to `#reports`.

## Stream one part

Pass a sync or async chunk source to `Part`:

```python
from collections.abc import AsyncIterator

from multipart_response.fastapi import MultipartResponse, Part


async def video_chunks() -> AsyncIterator[bytes]:
    yield b"first chunk"
    yield b"second chunk"


@app.get("/video", response_class=MultipartResponse)
async def video():
    yield Part(video_chunks(), media_type="video/mp4")
```

A streamed part has no automatic `Content-Length`. Text parts may yield strings, which use the part's charset.

## Nest multipart content

Yield `Multipart` to nest parts with their own subtype and boundary:

```python
from multipart_response.fastapi import HTMLPart, Multipart, MultipartResponse, TextPart


@app.get("/versions", response_class=MultipartResponse)
async def versions():
    yield Multipart(
        [
            TextPart("Plain text"),
            HTMLPart("<p>HTML</p>"),
        ],
        subtype="alternative",
    )
```

Wrap the nested entity in `Part` to add headers:

```python
yield Part(
    Multipart(
        [
            TextPart("Plain text"),
            HTMLPart("<p>HTML</p>"),
        ],
        subtype="alternative",
    ),
    headers={"Content-ID": "<versions>"},
)
```

`Part` sets the nested `Content-Type` and boundary. Multipart entities can contain streams and other multipart entities.

## Return a Starlette response

Return `MultipartResponse` from a Starlette endpoint:

```python
from multipart_response.starlette import HTMLPart, JSONPart, MultipartResponse


async def endpoint(request):
    return MultipartResponse([
        JSONPart({"title": "Example"}),
        HTMLPart("<h1>Example</h1>"),
    ])
```

Pass a sequence to buffer the body and set its outer `Content-Length`. Pass a sync or async iterable to stream it.

`MultipartResponse` requires explicit `Part`, `MultipartPart`, or `Multipart` values. `HTMLMultipartResponse` also accepts HTML strings and `(HTML, headers)` pairs. It passes explicit parts through unchanged:

```python
from multipart_response.starlette import HTMLMultipartResponse, JSONPart, TextPart

return HTMLMultipartResponse([
    "<p>HTML shorthand</p>",
    TextPart("Explicit plain text"),
    JSONPart({"status": "ready"}),
])
```

## Build a custom part

Set the media type and headers on `Part`:

```python
from multipart_response.starlette import Part

part = Part(
    b"image data",
    media_type="image/png",
    headers={"Content-ID": "<preview>"},
)

part.headers["Content-Disposition"] = 'attachment; filename="preview.png"'
part.set_cookie("preview", "ready")
```

`Part` adds `Content-Length` to static bodies. For text media types, it also adds `charset=utf-8` when no charset is set.

### Part API

| Name | Use |
| --- | --- |
| `body` | Read the rendered body or stream source. |
| `raw_headers` | Read the encoded `(name, value)` pairs. |
| `headers` | Read or change headers through Starlette's `MutableHeaders`. |
| `media_type` | Set the generated `Content-Type`. |
| `charset` | Set the text encoding. Defaults to `utf-8`. |
| `render(content)` | Render static content or keep a body stream. Override it in a subclass. |
| `render_chunk(chunk)` | Encode one string or bytes-like stream chunk. |
| `init_headers(headers)` | Build `raw_headers`. Override it in a subclass. |
| `render_headers()` | Render the header block with CRLF line endings. |
| `set_cookie(...)` | Add a `Set-Cookie` part header with Starlette's API. |
| `delete_cookie(...)` | Expire a cookie in the part headers. |
| `as_multipart_part()` | Convert to the framework-neutral `MultipartPart`. |

Set the HTTP status, outer cookies, and background task on `MultipartResponse`. A part has none of those values.

## Use the core writer

Import the dependency-free core to build static, streamed, or nested entities:

```python
from multipart_response import Multipart, MultipartPart

multipart = Multipart(
    [
        MultipartPart(
            b"hello",
            [(b"Content-Type", b"text/plain; charset=utf-8")],
        ),
    ],
    boundary="example",
)

body = multipart.render()
assert multipart.content_type == "multipart/mixed; boundary=example"
```

Use `MultipartWriter` directly when you need to call `start_part()`, `write_body()`, and `finalize()` yourself.

## Framing rules

The writer:

- Generates a boundary with 128 random bits.
- Limits boundaries to the RFC 2046 grammar and 70-byte maximum.
- Uses CRLF around each delimiter.
- Requires at least one part.
- Rejects invalid header names, values, and line lengths.
- Rejects boundary collisions across body chunks and nesting levels.
- Streams sync and async part bodies.
- Nests multipart entities recursively.
- Keeps header order and duplicate headers.
