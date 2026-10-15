"""Standard-library-only smoke test of Nyan ID PNG upload and Bot API multipart."""
from __future__ import annotations

import ast
import json
import secrets
import struct
import types
import urllib.request
import zlib
from pathlib import Path
from unittest.mock import patch


class FakeHTTPException(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail


def load_functions() -> dict:
    path = Path("server/nyan_id.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_validate_exported_png", "_telegram_send_png"}
    ]
    assert len(functions) == 2, "Nyan ID export functions missing"
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *functions,
        ],
        type_ignores=[],
    )
    runtime = {
        "struct": struct,
        "zlib": zlib,
        "secrets": secrets,
        "json": json,
        "urllib": __import__("urllib"),
        "core": types.SimpleNamespace(BOT_TOKEN="TEST_NOT_REAL_BOT_TOKEN"),
        "HTTPException": FakeHTTPException,
        "_MAX_PNG_BYTES": 3 * 1024 * 1024,
    }
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), runtime)
    return runtime


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def sample_png(width: int = 1200, height: int = 780) -> bytes:
    png = bytes.fromhex("89504e470d0a1a0a")
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    rows = (b"\\x00" + b"\\xF0\\xDE\\xE8\\xFF" * width) * height
    return (
        png
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(rows, level=6))
        + png_chunk(b"IEND", b"")
    )


def test_png_validation(namespace: dict, valid: bytes) -> None:
    check = namespace["_validate_exported_png"]
    check(valid)

    malformed = [
        sample_png(width=1199),
        valid[:-1],
        valid + b"extra",
        b"JPEG" + valid[4:],
        valid[:38] + bytes([valid[38] ^ 1]) + valid[39:],
        valid + b"X" * (3 * 1024 * 1024),
    ]
    for candidate in malformed:
        try:
            check(candidate)
        except FakeHTTPException:
            pass
        else:
            raise AssertionError("Malformed PNG was accepted")
    print("Nyan ID PNG validation: OK")


def test_telegram_multipart(namespace: dict, valid: bytes) -> None:
    def check_request(request, timeout):
        assert request.full_url.endswith("/sendDocument")
        assert request.get_header("Content-type").startswith("multipart/form-data; boundary=")
        assert timeout <= 20
        boundary = request.get_header("Content-type").split("boundary=", 1)[1]
        payload = request.data
        assert payload.startswith(("--" + boundary + "\\r\\n").encode())
        assert payload.endswith(("--" + boundary + "--\\r\\n").encode())
        assert (
            b'Content-Disposition: form-data; name="chat_id"\\r\\n\\r\\n12345\\r\\n'
            in payload
        )
        assert b'Content-Disposition: form-data; name="caption"\\r\\n\\r\\n' in payload
        assert (
            b'Content-Disposition: form-data; name="document"; '
            b'filename="Nyan-ID-NW-ABCD-EFGH.png"\\r\\n'
            b'Content-Type: image/png\\r\\n\\r\\n'
            in payload
        )
        assert payload.count(valid) == 1

        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, *_): return b'{"ok":true,"result":{"message_id":42}}'

        return FakeResponse()

    with patch("urllib.request.urlopen", side_effect=check_request):
        message_id = namespace["_telegram_send_png"](
            12345, "NW-ABCD-EFGH", valid
        )
        assert message_id == 42
    print("Nyan ID Telegram sendDocument multipart: OK")


if __name__ == "__main__":
    symbols = load_functions()
    sample = sample_png()
    test_png_validation(symbols, sample)
    test_telegram_multipart(symbols, sample)
