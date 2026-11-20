@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Instalando o necessario (so na primeira vez)...
python -m pip install -q -r requirements.txt
echo.
echo Abrindo o LembraMed! no navegador...
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:5000"
echo Deixe esta janela aberta enquanto usar o LembraMed!. Para parar, feche-a.
echo.
python app.py
pause
