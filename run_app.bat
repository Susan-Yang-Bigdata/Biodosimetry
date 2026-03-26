@echo off
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo [오류] Python "py" 런처를 찾을 수 없습니다.
  echo python.org 에서 Python 3.11+ 설치 후 "Add python.exe to PATH" 옵션을 켜 주세요.
  pause
  exit /b 1
)

echo 패키지 확인 중...
py -3 -m pip install -q streamlit pypdf
if errorlevel 1 (
  echo [오류] pip 설치 실패
  pause
  exit /b 1
)

echo.
echo 브라우저가 자동으로 안 뜨면 주소창에 입력: http://127.0.0.1:8501
echo 종료: 이 창에서 Ctrl+C
echo.

py -3 -m streamlit run "%~dp0app.py" --server.address 127.0.0.1 --server.port 8501

pause
