@echo off
title ARGOS MOTOR - DESCARGA EN VIVO 2021 (DISCO D:)
color 0A
cd /d "C:\Users\jfulg\Desktop\Stater"
echo ========================================================================
echo    ARGOS MOTOR - DESCARGA CNMV ESPANA 2021 EN DIRECTO HACIA DISCO D:
echo ========================================================================
echo.
python -u ARGOS_MOTOR/descarga/es_spain/download_es_2021.py
echo.
echo ========================================================================
echo Descarga finalizada. Puedes cerrar esta ventana.
echo ========================================================================
pause
