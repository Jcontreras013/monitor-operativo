@echo off
REM ==============================================================================
REM Arranca telegram_bot.py y lo reinicia solo si se cae por cualquier error,
REM guardando toda la salida en log_telegram_bot.txt para poder revisar despues
REM que paso. Pensado para lanzarse oculto via iniciar_telegram_bot_oculto.vbs
REM (ver ese archivo para dejarlo arrancando solo al iniciar Windows).
REM ==============================================================================
cd /d "%~dp0"

:loop
echo. >> log_telegram_bot.txt
echo ============================================================ >> log_telegram_bot.txt
echo Arrancando bot: %date% %time% >> log_telegram_bot.txt
echo ============================================================ >> log_telegram_bot.txt
py telegram_bot.py >> log_telegram_bot.txt 2>&1
echo Bot terminado o se cayo, reiniciando en 10 segundos... >> log_telegram_bot.txt
timeout /t 10 /nobreak > nul
goto loop
