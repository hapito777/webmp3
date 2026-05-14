import io
import re

from flask import Flask, jsonify, render_template, request, send_file

from downloader import DOWNLOADS_DIR, DownloadError, download_mp3, logger

app = Flask(__name__)


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\s\-.()]", "", name).strip()
    return cleaned[:120] or "audio"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
    if not url:
        logger.warning("request rejected reason=empty_url source=web who=%s", client_ip)
        return jsonify({"error": "URL is required"}), 400

    try:
        _mp3_path, info = download_mp3(url, source="web", who=client_ip)
    except DownloadError as e:
        return jsonify({"error": f"Download failed: {e}"}), 400
    except Exception as e:
        logger.exception("unexpected error url=%r source=web", url)
        return jsonify({"error": f"Unexpected error: {e}"}), 500

    return jsonify({"file_id": info["job_id"], "title": info["title"]})


@app.route("/file/<file_id>")
def file_download(file_id):
    if not re.fullmatch(r"[a-f0-9]{32}", file_id):
        return "invalid id", 400
    mp3_path = DOWNLOADS_DIR / f"{file_id}.mp3"
    if not mp3_path.exists():
        return "not found", 404

    title = request.args.get("title", "audio")
    safe_title = sanitize_filename(title)

    buf = io.BytesIO(mp3_path.read_bytes())
    mp3_path.unlink(missing_ok=True)
    logger.info("delivered job=%s filename=%r bytes=%d", file_id, f"{safe_title}.mp3", len(buf.getvalue()))

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{safe_title}.mp3",
        mimetype="audio/mpeg",
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
