"""
PDF 텍스트 추출 + 단순 키워드 조회.

- 머신러닝·벡터 DB·OCR 없음: ‘선택한 PDF 안에서 글자를 찾는’ 수준입니다.
- 스캔 PDF(이미지만 있는 문서)는 추출 텍스트가 비어 있을 수 있습니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader


def is_pdf_blob(data: bytes) -> bool:
    """파일 앞부분이 PDF 표준 시그니처인지 확인합니다."""
    return len(data) >= 5 and data[:5] == b"%PDF-"


@dataclass(frozen=True)
class PdfPageText:
    """한 페이지에서 읽어 낸 텍스트."""

    page_index1: int
    text: str


@dataclass(frozen=True)
class PdfDocumentText:
    """한 개 PDF 파일 전체."""

    file_name: str
    pages: tuple[PdfPageText, ...]


def load_pdf_text(*, file_name: str, data: bytes) -> PdfDocumentText:
    """
    PDF 바이트에서 페이지별 텍스트를 뽑습니다.

    사전 조건: data 가 비어 있지 않고, is_pdf_blob(data) 가 참이어야 합니다.
    """
    if not data:
        raise ValueError("파일 데이터가 비어 있습니다.")
    if not is_pdf_blob(data):
        raise ValueError("PDF 형식이 아닙니다(%PDF- 헤더 없음).")

    reader = PdfReader(BytesIO(data))
    built: list[PdfPageText] = []
    for i, page in enumerate(reader.pages):
        raw = page.extract_text()
        text = raw if isinstance(raw, str) else ""
        built.append(PdfPageText(page_index1=i + 1, text=text))
    return PdfDocumentText(file_name=file_name, pages=tuple(built))


def total_char_count(doc: PdfDocumentText) -> int:
    return sum(len(p.text) for p in doc.pages)


def snippets_for_query(
    doc: PdfDocumentText,
    query: str,
    *,
    context_chars: int = 200,
    max_snippets_per_page: int = 3,
) -> list[tuple[int, str]]:
    """
    질의 문자열이 포함된 페이지와, 주변 문맥 일부를 돌려줍니다.

    대소문자 구분 없음. 공백만 있는 질의는 결과 없음.
    """
    q = query.strip()
    if not q:
        return []

    needle = q.lower()
    hits: list[tuple[int, str]] = []

    for p in doc.pages:
        hay = p.text.lower()
        if needle not in hay:
            continue

        start_search = 0
        count = 0
        full_text = p.text
        while count < max_snippets_per_page:
            idx = hay.find(needle, start_search)
            if idx < 0:
                break
            a = max(0, idx - context_chars)
            b = min(len(full_text), idx + len(q) + context_chars)
            chunk = full_text[a:b].replace("\n", " ")
            hits.append((p.page_index1, chunk))
            count += 1
            start_search = idx + max(1, len(needle))

    return hits
