"""Serves the frontend directory on port 3456."""
import http.server
import os

FRONTEND_DIR = r"C:\Users\suley\Desktop\veritas\frontend"

print(f"Serving from: {FRONTEND_DIR}")
print(f"index.html exists: {os.path.exists(os.path.join(FRONTEND_DIR, 'index.html'))}")

os.chdir(FRONTEND_DIR)
handler = http.server.SimpleHTTPRequestHandler
httpd = http.server.HTTPServer(("", 3456), handler)
print("Serving frontend on http://localhost:3456")
httpd.serve_forever()
