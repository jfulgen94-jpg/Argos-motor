@echo off
chcp 65001 >nul
title STATER - DESCARGADOR INSTITUCIONAL ESPAÑA (CNMV / ESEF)
color 0B
echo =========================================================================
echo === STATER MOTOR ARGOS - DESCARGADOR INSTITUCIONAL ESPAÑA (CNMV/ESEF) ===
echo =========================================================================
echo Conectores Oficiales: CNMV (ListadoIFA/EEFF) + ESEF (filings.xbrl.org)
echo Universo Maestro: 378 Sociedades Cotizadas (IBEX 35 / Continuo / Growth / SOCIMIs)
echo Destino Canónico: D:\ARGOS_DATA\raw\ES_CNMV
echo =========================================================================
echo.

python ARGOS_MOTOR\descarga\es_spain\run_download_spain.py %*

echo.
echo =========================================================================
echo Ingesta completada con éxito.
echo =========================================================================
pause
