@echo off
chcp 65001 >nul
title STATER - DESCARGADOR INSTITUCIONAL ALEMANIA (BAFIN / ESEF / UNTERNEHMENSREGISTER)
color 0E
echo =========================================================================
echo === STATER MOTOR ARGOS - DESCARGADOR INSTITUCIONAL ALEMANIA (BAFIN/ESEF) ===
echo =========================================================================
echo Conectores Oficiales: ESEF + Unternehmensregister + Bundesanzeiger (Area 22)
echo Universo Maestro: 1.011 Sociedades Cotizadas (DAX / MDAX / SDAX / TecDAX / Standards)
echo Horizonte Temporal: 2012 - 2025 (Corte 2012 Institucional)
echo Destino Canónico: D:\ARGOS_DATA\raw\DE_BAFIN
echo =========================================================================
echo.

python -u ARGOS_MOTOR\descarga\de_germany\downloader_bafin.py %*

echo.
echo =========================================================================
echo Ingesta Alemania completada con éxito.
echo =========================================================================
pause
