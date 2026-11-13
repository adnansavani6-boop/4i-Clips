import streamlit as st
import yt_dlp
import os
import subprocess
import shutil
import pandas as pd
import tempfile
from pathlib import Path
from urllib.parse import urlparse

st.set_page_config(page_title="4i-Clips (Lightning Fast)", page_icon="⚡", layout="wide")

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

def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse(url.strip()).hostname or "").lower()
    except ValueError:
        return False
    return host.endswith("youtube.com") or host == "youtu.be" or host.endswith(".youtu.be")

# --- FAST YOUTUBE DOWNLOADER WITH BYPASS & COOKIES SUPPORT ---
def download_youtube_video(url: str, folder: Path, cookie_file=None):
    clear_sources()
    
    # Try multiple client bypasses to avoid 403 Forbidden
    client_attempts = [
        {'player_client': ['android']},
        {'player_client': ['ios']},
        {'player_client': ['mweb']},
        None
    ]
    
    for clients in client_attempts:
        opts = {
            'format': 'best[ext=mp4]/best[height<=720]',
            'outtmpl': str(folder / 'source.mp4'),
            'noplaylist': True,
            'quiet': True,
            'nocheckcertificate': True,
            'geo_bypass': True,
        }
        if clients:
            opts['extractor_args'] = {'youtube': clients}
        if cookie_file:
            opts['cookiefile'] = cookie_file

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            target = folder / 'source.mp4'
            if target.exists() and target.stat().st_size > 10_000:
                return target
        except Exception:
            continue
    return None

def probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())

def make_clip(src: str, dst: Path, start: int, dur: int, vertical_crop: bool):
    if vertical_crop:
        vf = "crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)',scale=1080:1920,setsar=1"
    else:
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1"
    
    # Ultra-fast preset for instant processing
    cmd = [
        "ffmpeg", "-y", "-ss", str(start), "-i", src, "-t", str(dur),
        "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(dst),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0 and dst.exists() and dst.stat().st_size > 1000

st.title("⚡ 4i-Clips: Lightning-Fast AI Clipper & Auto-Scheduler")
tab1, tab2, tab3 = st.tabs(["1. Generate Clips", "2. Manage Accounts", "3. Schedule & Queue"])

with tab1:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        st.error("FFmpeg not found. Check packages.txt")

    source_type = st.radio("Source", ["YouTube link", "Upload video file"], horizontal=True)
    
    if source_type == "YouTube link":
        url = st.text_input("Paste YouTube URL:")
        with st.expander("🔑 Optional: Upload cookies.txt (Agar YouTube block kare toh)"):
            cookie_upload = st.file_uploader("Upload cookies.txt file", type=["txt"])
            cookie_path = None
            if cookie_upload:
                cookie_path = os.path.join(workdir(), "cookies.txt")
                with open(cookie_path, "wb") as f:
                    f.write(cookie_upload.getbuffer())
                st.success("Cookies loaded!")

        if st.button("🚀 Download & Bypass YouTube", type="primary") and url:
            if not is_youtube_url(url):
                st.warning("Please paste a valid YouTube link.")
            else:
                with st.spinner("Bypassing and downloading video instantly..."):
                    path = download_youtube_video(url.strip(), workdir(), cookie_path)
                if path:
                    set_source(path)
                    st.success("✅ Video downloaded successfully!")
                else:
                    st.error("YouTube blocked direct link. Upar 'Cookies.txt' upload karke try karein, ya video file upload option use karein.")
    else:
        st.info("💡 Tip: Badi videos ke liye phone ki gallery se direct choti clip ya compressed video upload karein taaki fast processing ho.")
        up = st.file_uploader("Upload video (MP4/MOV)", type=["mp4", "mov", "mkv", "webm"])
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
        crop_916 = c3.checkbox("Auto 9:16 crop", value=True)

        if st.button("⚡ Cut Instant Clips (Ultrafast)", type="primary"):
            reset_clips()
            try:
                total = probe_duration(src)
                starts = []
                t = 0
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
                    st.success(f"✅ {len(list_clips())} clips ready instantly!")
            except Exception as e:
                st.error(f"Error: {e}")

    clips = list_clips()
    zip_path = workdir() / "all_clips.zip"
    if clips:
        st.write(f"Generated clips: **{len(clips)}**")
        if zip_path.exists():
            with open(zip_path, "rb") as fp:
                st.download_button("📦 Download All Clips (ZIP)", fp, "4i_clips_bundle.zip", "application/zip")
        st.video(str(clips[0]))

with tab2:
    st.subheader("Accounts Manager")
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
            st.success(f"🚀 {len(rows)} posts queued successfully.")
    if "schedule" in st.session_state:
        st.dataframe(st.session_state.schedule)
        
