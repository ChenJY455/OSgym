#!/bin/bash

echo "Killing OSGym..."
sudo pkill -f "python main.py"
sudo pkill -f "python3 main.py"
sudo pkill -f "docker"