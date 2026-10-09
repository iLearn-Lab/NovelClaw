"""Check JavaScript shipped as static assets (Node.js 20+ required)."""

from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
for script in sorted(root.glob("apps/*/local_web_portal/app/static/*.js")):
    subprocess.run(["node", "--check", str(script)], check=True)
print("Static JavaScript syntax checks passed.")
