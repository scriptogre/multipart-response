# multipart-response

Stream one HTTP response as multiple MIME parts. For Django, FastAPI, FastHTML, and Starlette.

## Integrations

Use the adapter for your web framework:

- [Django](#django)
- [FastAPI](#fastapi)
- [FastHTML](#fasthtml)
- [Starlette](#starlette)

### Django

```console
uv add "multipart-response[django]"
```

Stream parts from a Django view:

```python
from multipart_response.django import MultipartResponse, Part


def generate_report(request):
    def parts():
        yield Part(
            "<p>Generating report...</p>",
            headers={"HX-Target": "#status"},
        )
        yield Part(
            '<li><a href="/reports/42">Quarterly report</a></li>',
            headers={
                "HX-Target": "#reports",
                "HX-Swap": "beforeend",
            },
        )

    return MultipartResponse(parts())
```

- `Part(content, content_type=..., charset=..., headers=...)` defaults to HTML.
- `Part.content` contains the rendered content or stream.
- Parts support Django's header mapping, `has_header()`, `get()`, `setdefault()`, `set_cookie()`, `set_signed_cookie()`, and `delete_cookie()`.
- `MultipartResponse` accepts `status`, `reason`, `charset`, `headers`, `subtype`, and `boundary`.

Use an async part source under ASGI:

```python
async def updates(request):
    async def parts():
        yield Part("<p>Ready</p>")
        yield Part("<p>Done</p>")

    return MultipartResponse(parts())
```

Django 4.2 or later is required.

*`MultipartResponse` subclasses Django's native [`StreamingHttpResponse`](https://docs.djangoproject.com/en/6.0/ref/request-response/#django.http.StreamingHttpResponse).*

### FastAPI

```console
uv add "multipart-response[fastapi]"
```

Stream multiple content types from one path operation:

```python
import json

from fastapi import FastAPI
from multipart_response.fastapi import MultipartResponse, Part

app = FastAPI()


@app.get("/updates", response_class=MultipartResponse)
async def updates():
    yield Part("<p>Ready</p>", media_type="text/html")
    yield Part(
        json.dumps({"status": "ready"}),
        media_type="application/json",
        headers={"HX-Target": "#status"},
    )
    yield Part(chunk_stream(), media_type="video/mp4")
```

- `Part(content, headers=..., media_type=...)` exposes `headers`, `set_cookie()`, and `delete_cookie()`.
- `MultipartResponse` accepts `status_code`, `headers`, `subtype`, `background`, and `boundary`.
- Return `MultipartResponse([...])` directly to set outer response options.

Stream HTML or JSON values directly when every part has one content type:

```python
from multipart_response.fastapi import HTMLMultipartResponse, JSONMultipartResponse


@app.get("/html-updates", response_class=HTMLMultipartResponse)
async def html_updates():
    yield "<p>Ready</p>"
    yield "<p>Done</p>", {"HX-Target": "#status"}


@app.get("/json-updates", response_class=JSONMultipartResponse)
async def json_updates():
    yield {"status": "ready"}
    yield "done"
```

`HTMLMultipartResponse` renders strings as HTML. `JSONMultipartResponse` uses FastAPI's `jsonable_encoder()` before rendering each JSON part.

*`MultipartResponse` subclasses Starlette's native [`StreamingResponse`](https://www.starlette.io/responses/#streamingresponse), which FastAPI uses for streamed responses.*

### FastHTML

```console
uv add "multipart-response[fasthtml]"
```

Stream FastHTML components from a route:

```python
from fasthtml.common import Div, P, fast_app
from multipart_response.fasthtml import MultipartResponse, Part

app, rt = fast_app()


@rt("/updates")
def get():
    def parts():
        yield Part(P("Ready"))
        yield Part(Div("Done"), headers={"HX-Target": "#status"})

    return MultipartResponse(parts())
```

- `Part(component, headers=..., media_type=...)` renders FastHTML components and defaults to HTML.
- `MultipartResponse` accepts the Starlette response options.
- Return the response directly so FastHTML does not buffer a sync part source.

Stream components directly when every part is HTML:

```python
from multipart_response.fasthtml import HTMLMultipartResponse


def get():
    def parts():
        yield P("Ready")
        yield Div("Done"), {"HX-Target": "#status"}

    return HTMLMultipartResponse(parts())
```

*`MultipartResponse` subclasses Starlette's native [`StreamingResponse`](https://www.starlette.io/responses/#streamingresponse), which FastHTML uses for streamed responses.*

### Starlette

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
- `MultipartResponse` accepts `status_code`, `headers`, `subtype`, `background`, and `boundary`.

Use `HTMLMultipartResponse` to return HTML strings without wrapping each one in `Part`:

```python
from multipart_response.starlette import HTMLMultipartResponse


async def html_updates(request):
    return HTMLMultipartResponse(["<p>Ready</p>", "<p>Done</p>"])
```

*`MultipartResponse` subclasses Starlette's native [`StreamingResponse`](https://www.starlette.io/responses/#streamingresponse).*

## Nested parts

`MultipartResponse` accepts `Part`, `MultipartPart`, and nested `Multipart` values:

```python
from multipart_response.fastapi import Multipart, Part

alternative = Multipart(
    [
        Part("Plain text", media_type="text/plain"),
        Part("<p>HTML</p>", media_type="text/html"),
    ],
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

## Core

The dependency-free core exports `Multipart`, `MultipartPart`, and `MultipartWriter`.

- Boundaries and MIME headers are validated against RFC 2046 limits.
- Body chunks are checked for boundary collisions.
- Static, streamed, and nested multipart content is supported.

## License

BSD-3-Clause
