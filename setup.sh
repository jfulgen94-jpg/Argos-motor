#!/usr/bin/env bash
set -e

echo "=================================================="
echo "  STATER / ARGOS MOTOR — SETUP AUTOMATICO CLOUD   "
echo "=================================================="

# 1. Crear directorios canonicos
mkdir -p data/raw/DE_BAFIN data/raw/NL_AFM data/raw/ES_CNMV data/raw/FR_AMF data/raw/IT_CONSOB
mkdir -p data/staging data/quarantine data/lake/duckdb logs

# 2. Instalar dependencias Python sin saturar la cuota de disco
pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt

# 3. Configurar navegadores en /tmp para NO sobrecargar la cuota de OSS de Alibaba Cloud
export PLAYWRIGHT_BROWSERS_PATH=/tmp/pw-browsers
mkdir -p /tmp/pw-browsers

# 4. Configurar PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

echo "=================================================="
echo "  ENTORNO PREPARADO CON EXITO                     "
echo "=================================================="
