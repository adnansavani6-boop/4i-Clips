import streamlit as st
import yt_dlp
import os
import subprocess
import shutil
import pandas as pd
import requests
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from yt_dlp.utils import DownloadError

st.set_page_config(page_title="4i-Clips", page_icon="🎬", layout="wide")

REQUIRED_COLS = ["platform", "username", "password_or_token"]
MIN_TAIL_SECONDS = 5
YTDLP_CLIENT_ATTEMPTS = [["tv"], ["web_safari"], ["mweb"], None]

def secret(name, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

def workdir() -> Path:
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
            "socket_timeout": 30,
        }
        if proxy:
            opts["proxy"] = proxy
        if clients:
            opts["extractor_args"] = {"youtube": {"player_client": clients}}
        label = ",".join(clients) if clients else "default"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as e:
            log.append(f"yt-dlp [{label}]: {str(e)[:150]}")
            continue
        found = find_source(folder)
        if found:
            return found
    return None

def try_cobalt(url: str, folder: Path, log: list):
    api = secret("COBALT_API_URL")
    if not api:
        return None
    try:
        r = requests.post(api, json={"url": url, "videoQuality": "720"}, headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=30)
        data = r.json()
        if data.get("status") not in ("tunnel", "redirect") or "url" not in data:
            return None
        clear_sources()
        target = folder / "source.mp4"
        with requests.get(data["url"], stream=True, timeout=60) as dl:
            dl.raise_for_status()
            with open(target, "wb") as f:
                for chunk in dl.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
        return find_source(folder)
    except Exception:
        return None

def download_video(url: str, folder: Path, log: list):
    return try_ytdlp(url, folder, log) or try_cobalt(url, folder, log)

def probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
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
        vf = "crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)',scale=1080:1920,setsar=1"
    else:
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1"
    cmd = [
        "ffmpeg", "-y", "-ss", str(start), "-i", src, "-t", str(dur),
        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", str(dst),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0 and dst.exists() and dst.stat().st_size > 1000, res.stderr[-300:]

st.title("🎬 4i-Clips: Bulk AI Clipper & Multi-Account Scheduler")
tab1, tab2, tab3 = st.tabs(["1. Generate Clips", "2. Manage Accounts", "3. Schedule & Queue"])

with tab1:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        st.error("FFmpeg not found. Add `packages.txt` containing `ffmpeg` to repo root.")

    source_type = st.radio("Source", ["YouTube link", "Upload video file"], horizontal=True)
    if source_type == "YouTube link":
        url = st.text_input("Paste YouTube URL")
        if st.button("Download video", type="primary") and url:
            if not is_youtube_url(url):
                st.warning("Please paste a valid YouTube link.")
            else:
                log = []
                with st.spinner("Downloading..."):
                    path = download_video(url.strip(), workdir(), log)
                if path:
                    set_source(path)
                    st.success("✅ Video downloaded.")
                else:
                    st.error("YouTube blocked direct download. Please use 'Upload video file' option instead.")
    else:
        up = st.file_uploader("Upload video", type=["mp4", "mov", "mkv", "webm"])
        if up:
            clear_sources()
            dest = workdir() / f"source{Path(up.name).suffix.lower()}"
            with open(dest, "wb") as f:
                f.write(up.getbuffer())
            set_source(dest)
            st.success("✅ Video uploaded.")

    src = st.session_state.get("source")
    if src and Path(src).exists():
        st.divider()
        c1, c2, c3 = st.columns(3)
        clip_len = c1.number_input("Clip length (sec)", min_value=10, max_value=60, value=30)
        max_clips = c2.number_input("Max clips", min_value=1, max_value=500, value=20)
        crop_916 = c3.checkbox("Auto 9:16 crop", value=True)

        if st.button("🚀 Generate clips", type="primary"):
            reset_clips()
            try:
                total = probe_duration(src)
                starts = build_starts(total, int(clip_len), int(max_clips))
                bar = st.progress(0.0, text="Cutting clips...")
                for i, start in enumerate(starts, 1):
                    make_clip(src, clips_dir() / f"clip_{i:03d}.mp4", start, int(clip_len), crop_916)
                    bar.progress(i / len(starts), text=f"Cutting clip {i}/{len(starts)}")
                bar.empty()
                if list_clips():
                    shutil.make_archive(str(workdir() / "all_clips"), "zip", clips_dir())
                    st.success(f"✅ {len(list_clips())} clips ready.")
            except Exception as e:
                st.error(f"Error cutting clips: {e}")

    clips = list_clips()
    zip_path = workdir() / "all_clips.zip"
    if clips:
        st.write(f"Generated clips: **{len(clips)}**")
        if zip_path.exists():
            with open(zip_path, "rb") as fp:
                st.download_button("📦 Download all clips (ZIP)", fp, "4i_clips_bundle.zip", "application/zip")
        st.video(str(clips[0]))

with tab2:
    st.subheader("Accounts")
    template = pd.DataFrame([{"platform": "Instagram", "username": "page_01", "password_or_token": "TOKEN", "proxy": ""}])
    st.download_button("📥 Download CSV template", template.to_csv(index=False), "accounts_template.csv", "text/csv")
    acc_file = st.file_uploader("Upload accounts CSV", type=["csv"])
    if acc_file:
        df = pd.read_csv(acc_file, dtype=str).fillna("")
        df.columns = [c.strip().lower() for c in df.columns]
        st.session_state.accounts = df
        st.success(f"{len(df)} accounts loaded.")

with tab3:
    st.subheader("Schedule & Queue")
    caption = st.text_area("Default caption", "🔥 #shorts #reels")
    if st.button("📅 Build schedule", type="primary"):
        accts = st.session_state.get("accounts")
        clips = list_clips()
        if accts is None or not len(accts):
            st.error("Upload accounts CSV in Tab 2 first.")
        elif not clips:
            st.error("Generate clips in Tab 1 first.")
        else:
            rows = [{"Clip": c.name, "Platform": a["platform"], "Account": a["username"], "Status": "Queued"} for c, a in zip(clips, accts.to_dict('records'))]
            st.session_state.schedule = pd.DataFrame(rows)
            st.success(f"🚀 {len(rows)} posts queued.")
    if "schedule" in st.session_state:
        st.dataframe(st.session_state.schedule)
     
