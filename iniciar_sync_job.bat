@echo off
REM ==============================================================================
REM Arranca el robot de sincronizacion (sync_job.py) y lo vuelve a arrancar
REM solo si se cae, guardando toda la salida en log_sync.txt.
REM Pensado para lanzarse oculto con iniciar_sync_job_oculto.vbs (ver ese
REM archivo para dejarlo arrancando solo al iniciar Windows).
REM
REM Espera 5 minutos antes de volver a arrancarlo: cada arranque consulta a
REM Cepheus, que solo permite 5 consultas por hora.
REM ==============================================================================
cd /d "%~dp0"

:loop
echo. >> log_sync.txt
echo ============================================================ >> log_sync.txt
echo Arrancando robot: %date% %time% >> log_sync.txt
echo ============================================================ >> log_sync.txt
py sync_job.py >> log_sync.txt 2>&1
echo Robot terminado o se cayo: %date% %time%. Se vuelve a arrancar en 5 minutos... >> log_sync.txt
timeout /t 300 /nobreak > nul
goto loop
