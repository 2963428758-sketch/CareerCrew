"""附件校验模块单元测试（T3.1 §14.1）：扩展名/MIME/magic 签名/大小 校验矩阵。

纯函数 validate_attachment：正常化扩展名与 MIME 白名单映射、magic-byte 校验、
25MB 上限。伪造扩展名 / 伪造 MIME / 签名不符 / 超大 一律拒绝。
"""
from __future__ import annotations

import pytest

from careercrew_core.conversation.validation import (
    EXTENSION_WHITELIST,
    MIME_TO_EXTENSION,
    AttachmentValidationError,
    MAX_ATTACHMENT_SIZE,
    validate_attachment,
)

# ── magic-byte 样本（与 validation.SIGNATURES 对齐）──
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8
PDF = b"%PDF-1.7" + b"\x00" * 8
ZIP = b"PK\x03\x04" + b"\x00" * 8   # DOCX/PPTX/XLSX


# ── 扩展名白名单 ──

def test_extension_whitelist_exact():
    assert EXTENSION_WHITELIST == {
        ".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt", ".png", ".jpg", ".jpeg",
    }


def test_mime_to_extension_mapping_exact():
    assert MIME_TO_EXTENSION == {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/markdown": ".md",
        "text/plain": ".txt",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
    }


# ── 通过矩阵 ──

@pytest.mark.parametrize("filename,mime,head", [
    ("resume.pdf", "application/pdf", PDF),
    ("report.DOCX", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ZIP),
    ("deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", ZIP),
    ("sheet.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ZIP),
    ("notes.md", "text/markdown", b"# title\n"),
    ("notes.txt", "text/plain", b"hello"),
    ("photo.png", "image/png", PNG),
    ("photo.jpg", "image/jpeg", JPEG),
    ("photo.jpeg", "image/jpeg", JPEG),
])
def test_validate_accepts_valid(filename, mime, head):
    result = validate_attachment(filename, mime, head, size=100)
    assert result["extension"] in EXTENSION_WHITELIST
    assert result["mime"] == mime


# ── 拒绝矩阵 ──

def test_rejects_unknown_extension():
    with pytest.raises(AttachmentValidationError):
        validate_attachment("virus.exe", "application/pdf", PDF, size=10)


def test_rejects_double_extension_spoof():
    with pytest.raises(AttachmentValidationError):
        validate_attachment("note.txt.pdf", "application/pdf", b"plain text", size=10)


def test_rejects_extension_mime_mismatch():
    # .pdf 扩展名却声称 image/png
    with pytest.raises(AttachmentValidationError):
        validate_attachment("x.pdf", "image/png", PNG, size=10)


def test_rejects_signature_mismatch_pdf():
    # .pdf + application/pdf 但内容是 PNG 签名
    with pytest.raises(AttachmentValidationError):
        validate_attachment("x.pdf", "application/pdf", PNG, size=10)


def test_rejects_signature_mismatch_docx():
    # .docx + docx MIME 但内容不是 ZIP(PK)
    with pytest.raises(AttachmentValidationError):
        validate_attachment("x.docx",
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            b"not a zip at all", size=10)


def test_rejects_oversize_exact_boundary():
    # 恰好 25MB 是允许的；25MB+1 拒绝
    validate_attachment("big.pdf", "application/pdf", PDF, size=MAX_ATTACHMENT_SIZE)
    with pytest.raises(AttachmentValidationError):
        validate_attachment("big.pdf", "application/pdf", PDF, size=MAX_ATTACHMENT_SIZE + 1)


def test_rejects_empty_filename():
    with pytest.raises(AttachmentValidationError):
        validate_attachment("", "application/pdf", PDF, size=10)


def test_rejects_no_extension():
    with pytest.raises(AttachmentValidationError):
        validate_attachment("noext", "application/pdf", PDF, size=10)


def test_rejects_jpeg_signature_mismatch():
    # .jpg + image/jpeg 但内容是 PNG
    with pytest.raises(AttachmentValidationError):
        validate_attachment("x.jpg", "image/jpeg", PNG, size=10)


def test_text_requires_decodable_utf8():
    # 文本类无 magic 签名：verdict 由扩展名+MIME+可解码校验决定
    with pytest.raises(AttachmentValidationError):
        validate_attachment("x.txt", "text/plain", b"\xff\xfe\x00\x80", size=10)


# ── 归一化 ──

def test_normalizes_uppercase_extension_and_untrusted_mime():
    result = validate_attachment("A.JPEG", "IMAGE/JPEG", JPEG, size=10)
    assert result["extension"] == ".jpeg"
    # MIME 归一化到白名单键（小写）
    assert result["mime"] == "image/jpeg"
