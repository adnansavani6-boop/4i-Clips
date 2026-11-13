import streamlit as st
import yt_dlp
import subprocess
import shutil
import tempfile
import json
import csv
import math
from pathlib import Path
from urllib.parse import urlparse

st.set_page_config(page_title="4i-Clips V2", page_icon="⚡", layout="wide")

BASE = Path(st.session_state.get("workdir", tempfile.mkdtemp(prefix="4iclips_v2_")))
st.session_state["workdir"] = str(BASE)
CLIPS = BASE / "clips"
CLIPS.mkdir(exist_ok=True)

def run(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

def youtube_url(url):
    try:
        h = (urlparse(url.strip()).hostname or "").lower()
        return h == "youtu.be" or h.endswith("youtube.com") or h.endswith(".youtube.com")
    except Exception:
        return False

def reset_clips():
    for p in CLIPS.glob("clip_*.mp4"):
        p.unlink(missing_ok=True)
    (BASE / "clips.zip").unlink(missing_ok=True)

def duration(path):
    r = run(["ffprobe","-v","error","-show_entries","format=duration",
             "-of","default=noprint_wrappers=1:nokey=1",str(path)])
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1000:])
    return float(r.stdout.strip())

def download_video(url, cookies=None):
    for p in BASE.glob("source.*"):
        p.unlink(missing_ok=True)
    out = BASE / "source.%(ext)s"
    opts = {
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(out),
        "noplaylist": True,
        "quiet": True,
        "retries": 3,
        "fragment_retries": 3,
    }
    if cookies:
        opts["cookiefile"] = str(cookies)
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([url])
    files = list(BASE.glob("source.*"))
    return files[0] if files else None

def scene_points(src):
    # FFmpeg scene-change score. If unavailable, return empty list.
    vf = "select='gt(scene,0.35)',showinfo"
    r = run(["ffmpeg","-hide_banner","-i",str(src),"-vf",vf,"-f","null","-"], timeout=180)
    points = []
    for line in r.stderr.splitlines():
        if "pts_time:" in line:
            try:
                x = line.split("pts_time:",1)[1].split()[0]
                points.append(float(x))
            except Exception:
                pass
    return points

def loudness_points(src):
    # Detect louder sections using FFmpeg's volumedetect in 10-second windows.
    # This is a lightweight heuristic, not a claim of semantic AI.
    total = duration(src)
    points = []
    step = 10
    for start in range(0, max(1, int(total)), step):
        length = min(step, total-start)
        r = run(["ffmpeg","-ss",str(start),"-t",str(length),"-i",str(src),
                 "-af","volumedetect","-f","null","-"], timeout=30)
        mean = None
        for line in r.stderr.splitlines():
            if "mean_volume:" in line:
                try:
                    mean = float(line.split("mean_volume:")[1].split("dB")[0].strip())
                except Exception:
                    pass
        if mean is not None:
            points.append((start, mean))
    return points

def smart_starts(src, clip_len, max_clips):
    total = duration(src)
    candidates = []
    # Combine scene changes with loudness peaks.
    for t in scene_points(src):
        if 0 <= t <= max(0, total-clip_len):
            candidates.append((t, 2.0))
    loud = loudness_points(src)
    if loud:
        vals = [v for _,v in loud]
        avg = sum(vals)/len(vals)
        for t,v in loud:
            if v >= avg + 4 and t <= max(0,total-clip_len):
                candidates.append((float(t), 1.5))

    # Always retain evenly spaced fallbacks.
    if not candidates:
        candidates = [(float(t),1.0) for t in range(0, max(1,int(total-clip_len)+1), clip_len)]

    candidates.sort(key=lambda x: x[1], reverse=True)
    chosen = []
    min_gap = max(clip_len * 0.6, 8)
    for t,_score in candidates:
        if all(abs(t-c) >= min_gap for c in chosen):
            chosen.append(t)
        if len(chosen) >= max_clips:
            break
    chosen.sort()
    return chosen

def make_clip(src, dst, start, length, mode):
    if mode == "crop":
        vf = "crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)',scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1"
    else:
        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1"
    cmd = ["ffmpeg","-y","-ss",str(max(0,start)),"-i",str(src),
           "-t",str(length),"-vf",vf,
           "-c:v","libx264","-preset","veryfast","-crf","23",
           "-pix_fmt","yuv420p","-c:a","aac","-b:a","128k",
           "-movflags","+faststart",str(dst)]
    r = run(cmd, timeout=300)
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 1000

def zip_clips():
    archive = BASE / "clips"
    z = shutil.make_archive(str(BASE / "clips"), "zip", archive)
    return Path(z)

st.title("⚡ 4i-Clips V2")
st.caption("Smart clip detection • 9:16 rendering • export queue")

if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
    st.error("FFmpeg/FFprobe not found. Install packages.txt before running.")

tab1, tab2, tab3 = st.tabs(["🎬 Smart Clipper","📋 Queue","⚙️ Settings"])

with tab1:
    source = st.radio("Source",["YouTube URL","Upload video"],horizontal=True)
    src = None

    if source == "YouTube URL":
        url = st.text_input("YouTube URL")
        cookies = st.file_uploader("Optional cookies.txt",type=["txt"])
        if st.button("⬇️ Download",type="primary"):
            if not youtube_url(url):
                st.error("Valid YouTube URL required.")
            else:
                cookie_path = None
                if cookies:
                    cookie_path = BASE / "cookies.txt"
                    cookie_path.write_bytes(cookies.getbuffer())
                try:
                    with st.spinner("Downloading..."):
                        src = download_video(url,cookie_path)
                    if src:
                        st.session_state["source"] = str(src)
                        st.success("Video ready.")
                except Exception as e:
                    st.error(f"Download failed: {e}")

    else:
        up = st.file_uploader("Upload MP4/MOV/MKV/WebM",type=["mp4","mov","mkv","webm"])
        if up:
            p = BASE / ("source" + Path(up.name).suffix.lower())
            p.write_bytes(up.getbuffer())
            st.session_state["source"] = str(p)
            st.success("Video ready.")

    src = Path(st.session_state["source"]) if st.session_state.get("source") else None

    if src and src.exists():
        st.video(str(src))
        a,b,c = st.columns(3)
        clip_len = a.slider("Clip length",10,60,30)
        max_clips = b.slider("Maximum clips",1,50,10)
        mode = c.selectbox("9:16 mode",["crop","fit"])

        if st.button("🧠 Find Best Moments + Render",type="primary"):
            reset_clips()
            try:
                with st.spinner("Analyzing scenes and audio..."):
                    starts = smart_starts(src,clip_len,max_clips)
                if not starts:
                    st.error("No usable moments found.")
                else:
                    bar = st.progress(0)
                    made = 0
                    for i,start in enumerate(starts,1):
                        dst = CLIPS / f"clip_{i:03d}.mp4"
                        if make_clip(src,dst,start,clip_len,mode):
                            made += 1
                        bar.progress(i/len(starts))
                    zip_clips()
                    st.success(f"Created {made} clips.")
            except Exception as e:
                st.error(f"Processing error: {e}")

    clips = sorted(CLIPS.glob("clip_*.mp4"))
    if clips:
        st.write(f"**{len(clips)} clips ready**")
        st.download_button("📦 Download ZIP",(BASE/"clips.zip").read_bytes(),
                           "4i_clips_v2.zip","application/zip")
        for p in clips[:6]:
            with st.expander(p.name):
                st.video(str(p))

with tab2:
    st.subheader("Queue Builder")
    account_csv = st.file_uploader("Upload accounts CSV",type=["csv"])
    if account_csv:
        import pandas as pd
        df = pd.read_csv(account_csv,dtype=str).fillna("")
        required = {"platform","username"}
        missing = required - set(c.strip().lower() for c in df.columns)
        if missing:
            st.error(f"Missing columns: {', '.join(sorted(missing))}")
        else:
            df.columns = [c.strip().lower() for c in df.columns]
            st.session_state["accounts"] = df
            st.success(f"{len(df)} accounts loaded.")

    clips = sorted(CLIPS.glob("clip_*.mp4"))
    accounts = st.session_state.get("accounts")
    if accounts is not None and len(accounts) and clips:
        distribution = st.selectbox("Distribution",[
            "Every clip to every account",
            "Round-robin clips across accounts"
        ])
        if st.button("Build Queue",type="primary"):
            rows = []
            if distribution.startswith("Every"):
                for clip in clips:
                    for _,a in accounts.iterrows():
                        rows.append({"clip":clip.name,"platform":a["platform"],
                                     "account":a["username"],"status":"queued"})
            else:
                for i,clip in enumerate(clips):
                    a = accounts.iloc[i % len(accounts)]
                    rows.append({"clip":clip.name,"platform":a["platform"],
                                 "account":a["username"],"status":"queued"})
            st.session_state["queue"] = rows

    if st.session_state.get("queue"):
        import pandas as pd
        q = pd.DataFrame(st.session_state["queue"])
        st.dataframe(q,use_container_width=True)
        st.download_button("Download queue CSV",q.to_csv(index=False),
                           "4i_queue.csv","text/csv")

with tab3:
    st.subheader("Settings")
    st.info("This V2 keeps platform credentials out of the generated queue. Connect official platform APIs/OAuth in the uploader module before enabling automatic publishing.")
    st.write("FFmpeg:", "OK" if shutil.which("ffmpeg") else "Missing")
    st.write("FFprobe:", "OK" if shutil.which("ffprobe") else "Missing")
    st.write("Working directory:", str(BASE))
