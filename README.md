# multipart-response

Stream one HTTP response as multiple parts. For Django, FastAPI, and Starlette.

## FastAPI

Install the FastAPI adapter:

```console
uv add "multipart-response[fastapi]"
```

Yield parts from an endpoint:

```python
from fastapi import FastAPI
from multipart_response.fastapi import HTMLMultipartResponse

app = FastAPI()

@app.get("/updates", response_class=HTMLMultipartResponse)
async def updates():
    yield "<p>Ready</p>"
    yield "<p>Done</p>"
```

Each part is sent when it is yielded:

```http
Content-Type: multipart/mixed; boundary=multipart-...

--multipart-...
content-length: 12
content-type: text/html; charset=utf-8

<p>Ready</p>
--multipart-...
content-length: 11
content-type: text/html; charset=utf-8

<p>Done</p>
--multipart-...--
```

The same API is available from `multipart_response.starlette`.

## Django

Install the Django adapter:

```console
uv add "multipart-response[django]"
```

Return a multipart response from a view:

```python
from multipart_response.django import HTMLMultipartResponse


def updates(request):
    def parts():
        yield "<p>Ready</p>"
        yield "<p>Done</p>"

    return HTMLMultipartResponse(parts())
```

Use an async part source when Django runs under ASGI:

```python
async def updates(request):
    async def parts():
        yield "<p>Ready</p>"
        yield "<p>Done</p>"

    return HTMLMultipartResponse(parts())
```

Django parts use Django response conventions:

```python
from multipart_response.django import HTMLPart

part = HTMLPart("<p>Ready</p>")
part["HX-Target"] = "#status"
part.headers["HX-Swap"] = "innerHTML"
part.set_cookie("seen", "yes")
```

`Part` binds Django's header, charset, and cookie methods directly. `JSONPart` uses `JsonResponse`, including `DjangoJSONEncoder` and `safe=True`.

Django 4.2 or later is required. Sync iterators suit WSGI. Async iterators suit ASGI.

## htmx

With the [hx-multipart](https://four.htmx.org/extensions/hx-multipart) extension, each part is one swap. Part headers pick the target:

```python
@app.get("/dashboard", response_class=HTMLMultipartResponse)
async def dashboard():
    yield ("<p>Ready</p>", {"HX-Target": "#status"})
    yield ("<li>New</li>", {"HX-Target": "#reports", "HX-Swap": "beforeend"})
```

The same shorthand works with Django's `HTMLMultipartResponse`.

## Other part types

Use explicit parts when one response mixes content types:

```python
from multipart_response.fastapi import JSONPart, Multipart, MultipartResponse, Part, TextPart

@app.get("/report", response_class=MultipartResponse)
async def report():
    yield TextPart("Preparing")
    yield JSONPart({"status": "ready"})
    yield Part(chunk_stream(), media_type="video/mp4")
    yield Multipart([...], subtype="alternative")
```

Import the Django versions from `multipart_response.django`. Django's `Part` uses `content_type` instead of `media_type`.

## Notes

- Return `MultipartResponse([...], status_code=..., headers=...)` with FastAPI or Starlette.
- Return `MultipartResponse([...], status=..., reason=..., headers=...)` with Django.
- The dependency-free core exports `Multipart`, `MultipartPart`, and `MultipartWriter`.
- Boundaries and headers are validated against RFC 2046 limits.
- Body chunks are checked for boundary collisions.

## License

BSD-3-Clause
