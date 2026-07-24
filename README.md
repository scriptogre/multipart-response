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

- `Part(...)` follows Django's [`HttpResponse`](https://docs.djangoproject.com/en/6.0/ref/request-response/#django.http.HttpResponse) API for content, headers, and cookies. HTML is the default content type.
- `MultipartResponse(...)` follows [`StreamingHttpResponse`](https://docs.djangoproject.com/en/6.0/ref/request-response/#django.http.StreamingHttpResponse) and adds `subtype` and `boundary`.

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

- `Part(...)` follows FastAPI's [`Response`](https://fastapi.tiangolo.com/advanced/custom-response/#response) API for content, media type, headers, and cookies.
- `MultipartResponse(...)` follows [`StreamingResponse`](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse) and adds `subtype` and `boundary`.
- Use [`response_class`](https://fastapi.tiangolo.com/advanced/custom-response/) with yielded parts, or [return the response directly](https://fastapi.tiangolo.com/advanced/response-directly/).

Stream HTML or JSON values directly when every part has one content type:

```python
from multipart_response.fastapi import HTMLMultipartResponse, JSONMultipartResponse


@app.get("/html-updates", response_class=HTMLMultipartResponse)
async def html_updates():
    yield "<p>Ready</p>"
    yield "<p>Done</p>", {"HX-Target": "#status"}


@app.get("/json-updates", response_class=JSONMultipartResponse)
async def json_updates():
    yield {"status": "ready"}, {"HX-Target": "#status"}
    yield "done"
```

`HTMLMultipartResponse` renders strings as HTML. `JSONMultipartResponse` uses FastAPI's [`jsonable_encoder()`](https://fastapi.tiangolo.com/tutorial/encoder/) and sets each part to `application/json`. The final part above contains the JSON string `"done"`, including its quotes.

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

- `Part(...)` renders FastHTML [`FT` components](https://fastcore.fast.ai/xml.html#ft) and follows Starlette's [`Response`](https://www.starlette.io/responses/#response) API. HTML is the default content type.
- `MultipartResponse(...)` follows [`StreamingResponse`](https://www.starlette.io/responses/#streamingresponse) and adds `subtype` and `boundary`.
- [Return the response directly](https://www.fastht.ml/docs/explains/routes.html) so FastHTML does not buffer a sync part source.

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

- `Part(...)` follows Starlette's [`Response`](https://www.starlette.io/responses/#response) API for content, media type, headers, and cookies.
- `MultipartResponse(...)` follows [`StreamingResponse`](https://www.starlette.io/responses/#streamingresponse) and adds `subtype` and `boundary`.

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

The [`hx-multipart`](https://four.htmx.org/extensions/hx-multipart) extension swaps each part as it arrives.

<img src="https://raw.githubusercontent.com/scriptogre/multipart-response/main/docs/hx-multipart.png" alt="The hx-multipart extension documentation" width="720">

Use [`HX-Target`, `HX-Swap`, and `HX-Select`](https://four.htmx.org/extensions/hx-multipart#hx--headers) to control each part.

It uses [`fetch-multipart`](https://github.com/scriptogre/fetch-multipart) to parse the stream.

## Core

The dependency-free core exports `Multipart`, `MultipartPart`, and `MultipartWriter`.

- Boundaries and MIME headers are validated against RFC 2046 limits.
- Body chunks are checked for boundary collisions.
- Static, streamed, and nested multipart content is supported.

## License

BSD-3-Clause
