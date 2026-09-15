@echo off
chcp 65001 > nul
echo ===============================================================================
echo     STATER / ARGOS - SINCRONIZACIÓN AUTOMÁTICA AZURE DATA LAKE GEN2
echo ===============================================================================
echo.
echo Conectando con Microsoft Azure Blob Storage (Contenedor: fulgen)...
echo Subiendo en paralelo informes financieros, balances y paquetes ESEF...
echo.

python -u ARGOS_MOTOR/cloud/azure_data_lake_sync.py --max-workers 8

echo.
echo ===============================================================================
echo Sincronización finalizada. Todos los datos están asegurados en Microsoft Azure.
echo ===============================================================================
pause
