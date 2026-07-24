# multipart-response

Stream one HTTP response as multiple MIME parts. For Django, FastAPI, FastHTML, and Starlette.

## FastAPI

```console
uv add "multipart-response[fastapi]"
```

Yield HTML shorthand and explicit parts from one path operation:

```python
from fastapi import FastAPI
from multipart_response.fastapi import HTMLMultipartResponse, HTMLPart, JSONPart, Part

app = FastAPI()


@app.get("/updates", response_class=HTMLMultipartResponse)
async def updates():
    yield "<p>Ready</p>"
    yield HTMLPart("<p>Done</p>", headers={"HX-Target": "#status"})
    yield JSONPart({"status": "ready"})
    yield Part(chunk_stream(), media_type="video/mp4")
```

- `HTMLMultipartResponse` accepts HTML strings and explicit parts.
- `Part(content, headers=..., media_type=...)` exposes `headers`, `set_cookie()`, and `delete_cookie()`.
- `MultipartResponse` accepts `status_code`, `headers`, `subtype`, `background`, and `boundary`.
- Return `MultipartResponse([...])` directly to set outer response options.

## FastHTML

```console
uv add "multipart-response[fasthtml]"
```

Return FastHTML components as streamed parts:

```python
from fasthtml.common import Div, P, fast_app
from multipart_response.fasthtml import MultipartResponse, Part

app, rt = fast_app()


@rt("/updates")
def get():
    def parts():
        yield P("Ready")
        yield Part(Div("Done"), headers={"HX-Target": "#status"})

    return MultipartResponse(parts())
```

- `MultipartResponse` renders FastHTML components, HTML strings, and explicit parts.
- `Part(component, headers=...)` defaults to HTML and sets options on one component.
- `Part` accepts `media_type`; `JSONPart` uses FastHTML's JSON serialization.
- `MultipartResponse` accepts the Starlette response options.
- Return the response directly so FastHTML does not buffer the part source.

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

The [`hx-multipart`](https://four.htmx.org/extensions/hx-multipart) extension lets one htmx request process a streaming `multipart/mixed` response. As each part arrives, its body and `HX-*` headers can swap HTML, fire events, or run other htmx response actions.

![The hx-multipart extension documentation](https://raw.githubusercontent.com/scriptogre/multipart-response/main/docs/hx-multipart.png)

The extension vendors [`fetch-multipart`](https://github.com/scriptogre/fetch-multipart), which adds `Response.prototype.parts()` and exposes each MIME part as a streaming Fetch-style `BodyPart`. `multipart-response` writes the parts on the server; `hx-multipart` parses and handles them in the browser.

Set `HX-Target` and `HX-Swap` on a part to control its swap.

FastHTML loads htmx 2 by default. Pass `htmx=False` to `fast_app()`, then load htmx 4 and `hx-multipart` as shown in the extension install guide.

## Compatibility shorthand

The Starlette and FastAPI `HTMLMultipartResponse` classes still accept `(HTML, headers)` tuples. Prefer `HTMLPart(HTML, headers=...)` in new code.

## Core

The dependency-free core exports `Multipart`, `MultipartPart`, and `MultipartWriter`.

- Boundaries and MIME headers are validated against RFC 2046 limits.
- Body chunks are checked for boundary collisions.
- Static, streamed, and nested multipart content is supported.

## License

BSD-3-Clause
