#!/bin/bash

echo "Restarting OSGym..."
pkill -f "python3 main.py"
pkill -f "docker"

echo "Activating conda environment..."
conda activate osgym

echo "Starting OSGym..."
nohup python3 main.py > logs/output.log 2>&1 &
