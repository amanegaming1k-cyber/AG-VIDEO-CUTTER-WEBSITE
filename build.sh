#!/usr/bin/env bash
set -e
pip install -r requirements.txt
# Render's standard Python image is Debian/Ubuntu based.
apt-get update
apt-get install -y ffmpeg
ffmpeg -version | head -n 1
