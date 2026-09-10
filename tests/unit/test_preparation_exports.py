import importlib
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

import fitz
import pytest


@pytest.fixture
def exports():
    try:
        return importlib.import_module("careercrew_core.preparation.exports")
    except ModuleNotFoundError:
        return None


def test_pdf_preserves_chinese_long_lines_and_all_pages(exports):
    assert exports is not None, "简历 PDF/DOCX 导出尚未实现"
    paragraphs = [f"第{i:03d}段：负责中文简历与后端接口开发，保证数据准确。" for i in range(180)]
    content = "\n".join(paragraphs) + "\n" + "长行内容" * 250 + "全文结束标记"
    data = exports.export_pdf("岗位专属简历", content)
    assert data.startswith(b"%PDF")
    with fitz.open(stream=data, filetype="pdf") as doc:
        assert len(doc) >= 4
        recovered = "".join(page.get_text() for page in doc).replace("\n", "").replace(" ", "")
        assert all(paragraph in recovered for paragraph in paragraphs)
        assert "长行内容" * 250 + "全文结束标记" in recovered
        assert all(page.get_text().strip() for page in doc)


def test_docx_is_valid_and_contains_full_original_text(exports):
    assert exports is not None, "简历 PDF/DOCX 导出尚未实现"
    content = "工作经历\n" + "研发中文系统，保留 <标签> & 内容。\n" * 300 + "最后一段"
    data = exports.export_docx("接口开发版", content)
    with ZipFile(BytesIO(data)) as doc:
        assert "[Content_Types].xml" in doc.namelist()
        root = ElementTree.fromstring(doc.read("word/document.xml"))
        text = "".join(root.itertext())
        assert "接口开发版" in text
        assert text.count("研发中文系统，保留 <标签> & 内容。") == 300
        assert "最后一段" in text
