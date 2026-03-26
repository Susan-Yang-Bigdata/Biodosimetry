이 폴더에 OCR할 PDF 파일을 넣으세요.

프로젝트 루트에서:
  py -3 -m pip install pymupdf ocrmypdf

디지털 PDF(웹 PDF 등, 이미 글자 선택 가능):
  py -3 ocr_pdfs.py --strategy extract
  -> ../pdfs_ocr/*_extracted.txt

스캔본까지 OCR(검색 가능 PDF 선호):
  py -3 ocr_pdfs.py
  -> ../pdfs_ocr/*_ocr.pdf (실패 시 *_ocr.txt)

필수: Tesseract 설치 후 PATH (한글 kor+eng 권장).
ocrmypdf용: Windows에서는 Ghostscript(gswin64c) 설치가 필요할 수 있습니다.
