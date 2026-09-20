#!/usr/bin/env bash
set -e

echo "=================================================="
echo "  STATER / ARGOS MOTOR — SETUP AUTOMATICO CLOUD   "
echo "=================================================="

# 1. Crear directorios canonicos
mkdir -p data/raw/DE_BAFIN data/raw/NL_AFM data/raw/ES_CNMV data/raw/FR_AMF data/raw/IT_CONSOB
mkdir -p data/staging data/quarantine data/lake/duckdb logs

# 2. Instalar dependencias Python
pip install --upgrade pip
pip install -r requirements.txt

# 3. Instalar Chromium y dependencias del sistema para Playwright
playwright install --with-deps chromium

# 4. Configurar PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

echo "=================================================="
echo "  ENTORNO PREPARADO CON EXITO                     "
echo "=================================================="
