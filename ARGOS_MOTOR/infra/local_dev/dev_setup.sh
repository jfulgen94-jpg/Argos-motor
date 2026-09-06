#!/bin/bash
echo "Setting up STATER Motor Argos development environment..."
python -m venv venv
source venv/bin/activate
pip install -r STATER_MOTOR_ARGOS/requirements.txt
echo "STATER Motor Argos ready."
