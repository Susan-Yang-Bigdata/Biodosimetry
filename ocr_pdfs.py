"""
폴더 안의 PDF를 OCR 또는 텍스트 추출 처리합니다.

기본 입력:  data/pdfs_to_ocr/*.pdf
기본 출력:  data/pdfs_ocr/<원본이름>_ocr.pdf  (ocrmypdf 성공 시)
            실패 시: data/pdfs_ocr/<원본이름>_ocr.txt  (PyMuPDF + Tesseract)

--strategy extract:
  Tesseract 없이 page.get_text() 만 사용 (디지털 PDF·웹 PDF에 적합).

실행 (프로젝트 루트):
  py -3 -m pip install pymupdf ocrmypdf
  py -3 ocr_pdfs.py
  py -3 ocr_pdfs.py --strategy extract
  py -3 ocr_pdfs.py --tesseract "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import fitz


def _list_pdfs(folder: Path) -> list[Path]:
    """Windows 등 대소문자 구분 없는 파일시스템에서 중복 경로를 제거합니다."""
    seen: set[Path] = set()
    out: list[Path] = []
    for p in sorted(folder.glob("*.pdf")) + sorted(folder.glob("*.PDF")):
        key = p.resolve()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return sorted(out, key=lambda x: x.name.lower())


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def _find_tesseract_exe(explicit: Path | None) -> Path | None:
    """PATH 또는 Windows 기본 설치 경로에서 tesseract 실행 파일을 찾습니다."""
    if explicit is not None:
        p = explicit.expanduser().resolve()
        return p if p.is_file() else None
    w = _which("tesseract")
    if w:
        return Path(w).resolve()
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(key)
        if not base:
            continue
        cand = Path(base) / "Tesseract-OCR" / "tesseract.exe"
        if cand.is_file():
            return cand.resolve()
    return None


def _prepend_path(dir_path: Path) -> None:
    """ocrmypdf·하위 프로세스가 tesseract를 찾도록 PATH 앞에 폴더를 붙입니다."""
    prev = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{dir_path}{os.pathsep}{prev}"


def _ensure_tessdata_env(tesseract_exe: Path) -> None:
    """tessdata 폴더가 있으면 TESSDATA_PREFIX 를 설정합니다."""
    tessdata = tesseract_exe.parent / "tessdata"
    if tessdata.is_dir():
        os.environ["TESSDATA_PREFIX"] = str(tessdata)


def _extract_digital_text_to_txt(src: Path, dst_txt: Path) -> None:
    """OCR 없이 이미 들어 있는 텍스트만 페이지별로 저장합니다."""
    doc = fitz.open(src)
    chunks: list[str] = []
    for i in range(len(doc)):
        page = doc[i]
        body = page.get_text()
        chunks.append(f"===== 페이지 {i + 1} / {len(doc)} =====\n{body.strip()}\n")
    dst_txt.write_text("\n".join(chunks), encoding="utf-8")


def _ocr_pdf_with_ocrmypdf(src: Path, dst: Path, language: str) -> int:
    cmd = [
        sys.executable,
        "-m",
        "ocrmypdf",
        "--language",
        language,
        "--force-ocr",
        "--optimize",
        "0",
        "--jobs",
        "1",
        str(src),
        str(dst),
    ]
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL)
    return int(proc.returncode)


def _ocr_pdf_to_txt_pymupdf(src: Path, dst_txt: Path, language: str, min_keep_chars: int) -> None:
    doc = fitz.open(src)
    chunks: list[str] = []
    for i in range(len(doc)):
        page = doc[i]
        existing = page.get_text()
        if len(existing.strip()) >= min_keep_chars:
            body = existing
        else:
            tp = page.get_textpage_ocr(dpi=300, full=True, language=language)
            body = tp.extractText(sort=True)
        chunks.append(f"===== 페이지 {i + 1} / {len(doc)} =====\n{body.strip()}\n")
    dst_txt.write_text("\n".join(chunks), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="폴더 내 PDF 일괄 OCR / 텍스트 추출")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/pdfs_to_ocr"),
        help="PDF가 있는 폴더 (기본: data/pdfs_to_ocr)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/pdfs_ocr"),
        help="결과 저장 폴더 (기본: data/pdfs_ocr)",
    )
    parser.add_argument(
        "--language",
        default="kor+eng",
        help="Tesseract 언어 코드 (기본: kor+eng)",
    )
    parser.add_argument(
        "--min-keep-chars",
        type=int,
        default=40,
        help="txt OCR 폴백 시, 이만큼 글자가 있으면 기존 텍스트 유지",
    )
    parser.add_argument(
        "--strategy",
        choices=("ocr", "extract"),
        default="ocr",
        help="ocr: Tesseract+ocrmypdf 우선 | extract: 텍스트 레이어만 추출(스캔본엔 빈 약)",
    )
    parser.add_argument(
        "--tesseract",
        type=Path,
        default=None,
        help="tesseract.exe 전체 경로 (PATH에 없을 때)",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent
    in_dir = (root / args.input).resolve() if not args.input.is_absolute() else args.input
    out_dir = (root / args.output).resolve() if not args.output.is_absolute() else args.output

    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdfs = _list_pdfs(in_dir)
    if not pdfs:
        sys.stderr.write(
            "PDF가 없습니다. 아래 폴더에 PDF를 넣은 뒤 다시 실행하세요.\n"
            f"  {in_dir}\n"
        )
        return 2

    if args.strategy == "extract":
        for src in pdfs:
            dst_txt = out_dir / f"{src.stem}_extracted.txt"
            _extract_digital_text_to_txt(src, dst_txt)
            print(f"[추출 TXT] {src.name} -> {dst_txt.name}")
        print(f"완료(텍스트 레이어만): {len(pdfs)}개 -> {out_dir}")
        return 0

    tess = _find_tesseract_exe(args.tesseract)
    if tess is None:
        sys.stderr.write(
            "Tesseract 실행 파일을 찾지 못했습니다 (PATH 및 Program Files 확인).\n"
            "  --tesseract \"경로\\tesseract.exe\" 로 지정하거나,\n"
            "  디지털 PDF면: py -3 ocr_pdfs.py --strategy extract\n"
            "Windows 설치: https://github.com/UB-Mannheim/tesseract/wiki\n"
        )
        return 3

    _prepend_path(tess.parent)
    _ensure_tessdata_env(tess)

    ok_pdf = 0
    ok_txt = 0
    for src in pdfs:
        stem = src.stem
        dst_pdf = out_dir / f"{stem}_ocr.pdf"
        dst_txt = out_dir / f"{stem}_ocr.txt"

        rc = _ocr_pdf_with_ocrmypdf(src, dst_pdf, args.language)
        if rc == 0 and dst_pdf.is_file():
            print(f"[PDF] {src.name} -> {dst_pdf.name}")
            ok_pdf += 1
            continue

        sys.stderr.write(
            f"[경고] ocrmypdf 실패(rc={rc}): {src.name}\n"
            "Ghostscript 미설치/경로 문제일 수 있습니다. PyMuPDF로 txt 폴백합니다.\n"
        )
        _ocr_pdf_to_txt_pymupdf(src, dst_txt, args.language, args.min_keep_chars)
        print(f"[TXT] {src.name} -> {dst_txt.name}")
        ok_txt += 1

    print(f"완료: 검색 가능 PDF {ok_pdf}개, OCR/혼합 txt {ok_txt}개 -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
