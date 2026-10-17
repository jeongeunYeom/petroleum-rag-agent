from __future__ import annotations

import asyncio

import httpx
from PIL import Image

from app.core.config import Settings
from app.services.ollama import OllamaClient


def test_image_request_has_room_for_image_tokens_and_equation_prompt(tmp_path, monkeypatch):
    image_path = tmp_path / "equation.png"
    Image.new("RGB", (300, 180), "white").save(image_path)
    captured = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, json):
            captured.update(json)
            return httpx.Response(
                200,
                json={"message": {"content": "equation_text: Q = k*A*dP/(l*mu)"}},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr("app.services.ollama.httpx.AsyncClient", lambda **_kwargs: FakeClient())
    response = asyncio.run(
        OllamaClient(Settings(data_dir=tmp_path)).describe_image(
            image_path, prompt="Verify the visible equation", num_predict=500,
        )
    )

    assert "equation_text" in response
    assert captured["options"]["num_ctx"] >= 8192
    assert captured["options"]["num_predict"] == 500
    assert captured["messages"][0]["images"]
