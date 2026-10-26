import os
import re
import json
import uuid
import shutil
import threading
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, abort

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("AG_DATA_DIR", "/tmp/ag-video-cutter"))
JOBS = DATA / "jobs"
JOBS.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(2 * 1024**3)))
# This is an application-level guard, not a promise that the host can process this size.
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # each chunk should be <= 4 MiB
lock = threading.Lock()
states = {}

def job_dir(job_id):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
        abort(400, description="Invalid job ID.")
    return JOBS / job_id

def state(job_id, **updates):
    with lock:
        states.setdefault(job_id, {"status": "uploading", "progress": 0, "message": "Uploading…", "detail": ""})
        states[job_id].update(updates)
        return dict(states[job_id])

def get_state(job_id):
    with lock:
        return dict(states.get(job_id, {"status":"error","error":"Job not found or server restarted. Uploads on free hosting may be temporary."}))

def safe_name(name):
    name = Path(name or "video").name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return (name or "video")[:120]

def run_probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=90
    )
    if result.returncode != 0:
        raise RuntimeError("FFprobe could not read this video. It may be corrupt or unsupported.")
    try:
        duration = float(result.stdout.strip())
    except (ValueError, TypeError):
        raise RuntimeError("Could not determine video duration.")
    if duration <= 0:
        raise RuntimeError("Video duration is invalid.")
    return duration

def process_job(job_id, filename):
    folder = job_dir(job_id)
    source = folder / "source.upload"
    try:
        state(job_id, status="processing", progress=5, message="Checking video…", detail="FFprobe is reading the video duration.")
        duration = run_probe(source)
        part_duration = duration / 4.0
        parts = []
        # Re-encoding gives cuts at the requested time boundaries but may be slow on free CPU.
        for i in range(4):
            start = i * part_duration
            out = folder / f"part_{i+1}.mp4"
            state(job_id, status="processing", progress=8 + i * 21, message=f"Encoding part {i+1} of 4…",
                  detail="FFmpeg is processing on the server. Large files may exceed free-host limits.")
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{start:.6f}", "-i", str(source), "-t", f"{part_duration:.6f}",
                "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                "-avoid_negative_ts", "make_zero", str(out)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60)
            if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
                reason = (result.stderr or "FFmpeg failed").strip()[-1200:]
                raise RuntimeError(f"FFmpeg could not create part {i+1}. {reason}")
            parts.append({"filename": out.name, "duration": format_duration(part_duration),
                          "url": f"/api/download/{job_id}/{out.name}"})
        state(job_id, status="done", progress=100, message="All four parts are ready.", detail="Download each part below.", parts=parts)
    except subprocess.TimeoutExpired:
        state(job_id, status="error", error="Processing timed out. Try a shorter or smaller video, or use a server with more CPU/time.")
    except Exception as exc:
        state(job_id, status="error", error=str(exc)[:1800])
    # Do not auto-delete successful outputs immediately; temporary host storage may still disappear on restart.

def format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

@app.get("/")
def index():
    return send_from_directory(ROOT, "index.html")

@app.get("/<path:path>")
def static_files(path):
    if path in {"index.html", "style.css", "app.js"}:
        return send_from_directory(ROOT, path)
    abort(404)

@app.get("/api/health")
def health():
    return jsonify({"service":"AG VIDEO CUTTER","status":"running","ffmpeg":shutil.which("ffmpeg") is not None})

@app.post("/api/start")
def start():
    body = request.get_json(silent=True) or {}
    try:
        size = int(body.get("size", 0))
    except (TypeError, ValueError):
        return jsonify(error="Invalid file size."), 400
    if size <= 0:
        return jsonify(error="Empty file."), 400
    if size > MAX_UPLOAD_BYTES:
        return jsonify(error=f"File is larger than configured upload cap ({MAX_UPLOAD_BYTES} bytes)."), 413
    job_id = uuid.uuid4().hex
    folder = job_dir(job_id)
    folder.mkdir(parents=True, exist_ok=False)
    state(job_id, status="uploading", progress=0, message="Uploading video…", detail="Waiting for chunks.")
    (folder / "meta.json").write_text(json.dumps({"filename": safe_name(body.get("filename")), "size": size}), encoding="utf-8")
    return jsonify(job_id=job_id, chunk_size=4 * 1024 * 1024)

@app.post("/api/upload/<job_id>/<int:index>")
def upload_chunk(job_id, index):
    folder = job_dir(job_id)
    if not folder.exists():
        return jsonify(error="Job not found. Start a new upload."), 404
    chunk = request.files.get("chunk")
    if not chunk:
        return jsonify(error="No chunk was received."), 400
    if index < 0 or index > 10000:
        return jsonify(error="Invalid chunk index."), 400
    chunk_dir = folder / "chunks"
    chunk_dir.mkdir(exist_ok=True)
    chunk_path = chunk_dir / f"{index:06d}.part"
    chunk.save(chunk_path)
    return jsonify(ok=True, index=index)

@app.post("/api/upload/<job_id>/complete")
def complete_upload(job_id):
    folder = job_dir(job_id)
    if not folder.exists():
        return jsonify(error="Job not found."), 404
    body = request.get_json(silent=True) or {}
    try:
        expected = int(body.get("total_chunks", 0))
        expected_size = int(body.get("size", 0))
    except (TypeError, ValueError):
        return jsonify(error="Invalid upload metadata."), 400
    if expected < 1 or expected > 10001:
        return jsonify(error="Invalid number of chunks."), 400
    chunks = folder / "chunks"
    source = folder / "source.upload"
    try:
        with source.open("wb") as output:
            total = 0
            for i in range(expected):
                part = chunks / f"{i:06d}.part"
                if not part.exists():
                    raise RuntimeError(f"Chunk {i+1} is missing. Please upload again.")
                with part.open("rb") as src:
                    shutil.copyfileobj(src, output, 1024 * 1024)
                    total += part.stat().st_size
        if total != expected_size:
            source.unlink(missing_ok=True)
            return jsonify(error=f"Upload size mismatch ({total} bytes received, {expected_size} expected)."), 400
        shutil.rmtree(chunks, ignore_errors=True)
        meta_path = folder / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        filename = safe_name(body.get("filename") or meta.get("filename") or "video")
        state(job_id, status="processing", progress=2, message="Upload complete…", detail="Starting FFmpeg.")
        threading.Thread(target=process_job, args=(job_id, filename), daemon=True).start()
        return jsonify(ok=True)
    except Exception as exc:
        return jsonify(error=str(exc)), 400

@app.get("/api/status/<job_id>")
def status(job_id):
    return jsonify(get_state(job_id))

@app.get("/api/download/<job_id>/<path:filename>")
def download(job_id, filename):
    if not re.fullmatch(r"part_[1-4]\.mp4", filename or ""):
        abort(400)
    folder = job_dir(job_id)
    path = folder / filename
    if not path.is_file():
        abort(404, description="Output file not found. The free host may have restarted and cleared temporary files.")
    return send_from_directory(folder, filename, as_attachment=True, download_name=filename, mimetype="video/mp4")

@app.errorhandler(413)
def too_large(_):
    return jsonify(error="Request too large. Upload in smaller chunks; check hosting request limits."), 413

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
