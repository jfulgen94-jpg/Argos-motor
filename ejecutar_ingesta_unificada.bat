@echo off
chcp 65001 >nul
title STATER - INGESTA UNIFICADA (ruta unica)
rem Uso: ejecutar_ingesta_unificada.bat --authority BAFIN --years 2020 --provider eqs:ARGOS_MOTOR\config\eqs_verified_links.json [--dry-run]
rem Requiere ARGOS_DATA_ROOT (p.ej. D:\ARGOS_DATA) o --data-root. Sin rutas relativas ni defaults implicitos.
cd /d "%~dp0ARGOS_MOTOR"
python -m mod_01_ingestion.src.unified.cli %*
