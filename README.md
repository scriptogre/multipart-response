# Multipart Response

Build and stream multipart HTTP responses with a dependency-free writer and adapters for Python web frameworks.

The first release supports Starlette and FastAPI. Django support is planned.

## Install

For Starlette:

```console
uv add "multipart-response[starlette]"
```

For FastAPI:

```console
uv add "multipart-response[fastapi]"
```

## Stream parts from FastAPI

FastAPI 0.134.0 and later can stream values yielded by a path operation into the declared response class:

```python
from fastapi import FastAPI
from multipart_response.fastapi import JSONPart, MultipartResponse, TextPart

app = FastAPI()


@app.get("/report", response_class=MultipartResponse)
async def report():
    yield TextPart("Preparing report")
    yield JSONPart({"status": "ready"})
```

FastAPI passes the async iterable to `MultipartResponse`, which writes each part as it arrives. The response uses `multipart/mixed` and includes a generated boundary:

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

You can also construct and return a response directly. Use this form to set response options or when the parts already come from another iterable:

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

## Target each htmx update

Each part has its own headers. An htmx client can use those headers to swap each HTML fragment into a different target:

```python
from multipart_response.fastapi import HTMLPart, MultipartResponse


@app.get("/dashboard", response_class=MultipartResponse)
async def dashboard():
    yield HTMLPart(
        "<p>Ready</p>",
        headers={
            "HX-Target": "#status",
            "HX-Swap": "innerHTML",
        },
    )
    yield HTMLPart(
        "<li>New report</li>",
        headers={
            "HX-Target": "#reports",
            "HX-Swap": "beforeend",
        },
    )
```

The first part updates `#status`. The second appends an item to `#reports`. The outer HTTP response still has one status code and one set of response headers, while each part controls its own swap.

## Return a Starlette response

```python
from multipart_response.starlette import HTMLPart, JSONPart, MultipartResponse


async def endpoint(request):
    return MultipartResponse([
        JSONPart({"title": "Example"}),
        HTMLPart("<h1>Example</h1>"),
    ])
```

`MultipartResponse` accepts:

- A sequence, which is buffered and receives an outer `Content-Length`.
- A synchronous iterable, which Starlette runs in its thread pool.
- An asynchronous iterable, which streams directly.

Strings become `TextPart`, dictionaries become `JSONPart`, and bytes-like values use `application/octet-stream`.

## Customize a Starlette part

`Part` follows Starlette's response conventions for rendering content and managing headers:

```python
from multipart_response.starlette import Part

part = Part(
    b"image data",
    media_type="image/png",
    headers={"Content-ID": "<preview>"},
)

part.headers["Content-Disposition"] = 'attachment; filename="preview.png"'
```

A part automatically adds `Content-Length`. Text media types also receive `charset=utf-8` unless the media type already declares a charset.

### Part API

- `body` contains the rendered bytes or memory view.
- `raw_headers` contains the encoded `(name, value)` header pairs.
- `headers` provides Starlette's mutable `MutableHeaders` interface.
- `media_type` and `charset` control the generated `Content-Type`.
- `render(content)` converts content into bytes and can be overridden by subclasses.
- `init_headers(headers)` builds `raw_headers` and can be overridden by subclasses.
- `render_headers()` returns the complete part header block with CRLF line endings.
- `set_cookie(...)` and `delete_cookie(...)` use the same signatures as Starlette's `Response` methods and add `Set-Cookie` fields to the part.
- `as_multipart_part()` returns the framework-neutral `MultipartPart` representation.

A part has no HTTP status code or background task. Those belong to the outer `MultipartResponse`. Cookies set on a part are part headers and are not cookies on the outer HTTP response.

## Use the writer directly

The core package has no runtime dependencies:

```python
from multipart_response import MultipartPart, MultipartWriter

writer = MultipartWriter(boundary="example")
body = writer.render([
    MultipartPart(
        b"hello",
        [(b"Content-Type", b"text/plain; charset=utf-8")],
    ),
])

content_type = writer.content_type("mixed")
```

A writer is single-use. Create a new writer for each multipart message.

## Protocol behavior

The writer:

- Generates boundaries with 128 bits of randomness.
- Validates the RFC 2046 boundary grammar and 70-byte limit.
- Emits CRLF around delimiter lines.
- Requires at least one body part.
- Validates MIME header names, values, and line lengths.
- Rejects boundary collisions, including collisions split across body chunks.
- Preserves header order and duplicates in `MultipartPart`.

Framework-specific part classes handle value rendering. The core writer handles multipart framing.
