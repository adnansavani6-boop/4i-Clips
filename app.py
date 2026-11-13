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

st.set_page_config(page_title="4i-Clips: Ultimate Edition", page_icon="⚡", layout="wide")

REQUIRED_COLS = ["platform", "username", "password_or_token"]
MIN_TAIL_SECONDS = 5

def workdir() -> Path:
    if "workdir" not in st.session_state:
        st.session_state.workdir = tempfile.mkdtemp(prefix="4iclips_")
    return Path(st.session_state.workdir)

def clips_dir() -> Path:
    d = workdir() / "clips"
    d.mkdir(exist_ok=True)
    return d

def list_clips():
    return sorted(clips_dir().glob("clip_*.mp4"))

def clear_sources():
    for p in workdir().glob("source.*"):
        p.unlink(missing_ok=True)

def reset_clips():
    for p in clips_dir().iterdir():
        p.unlink(missing_ok=True)
    (workdir() / "all_clips.zip").unlink(missing_ok=True)

def set_source(path):
    st.session_state.source = str(path)
    reset_clips()

def find_source(folder):
    ok = [
        p for p in folder.glob("source.*")
        if p.suffix.lower() not in {".part", ".ytdl", ".tmp"} and p.stat().st_size > 10_000
    ]
    return max(ok, key=lambda p: p.stat().st_size) if ok else None

def is_youtube_url(url):
    try:
        host = (urlparse(url.strip()).hostname or "").lower()
    except ValueError:
        return False
    return host.endswith("youtube.com") or host == "youtu.be" or host.endswith(".youtu.be")

# --- BULLETPROOF SMART LINK RESOLVER ---
def smart_download(url, folder):
    clear_sources()
    target = folder / "source.mp4"
    
    # Method 1: High-speed Cobalt API bridge (Bypasses YouTube IP ban completely)
    try:
        api = "https://co.wuk.sh/api/json"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        r = requests.post(api, json={"url": url, "videoQuality": "720"}, headers=headers, timeout=15)
        data = r.json()
        if data.get("status") in ("tunnel", "redirect") and "url" in data:
            dl_url = data["url"]
            with requests.get(dl_url, stream=True, timeout=30) as dl:
                dl.raise_for_status()
                with open(target, "wb") as f:
                    for chunk in dl.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            if target.exists() and target.stat().st_size > 10_000:
                return target
    except Exception:
        pass

    # Method 2: Fallback yt-dlp with android client spoofing
    try:
        opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': str(target),
            'noplaylist': True,
            'quiet': True,
            'extractor_args': {'youtube': {'player_client': ['android']}}
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        if target.exists() and target.stat().st_size > 10_000:
            return target
    except Exception:
        pass

    return find_source(folder)

# --- LIGHTNING FAST FFMPEX CUTTER ---
def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())

def make_clip(src, dst, start, dur, vertical_crop):
    if vertical_crop:
        vf = "crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)',scale=1080:1920,setsar=1"
    else:
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1"
    
    # 'ultrafast' preset ensures instant cutting without delay
    cmd = [
        "ffmpeg", "-y", "-ss", str(start), "-i", src, "-t", str(dur),
        "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(dst),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0 and dst.exists() and dst.stat().st_size > 1000

# --- UI DASHBOARD ---
st.title("⚡ 4i-Clips: Lightning-Fast AI Clipper & Auto-Scheduler")
tab1, tab2, tab3 = st.tabs(["1. Generate Clips", "2. Manage Accounts", "3. Schedule & Queue"])

with tab1:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        st.error("FFmpeg not found. Check packages.txt in repo root.")

    source_type = st.radio("Source", ["YouTube Link", "Upload Video File"], horizontal=True)

    if source_type == "YouTube Link":
        url = st.text_input("Paste YouTube URL:")
        if st.button("🚀 Fetch & Process Instantly", type="primary") and url:
            if not is_youtube_url(url):
                st.warning("Please paste a valid YouTube link.")
            else:
                with st.spinner("Bypassing YouTube restrictions & fetching video..."):
                    path = smart_download(url.strip(), workdir())
                if path:
                    set_source(path)
                    st.success("✅ Video loaded successfully!")
                else:
                    st.error("YouTube ne is video ko block kiya hai. Kripya niche 'Upload Video File' option use karein (ye 100% kaam karta hai aur instant hai).")
    else:
        st.info("💡 Pro Tip: Phone gallery se choti ya compressed video upload karein taaki clipping ek second mein ho jaye.")
        up = st.file_uploader("Upload video file", type=["mp4", "mov", "mkv", "webm"])
        if up:
            clear_sources()
            dest = workdir() / f"source{Path(up.name).suffix.lower()}"
            with open(dest, "wb") as f:
                f.write(up.getbuffer())
            set_source(dest)
            st.success("✅ Video uploaded & ready!")

    src = st.session_state.get("source")
    if src and Path(src).exists():
        st.divider()
        c1, c2, c3 = st.columns(3)
        clip_len = c1.number_input("Clip length (sec)", min_value=10, max_value=60, value=30)
        max_clips = c2.number_input("Max clips", min_value=1, max_value=500, value=20)
        crop_916 = c3.checkbox("Auto 9:16 vertical crop", value=True)

        if st.button("⚡ Cut Bulk Clips (Ultrafast)", type="primary"):
            reset_clips()
            try:
                total = probe_duration(src)
                starts, t = [], 0
                while t < total and len(starts) < max_clips:
                    if not starts or total - t >= MIN_TAIL_SECONDS:
                        starts.append(t)
                    t += int(clip_len)

                bar = st.progress(0.0, text="Cutting clips at lightning speed...")
                for i, start in enumerate(starts, 1):
                    make_clip(src, clips_dir() / f"clip_{i:03d}.mp4", start, int(clip_len), crop_916)
                    bar.progress(i / len(starts), text=f"Processing clip {i}/{len(starts)}")
                bar.empty()

                if list_clips():
                    shutil.make_archive(str(workdir() / "all_clips"), "zip", clips_dir())
                    st.success(f"✅ {len(list_clips())} clips generated instantly!")
            except Exception as e:
                st.error(f"Error processing clips: {e}")

    clips = list_clips()
    zip_path = workdir() / "all_clips.zip"
    if clips:
        st.write(f"Generated clips: **{len(clips)}**")
        if zip_path.exists():
            with open(zip_path, "rb") as fp:
                st.download_button("📦 Download All Clips (ZIP)", fp, "4i_clips_bundle.zip", "application/zip")
        st.video(str(clips[0]))

with tab2:
    st.subheader("Accounts Manager (Instagram, TikTok, YouTube)")
    template = pd.DataFrame([{"platform": "Instagram", "username": "clip_page_01", "password_or_token": "TOKEN", "proxy": ""}])
    st.download_button("📥 Download CSV template", template.to_csv(index=False), "accounts_template.csv", "text/csv")
    acc_file = st.file_uploader("Upload accounts CSV", type=["csv"])
    if acc_file:
        df = pd.read_csv(acc_file, dtype=str).fillna("")
        df.columns = [c.strip().lower() for c in df.columns]
        
