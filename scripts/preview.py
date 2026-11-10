"""Adapter for a managed preview runner's Vite-style launch arguments.

The application itself runs with uvicorn directly; npm is not a runtime need.
"""
import argparse
import os
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", default=8000, type=int)
parser.add_argument("--strictPort", action="store_true")
args = parser.parse_args()
os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "app.main:app", "--host", args.host, "--port", str(args.port)])
