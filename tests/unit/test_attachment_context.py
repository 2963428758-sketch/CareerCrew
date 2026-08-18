from __future__ import annotations

from types import SimpleNamespace

import fitz
import openai

from careercrew_api import storage
from careercrew_api.attachment_context import describe_image
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.conversation.attachments import AttachmentStore, FakeAttachmentDb


def test_describe_image_uses_uploaded_jpeg_mime(monkeypatch, tmp_path):
    image = tmp_path / "photo.jpg"
    image.write_bytes(b"jpeg-bytes")
    captured: dict = {}

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="图中有一份简历"))]
    )

    def create(**kwargs):
        captured.update(kwargs)
        return response

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(openai, "OpenAI", lambda **_: client)
    settings = SimpleNamespace(
        vlm=SimpleNamespace(
            base_url="https://example.test/v1",
            api_key="key",
            model="vision",
        )
    )

    assert describe_image(settings, str(image), mime_type="image/jpeg") == "图中有一份简历"
    url = captured["messages"][0]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")


def test_pdf_resolution_falls_back_to_pymupdf(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "L", storage.layout(tmp_path))
    runtime = CareerCrewRuntime()
    runtime._initialized = True
    runtime.attachment_store = AttachmentStore(FakeAttachmentDb())
    runtime.settings = SimpleNamespace()
    runtime.ingest_pipeline = SimpleNamespace()
    runtime.attachment_store.create(
        "t-1",
        "u-1",
        "report.pdf",
        "u-1/t-1/att-1",
        "application/pdf",
        9,
        attachment_id="att-1",
    )
    path = storage.L.attachments / "u-1" / "t-1" / "att-1"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"pdf-bytes")

    monkeypatch.setattr(
        runtime,
        "extract_document_text",
        lambda *_: (_ for _ in ()).throw(RuntimeError("MinerU unavailable")),
    )

    class FakePage:
        def get_text(self, mode):
            assert mode == "text"
            return "PDF fallback text"

    class FakeDocument:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return iter([FakePage()])

        def close(self):
            pass

    monkeypatch.setattr(fitz, "open", lambda _: FakeDocument())

    blocks = runtime.resolve_attachment_blocks("u-1", [{"id": "att-1"}])

    assert blocks == [{
        "id": "att-1",
        "filename": "report.pdf",
        "kind": "document",
        "content": "PDF fallback text",
    }]
