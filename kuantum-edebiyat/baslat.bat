@echo off
chcp 65001 >nul
pip install -r requirements.txt
set /p GEMINI_API_KEY=Gemini API anahtarini yapistirin: 
start http://127.0.0.1:5000
python app.py
pause
