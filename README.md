# 생물학적 선량평가 의사결정 지원 (Streamlit 프로토타입)

규칙 기반(`rules.json`)과 설계 원칙(`data/guidelines.json`)을 연결해, 방사선 비상 시나리오 입력에 대해 **우선순위·방향·검사 옵션·주의**를 정리해 보여 주는 **연구용** 웹 화면입니다.  
(국제 문헌·간행물 제목 등에는 영어 표기가 그대로 나오는 경우가 많습니다. 본 앱 본문은 **생물학적 선량평가**로 통일합니다.)  
**선별·계획 지원**이며 최종 의학적 판단이 아닙니다. 머신러닝·영상 분석은 포함하지 않습니다.  
현재 규칙은 문헌 인용 전 **`needs_confirmation`** 으로 표시됩니다.

## 필요 환경

- Python 3.11 이상 권장 (Windows에서는 `py -3` 로 실행 가능)

## 설치

프로젝트 폴더에서:

```bash
py -3 -m pip install streamlit pypdf
```

(`py` 대신 `python` 이 통하는 환경이면 `python` 으로 바꿔도 됩니다.)

## 실행

반드시 **이 폴더**(`app.py`, `rules.json` 이 있는 위치)에서 실행합니다.

```bash
py -3 -m streamlit run app.py
```

브라우저가 자동으로 안 뜨면 주소창에 **http://127.0.0.1:8501** 을 입력합니다.

Windows에서는 `run_app.bat` 을 더블클릭해도 됩니다.

## 파일 역할

| 파일 | 설명 |
|------|------|
| `app.py` | Streamlit 화면: **권고 요약 우선**, 근거·다음 조치·불확실성·GP·탭 |
| `recommendation_helpers.py` | 권고 카드·왜?·다음 조치·불확실성·PDF 검색어(규칙 id별 문장 편집 가능) |
| `rules.json` | 규칙 정의(`guideline_refs` 로 GP 원칙과 연결) |
| `data/guidelines.json` | 설계 원칙 GP01–GP05(공식 문서 직접 인용 아님 — 대조 후 갱신) |
| `rule_engine.py` | 규칙·지침 읽기, 매칭, 결과 합성 |
| `data/sample_scenarios.json` | 입력 예시(참고용) |
| `pdf_lookup.py` | PDF 텍스트 추출·키워드 발췌(ML/OCR 없음) |

## PDF 일괄 OCR (검색 가능 PDF / 텍스트)

1. OCR할 파일을 `data/pdfs_to_ocr/` 에 복사합니다.  
2. 설치: `py -3 -m pip install pymupdf ocrmypdf` (또는 `py -3 -m pip install .[ocr]` — `pyproject.toml`에 optional 그룹이 있을 때)  
3. 실행: `py -3 ocr_pdfs.py`  
4. 결과: `data/pdfs_ocr/` 에 `원본이름_ocr.pdf` (ocrmypdf 성공 시). 실패 시 같은 이름의 `_ocr.txt` (PyMuPDF+Tesseract).

**필수:** Tesseract가 PATH에 있어야 합니다(Windows는 [UB Mannheim 빌드](https://github.com/UB-Mannheim/tesseract/wiki) 등, `kor+eng` 권장).  
ocrmypdf는 **Ghostscript**가 없으면 PDF 출력이 실패할 수 있으며, 그때는 자동으로 txt 폴백합니다.

## PDF 조회 탭

앱 상단 탭 **「PDF 지침 조회」**에서 PDF를 올리고 키워드로 페이지별 발췌를 볼 수 있습니다.  
규칙 엔진(`rules.json`)과 **자동 연동되지는 않으며**, 인용·근거 확인용 보조 창입니다. 스캔 PDF는 텍스트가 거의 없을 수 있습니다.

## 규칙·지침 수정 요령

- `rules.json`: 각 규칙은 `when`(조건), `then`(결과), `guideline_refs`(예: `["GP03","GP05"]`), `evidence_status` 를 둡니다.  
- `data/guidelines.json`: `principles` 배열의 `id` 가 규칙의 `guideline_refs` 와 맞아야 합니다.  
- 조건은 **모두 만족**할 때 규칙이 발화합니다. 패턴은 `rule_engine.py` 주석을 참고하세요.
