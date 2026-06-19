"""Minimal static file server for frontend preview."""
from flask import Flask, send_from_directory
import os

FRONTEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
app = Flask(__name__)

@app.route("/")
@app.route("/<path:filename>")
def serve(filename="index.html"):
    return send_from_directory(FRONTEND, filename)

if __name__ == "__main__":
    print(f"Serving: {FRONTEND}")
    app.run(host="0.0.0.0", port=3456, debug=False)
