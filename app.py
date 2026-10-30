import os
import sqlite3
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.getenv("DATABASE_PATH", BASE_DIR / "data" / "app.db"))
AI_API_KEY = os.getenv("ARK_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
AI_MODEL = os.getenv("AI_MODEL", "doubao-seed-1-6-flash-250828")
APP_VERSION = os.getenv("APP_VERSION", "v1.0.0")

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


def get_db():
    if "db" not in g:
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idea TEXT NOT NULL,
            result TEXT NOT NULL,
            model TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.commit()


@app.get("/")
def index():
    return render_template("index.html", version=APP_VERSION)


@app.get("/health")
def health():
    db = get_db()
    db.execute("SELECT 1").fetchone()
    return jsonify(
        status="ok",
        database="ok",
        model_configured=bool(AI_API_KEY),
        version=APP_VERSION,
    )


@app.get("/api/history")
def history():
    rows = get_db().execute(
        "SELECT id, idea, result, model, created_at FROM analyses ORDER BY id DESC LIMIT 10"
    ).fetchall()
    return jsonify(items=[dict(row) for row in rows])


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}
    idea = str(payload.get("idea", "")).strip()
    if not idea:
        return jsonify(error="请先输入一个 AI 应用想法。"), 400
    if len(idea) < 4:
        return jsonify(error="输入内容太短，请至少写 4 个字符。"), 400
    if len(idea) > 1000:
        return jsonify(error="输入内容不能超过 1000 个字符。"), 400
    if not AI_API_KEY:
        return jsonify(error="服务器尚未配置 ARK_API_KEY，暂未调用模型。"), 503

    started = time.perf_counter()
    try:
        response = requests.post(
            f"{AI_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {AI_API_KEY}"},
            json={
                "model": AI_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是严谨的产品分析助手。用中文输出：一句话定位、目标用户、最小可行功能（3项）、首要风险。不要编造已有成果。",
                    },
                    {"role": "user", "content": idea},
                ],
                "temperature": 0.3,
                "max_tokens": 500,
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        result = data["choices"][0]["message"]["content"].strip()
        if not result:
            raise ValueError("empty model response")
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
        return jsonify(error="模型服务暂时不可用，请稍后重试或检查服务端配置。"), 502

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    db = get_db()
    cursor = db.execute(
        "INSERT INTO analyses (idea, result, model) VALUES (?, ?, ?)",
        (idea, result, AI_MODEL),
    )
    db.commit()
    record = db.execute(
        "SELECT id, idea, result, model, created_at FROM analyses WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return jsonify(item=dict(record), elapsed_ms=elapsed_ms)


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify(error="接口不存在。"), 404
    return "页面不存在", 404


@app.errorhandler(500)
def internal_error(_error):
    if request.path.startswith("/api/"):
        return jsonify(error="服务器内部错误，请查看服务端日志。"), 500
    return "服务器内部错误", 500


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8000")), debug=False)
