# multipart-response

Stream one HTTP response as multiple parts. For FastAPI and Starlette.

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

Each part is sent the moment it is yielded:

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

## htmx

With the [hx-multipart](https://four.htmx.org/extensions/hx-multipart) extension, each part is one swap. Part headers pick the target:

```python
@app.get("/dashboard", response_class=HTMLMultipartResponse)
async def dashboard():
    yield ("<p>Ready</p>", {"HX-Target": "#status"})
    yield ("<li>New</li>", {"HX-Target": "#reports", "HX-Swap": "beforeend"})
```

## Other part types

```python
from multipart_response.fastapi import JSONPart, Multipart, MultipartResponse, Part, TextPart

@app.get("/report", response_class=MultipartResponse)
async def report():
    yield TextPart("Preparing")
    yield JSONPart({"status": "ready"})
    yield Part(chunk_stream(), media_type="video/mp4")  # streamed body
    yield Multipart([...], subtype="alternative")       # nested parts
```

## Notes

- `Part` follows Starlette conventions: `headers`, `set_cookie()`, `media_type`.
- Return `MultipartResponse([...], status_code=..., headers=...)` to set the envelope.
- Same API from Starlette: `multipart_response.starlette`. Core writer (`MultipartWriter`) is dependency-free.
- Boundaries and headers are validated (RFC 2046). Body chunks are checked for boundary collisions.

## License

BSD-3-Clause
