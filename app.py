"""4i-Clips: AI video clipper + multi-account scheduler (Streamlit).

Optional secrets (Streamlit Cloud -> App settings -> Secrets):
    YT_PROXY        = "http://user:pass@host:port"   # residential proxy, most reliable fix for 403s
    COBALT_API_URL  = "https://your-cobalt-host/"    # self-hosted Cobalt v10 API (fallback)
    COBALT_API_KEY  = "..."                          # only if your Cobalt instance needs one
"""
import shutil
import subprocess
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
import streamlit as st
import yt_dlp
from yt_dlp.utils import DownloadError

st.set_page_config(page_title="4i-Clips", page_icon="🎬", layout="wide")

REQUIRED_COLS = ["platform", "username", "password_or_token"]
MIN_TAIL_SECONDS = 5  # don't create a final clip shorter than this
# Tried in order. None = yt-dlp defaults. Update this list as yt-dlp/YouTube change.
YTDLP_CLIENT_ATTEMPTS = [["tv"], ["web_safari"], ["mweb"], None]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def secret(name, default=None):
    """Read a Streamlit secret without crashing when no secrets file exists."""
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def workdir() -> Path:
    """Per-session scratch folder, so concurrent users never overwrite each other."""
    if "workdir" not in st.session_state:
        st.session_state.workdir = tempfile.mkdtemp(prefix="4iclips_")
    return Path(st.session_state.workdir)


def clips_dir() -> Path:
    d = workdir() / "clips"
    d.mkdir(exist_ok=True)
    return d


def list_clips() -> list[Path]:
    return sorted(clips_dir().glob("clip_*.mp4"))


def clear_sources():
    for p in workdir().glob("source.*"):
        p.unlink(missing_ok=True)


def reset_clips():
    for p in clips_dir().iterdir():
        p.unlink(missing_ok=True)
    (workdir() / "all_clips.zip").unlink(missing_ok=True)


def set_source(path: Path):
    st.session_state.source = str(path)
    reset_clips()


def find_source(folder: Path):
    ok = [
        p for p in folder.glob("source.*")
        if p.suffix.lower() not in {".part", ".ytdl", ".tmp"} and p.stat().st_size > 10_000
    ]
    return max(ok, key=lambda p: p.stat().st_size) if ok else None


def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse(url.strip()).hostname or "").lower()
    except ValueError:
        return False
    return host.endswith("youtube.com") or host == "youtu.be" or host.endswith(".youtu.be")


# ----------------------------------------------------------------------------
# Download layer: yt-dlp (+proxy) -> Cobalt API -> friendly failure
# ----------------------------------------------------------------------------
def try_ytdlp(url: str, folder: Path, log: list):
    proxy = secret("YT_PROXY")
    for clients in YTDLP_CLIENT_ATTEMPTS:
        clear_sources()
        opts = {
            "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
            "merge_output_format": "mp4",
            "outtmpl": str(folder / "source.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 30,
            "max_filesize": 2 * 1024**3,
        }
        if proxy:
            opts["proxy"] = proxy
        if clients:
            opts["extractor_args"] = {"youtube": {"player_client": clients}}
        label = ",".join(clients) if clients else "default"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except DownloadError as e:
            log.append(f"yt-dlp [{label}]: {str(e)[:200]}")
            continue
        except Exception as e:  # unexpected extractor/ffmpeg errors
            log.append(f"yt-dlp [{label}] unexpected: {str(e)[:200]}")
            continue
        found = find_source(folder)
        if found:
            return found
        log.append(f"yt-dlp [{label}]: finished but no file was produced")
    return None


def try_cobalt(url: str, folder: Path, log: list):
    api = secret("COBALT_API_URL")
    if not api:
        log.append("Cobalt fallback not configured (COBALT_API_URL missing)")
        return None
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    key = secret("COBALT_API_KEY")
    if key:
        headers["Authorization"] = f"Api-Key {key}"
    try:
        r = requests.post(api, json={"url": url, "videoQuality": "720"}, headers=headers, timeout=30)
        data = r.json()
        if data.get("status") not in ("tunnel", "redirect") or "url" not in data:
            log.append(f"Cobalt: {str(data)[:200]}")
            return None
        clear_sources()
        target = folder / "source.mp4"
        with requests.get(data["url"], stream=True, timeout=60) as dl:
            dl.raise_for_status()
            with open(target, "wb") as f:
                for chunk in dl.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
        return find_source(folder)
    except (requests.RequestException, ValueError) as e:
        log.append(f"Cobalt: {str(e)[:200]}")
        return None


def download_video(url: str, folder: Path, log: list):
    return try_ytdlp(url, folder, log) or try_cobalt(url, folder, log)


# ----------------------------------------------------------------------------
# Clipping layer (FFmpeg)
# ----------------------------------------------------------------------------
def probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def build_starts(total: float, clip_len: int, max_clips: int) -> list[int]:
    starts, t = [], 0
    while t < total and len(starts) < max_clips:
        if not starts or total - t >= MIN_TAIL_SECONDS:
            starts.append(t)
        t += clip_len
    return starts


def make_clip(src: str, dst: Path, start: int, dur: int, vertical_crop: bool):
    if vertical_crop:
        # Center-crop to 9:16 (safe for landscape AND already-vertical sources)
        vf = "crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)',scale=1080:1920,setsar=1"
    else:
        # Keep full frame, pad to 9:16 instead of stretching
        vf = ("scale=1080:1920:force_original_aspect_ratio=decrease,"
              "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1")
    cmd = [
        "ffmpeg", "-y", "-ss", str(start), "-i", src, "-t", str(dur),
        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", str(dst),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    ok = res.returncode == 0 and dst.exists() and dst.stat().st_size > 1000
    return ok, res.stderr[-300:]


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
st.title("🎬 4i-Clips: Bulk AI Clipper & Multi-Account Scheduler")
tab1, tab2, tab3 = st.tabs(["1. Generate Clips", "2. Manage Accounts", "3. Schedule & Queue"])

# --- TAB 1 -------------------------------------------------------------------
with tab1:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        st.error("FFmpeg not found. Add a file named `packages.txt` containing `ffmpeg` to the repo root and reboot the app.")

    st.subheader("Source video")
    source_type = st.radio("Source", ["YouTube link", "Upload video file"], horizontal=True)

    if source_type == "YouTube link":
        url = st.text_input("Paste YouTube URL")
        st.caption("Only download content you own or have permission to reuse.")
        if st.button("Download video", type="primary"):
            if not is_youtube_url(url):
                st.warning("Please paste a valid YouTube link.")
            else:
                log: list[str] = []
                with st.spinner("Downloading… trying multiple methods if needed"):
                    path = download_video(url.strip(), workdir(), log)
                if path:
                    set_source(path)
                    st.success("✅ Video downloaded.")
                else:
                    st.error("YouTube is blocking downloads from this server for this video.")
                    st.info("**Quick fix:** download the video on your phone/PC and use "
                            "**Upload video file** above. Clipping works the same.")
                    with st.expander("Technical details"):
                        st.code("\n".join(log) or "No details captured")
    else:
        up = st.file_uploader("Upload video", type=["mp4", "mov", "mkv", "webm"])
        if up and st.session_state.get("upload_sig") != (up.name, up.size):
            clear_sources()
            dest = workdir() / f"source{Path(up.name).suffix.lower()}"
            with open(dest, "wb") as f:
                f.write(up.getbuffer())
            st.session_state.upload_sig = (up.name, up.size)
            set_source(dest)
            st.success("✅ Video uploaded.")

    src = st.session_state.get("source")
    if src and Path(src).exists():
        st.divider()
        c1, c2, c3 = st.columns(3)
        clip_len = c1.number_input("Clip length (seconds)", min_value=10, max_value=60, value=30)
        max_clips = c2.number_input("Max clips", min_value=1, max_value=500, value=20)
        crop_916 = c3.checkbox("Auto 9:16 crop (Reels/Shorts/TikTok)", value=True)

        if st.button("🚀 Generate clips", type="primary"):
            reset_clips()
            try:
                total = probe_duration(src)
            except (subprocess.CalledProcessError, ValueError):
                total = None
                st.error("Couldn't read thi
