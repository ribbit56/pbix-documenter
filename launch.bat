@echo off
cd /d "%~dp0"
py -m streamlit run app.py --server.headless true --server.port 8501 --browser.gatherUsageStats false --server.maxUploadSize 500
pause
