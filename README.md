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

## Return a FastAPI response

Return `MultipartResponse` directly from a path operation:

```python
from fastapi import FastAPI
from multipart_response.fastapi import JSONPart, MultipartResponse, TextPart

app = FastAPI()


@app.get("/report", response_class=MultipartResponse)
async def report() -> MultipartResponse:
    return MultipartResponse([
        JSONPart({"status": "ready"}),
        TextPart("Report complete"),
    ])
```

The response uses `multipart/mixed` and includes a generated boundary:

```http
Content-Type: multipart/mixed; boundary=multipart-...

--multipart-...
content-type: application/json

{"status":"ready"}
--multipart-...
content-type: text/plain; charset=utf-8

Report complete
--multipart-...--
```

FastAPI uses `response_class` to document `multipart/mixed` in OpenAPI. The response returned by the path operation supplies the runtime boundary.

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

## Customize a part

```python
from multipart_response.starlette import Part

part = Part(
    b"image data",
    media_type="image/png",
    headers={"Content-ID": "<preview>"},
)
```

Part headers describe the enclosed representation. HTTP response properties such as status codes, cookies, and background tasks belong to the outer `MultipartResponse`.

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
