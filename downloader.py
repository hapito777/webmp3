"""Shared yt-dlp download logic and logger for web and bot."""
import logging
import tempfile
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yt_dlp

DOWNLOADS_DIR = Path(tempfile.gettempdir()) / "mp3_app_downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _setup_logger() -> logging.Logger:
    log = logging.getLogger("mp3")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    log.addHandler(stream)
    file_h = RotatingFileHandler(LOGS_DIR / "history.log", maxBytes=1_000_000, backupCount=5)
    file_h.setFormatter(fmt)
    log.addHandler(file_h)
    return log


logger = _setup_logger()


class DownloadError(Exception):
    pass


def download_mp3(url: str, *, source: str = "web", who: str = "?"):
    """Download `url` to mp3. Returns (mp3_path, info_dict).

    Raises DownloadError on yt-dlp failure or missing output file.
    `source` is "web" or "telegram"; `who` is the requester id (IP / user id).
    """
    job_id = uuid.uuid4().hex
    out_template = str(DOWNLOADS_DIR / f"{job_id}.%(ext)s")
    logger.info("request url=%r source=%s who=%s job=%s", url, source, who, job_id)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        logger.warning("download failed url=%r job=%s source=%s error=%r", url, job_id, source, str(e))
        raise DownloadError(str(e)) from e

    mp3_path = DOWNLOADS_DIR / f"{job_id}.mp3"
    if not mp3_path.exists():
        logger.error("mp3 not produced url=%r job=%s source=%s", url, job_id, source)
        raise DownloadError("mp3 file was not produced (is ffmpeg installed?)")

    title = info.get("title", "audio")
    duration = info.get("duration")
    size_bytes = mp3_path.stat().st_size
    logger.info(
        "success title=%r duration=%s size=%d job=%s source=%s url=%r",
        title, duration, size_bytes, job_id, source, url,
    )
    return mp3_path, {
        "job_id": job_id,
        "title": title,
        "duration": duration,
        "size": size_bytes,
    }
