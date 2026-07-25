import os
import sys

# Ensure this file's own directory (flask_app/) is on sys.path so the local
# "app" package resolves regardless of how the runtime imports this module
# (Vercel's Python runtime imports main.py via importlib rather than running
# it as a script, so the automatic sys.path[0] insertion doesn't happen).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
