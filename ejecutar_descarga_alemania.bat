@echo off
chcp 65001 >nul
title STATER - DESCARGADOR INSTITUCIONAL ALEMANIA (BAFIN / ESEF)
color 0B
echo =========================================================================
echo === STATER MOTOR ARGOS - DESCARGADOR INSTITUCIONAL ALEMANIA (BAFIN)  ===
echo =========================================================================
echo Conector Oficial: BaFin / ESEF (filings.xbrl.org) + Unternehmensregister
echo Universo Maestro: 1.011 Sociedades Cotizadas (Prime, General, Scale, Freiverkehr)
echo Destino Canónico: D:\ARGOS_DATA\raw\DE_BAFIN
echo =========================================================================
echo.

if "%~1"=="" (
    python ARGOS_MOTOR\descarga\de_germany\downloader_bafin.py --years 2020,2021,2022,2023,2024
) else (
    python ARGOS_MOTOR\descarga\de_germany\downloader_bafin.py %*
)

echo.
echo =========================================================================
echo Ingesta Alemania finalizada con éxito.
echo =========================================================================
pause
