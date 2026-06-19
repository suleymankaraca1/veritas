"""
VERITAS Flask Server
Starts all agents and exposes the /analyze endpoint.
"""
import json
import logging
import os
import re
import sys
import threading
from datetime import date

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# Add utils and agents packages to path (for Render and local)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─── IP RATE LIMITING ─────────────────────────────────────
_rl_lock = threading.Lock()
_rl_store: dict = {}  # ip -> {"date": "YYYY-MM-DD", "count": N}
DAILY_LIMIT = 5


def _get_client_ip() -> str:
    """X-Forwarded-For varsa ilk IP'yi al, yoksa remote_addr kullan."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _check_rate_limit(ip: str) -> tuple[bool, int]:
    """Returns (allowed, remaining). Thread-safe."""
    today = str(date.today())
    with _rl_lock:
        rec = _rl_store.get(ip)
        if not rec or rec["date"] != today:
            _rl_store[ip] = {"date": today, "count": 1}
            return True, DAILY_LIMIT - 1
        if rec["count"] >= DAILY_LIMIT:
            return False, 0
        rec["count"] += 1
        return True, DAILY_LIMIT - rec["count"]
# ──────────────────────────────────────────────────────────

import agents.gateway as gateway
import agents.orchestrator as orchestrator
import agents.researcher_master as researcher_master
import agents.researcher_b as researcher_b
import agents.researcher_c as researcher_c
import agents.researcher_d as researcher_d
import agents.source_validator as source_validator
import agents.reporter as reporter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "veritas-dev")

CORS(app, resources={r"/api/*": {"origins": "*"}})


@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


def _start_all_agents():
    """Starts all agents in background threads."""
    logger.info("Tüm ajanlar başlatılıyor...")
    gateway.start()
    orchestrator.start()
    researcher_master.start()
    researcher_b.start()
    researcher_c.start()
    researcher_d.start()
    source_validator.start()
    reporter.start()
    logger.info("Tüm ajanlar başlatıldı.")


def _parse_report(raw: str) -> dict:
    """Gateway'den gelen ham rapor metnini parse eder."""
    # Extract JSON block if present (legacy format compatibility)
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # New format: extract the text block after FINAL_REPORT
    idx = raw.upper().find("FINAL_REPORT")
    if idx != -1:
        eol = raw.find("\n", idx)
        text = raw[eol:].strip() if eol != -1 else ""
        if text:
            return {"text": text}

    return {"raw": raw}


@app.route("/api/analyze", methods=["POST"])
def analyze():
    # Rate limiting
    client_ip = _get_client_ip()
    allowed, remaining = _check_rate_limit(client_ip)
    if not allowed:
        logger.warning(f"[RATE LIMIT] {client_ip} günlük limite ulaştı")
        return jsonify({
            "error": f"Günlük istek limitine ulaştınız ({DAILY_LIMIT} istek/gün). Yarın tekrar deneyin."
        }), 429

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON gövdesi bekleniyor"}), 400

    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "text alanı boş olamaz"}), 400

    if len(text) > 5000:
        return jsonify({"error": "Metin 5000 karakteri geçemez"}), 400

    # Strip HTML tags (XSS protection)
    text = re.sub(r"<[^>]+>", "", text).strip()
    if not text:
        return jsonify({"error": "Geçerli metin bulunamadı"}), 400

    logger.info(f"[API] /analyze isteği: ip={client_ip}, kalan_hak={remaining}, uzunluk={len(text)}")

    result = gateway.analyze(text)

    if result is None:
        return jsonify({"error": "Doğrulama zaman aşımına uğradı (900s). Tekrar deneyin."}), 504

    report_raw = result.get("report", "")
    parsed = _parse_report(report_raw)

    return jsonify({
        "task_id": result.get("task_id"),
        "report": parsed,
        "raw": report_raw,
    })


FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


@app.route("/", methods=["GET"])
@app.route("/<path:filename>", methods=["GET"])
def index(filename="index.html"):
    return send_from_directory(FRONTEND, filename)


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "VERITAS"})


if __name__ == "__main__":
    _start_all_agents()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
