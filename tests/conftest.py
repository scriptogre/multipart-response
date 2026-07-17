from __future__ import annotations

from dataclasses import dataclass

from python_multipart import MultipartParser


@dataclass
class ParsedPart:
    headers: list[tuple[bytes, bytes]]
    body: bytes


def parse_multipart(
    body: bytes,
    boundary: bytes | str,
    *,
    chunk_size: int | None = None,
) -> list[ParsedPart]:
    parts: list[ParsedPart] = []
    headers: list[tuple[bytes, bytes]] = []
    current_body = bytearray()
    header_name = bytearray()
    header_value = bytearray()

    def on_part_begin() -> None:
        headers.clear()
        current_body.clear()

    def on_header_field(data: bytes, start: int, end: int) -> None:
        header_name.extend(data[start:end])

    def on_header_value(data: bytes, start: int, end: int) -> None:
        header_value.extend(data[start:end])

    def on_header_end() -> None:
        headers.append((bytes(header_name), bytes(header_value)))
        header_name.clear()
        header_value.clear()

    def on_part_data(data: bytes, start: int, end: int) -> None:
        current_body.extend(data[start:end])

    def on_part_end() -> None:
        parts.append(ParsedPart(list(headers), bytes(current_body)))

    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": on_part_begin,
            "on_header_field": on_header_field,
            "on_header_value": on_header_value,
            "on_header_end": on_header_end,
            "on_part_data": on_part_data,
            "on_part_end": on_part_end,
        },
    )

    if chunk_size is None:
        parser.write(body)
    else:
        for offset in range(0, len(body), chunk_size):
            parser.write(body[offset : offset + chunk_size])
    parser.finalize()

    return parts
