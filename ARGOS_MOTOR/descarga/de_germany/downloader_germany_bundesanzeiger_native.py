#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STATER / ARGOS MOTOR — Bundesanzeiger Native Ingestion Wrapper
==============================================================
Punto de entrada canónico para la descarga de balances históricos (2012–2022)
mediante la librería abierta oficial: `deutschland.bundesanzeiger`.

Invoca la lógica implementada en `crawler_bundesanzeiger_hrb.py`.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from crawler_bundesanzeiger_hrb import main

if __name__ == "__main__":
    main()
