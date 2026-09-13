@echo off
chcp 65001 >nul
echo =========================================================================
echo === STATER MOTOR ARGOS - DESCARGADOR INSTITUCIONAL ALEMANIA (BAFIN)  ===
echo =========================================================================
echo Conector OAM: Unternehmensregister / BaFin / ESEF
echo Universo: DAX 40 / MDAX / SDAX (master_universe_de.json)
echo Destino Canónico: D:\ARGOS_DATA\raw\DE_BAFIN
echo =========================================================================

python ARGOS_MOTOR\descarga\de_germany\downloader_bafin.py %*

echo.
echo Proceso finalizado.
pause
