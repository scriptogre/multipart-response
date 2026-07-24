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

Return explicit parts from a view:

```python
from multipart_response.django import MultipartResponse, Part


def updates(request):
    def parts():
        yield Part("<p>Ready</p>")
        yield Part("<p>Done</p>")

    return MultipartResponse(parts())
```

`Part` uses Django's `content`, `content_type`, `charset`, and `headers` conventions. HTML is the default content type, as it is for Django's `HttpResponse`.

Set headers on one part through its constructor or `headers`:

```python
part = Part(
    "<p>Ready</p>",
    headers={"HX-Target": "#status"},
)
part.headers["HX-Swap"] = "innerHTML"
```

Serialize Python data with Django's `JsonResponse` rules:

```python
from multipart_response.django import JsonPart

part = JsonPart({"status": "ready"})
```

Use an async part source when Django runs under ASGI:

```python
async def updates(request):
    async def parts():
        yield Part("<p>Ready</p>")
        yield Part("<p>Done</p>")

    return MultipartResponse(parts())
```

`MultipartResponse` subclasses Django's [`StreamingHttpResponse`](https://docs.djangoproject.com/en/6.0/ref/request-response/#django.http.StreamingHttpResponse), so Django handles it like any other streaming response.

Django 4.2 or later is required. Sync iterators suit WSGI. Async iterators suit ASGI.

## htmx

With the [hx-multipart](https://four.htmx.org/extensions/hx-multipart) extension, each part is one swap. Part headers pick the target:

```python
@app.get("/dashboard", response_class=HTMLMultipartResponse)
async def dashboard():
    yield ("<p>Ready</p>", {"HX-Target": "#status"})
    yield ("<li>New</li>", {"HX-Target": "#reports", "HX-Swap": "beforeend"})
```

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

Django's `Part` uses `content_type` instead of `media_type`.

## Notes

- Return `MultipartResponse([...], status_code=..., headers=...)` with FastAPI or Starlette.
- Return `MultipartResponse([...], status=..., reason=..., headers=...)` with Django.
- The dependency-free core exports `Multipart`, `MultipartPart`, and `MultipartWriter`.
- Boundaries and headers are validated against RFC 2046 limits.
- Body chunks are checked for boundary collisions.

## License

BSD-3-Clause
