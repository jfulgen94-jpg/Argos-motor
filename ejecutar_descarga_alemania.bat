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
echo [DEPRECATED][LEGACY_BRIDGE][KEEP_UNTIL_MIGRATION_COMPLETE] Este lanzador usa el descargador Track A (DE/BAFIN).
echo Ruta unificada: ejecutar_ingesta_unificada.bat ^<AUTORIDAD^> --years ... --provider ... (ver audits\FASE4_UNIFICACION_2026-10-09)
echo El descubrimiento (crawling) de este pais aun no esta migrado; por eso sigue activo. No escribe via .part.
echo.

python -u ARGOS_MOTOR\descarga\de_germany\downloader_bafin.py %*

echo.
echo =========================================================================
echo Ingesta Alemania completada con éxito.
echo =========================================================================
pause
