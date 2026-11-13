import streamlit as st
import yt_dlp
import os
import subprocess
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="4i-Clips AI & Auto-Uploader", layout="wide")
st.title("🎬 4i-Clips: Bulk AI Clipper & Multi-Account Scheduler")

os.makedirs("downloads", exist_ok=True)
os.makedirs("clips", exist_ok=True)

tab1, tab2, tab3 = st.tabs(["1. Generate Clips", "2. Manage 100s of Accounts", "3. Auto-Schedule & Bulk Upload"])

# --- TAB 1: AI CLIPPING ENGINE ---
with tab1:
    st.subheader("YouTube Link ya Video Upload Karein")
    source_type = st.radio("Select Source:", ["YouTube Link", "Upload Video File"])
    
    video_path = None
    if source_type == "YouTube Link":
        yt_url = st.text_input("Paste YouTube URL:")
        if st.button("Download & Process Video") and yt_url:
            with st.spinner("Downloading video..."):
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl': 'downloads/input_video.mp4',
                    'overwrites': True
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([yt_url])
                video_path = "downloads/input_video.mp4"
                st.success("Video Downloaded!")
    else:
        uploaded_file = st.file_uploader("Upload MP4 File", type=["mp4", "mov"])
        if uploaded_file:
            video_path = "downloads/input_video.mp4"
            with open(video_path, "wb") as f:
                f.write(uploaded_file.read())
            st.success("Video Uploaded!")

    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        clip_duration = st.number_input("Clip Duration (Seconds)", min_value=10, max_value=60, value=30)
    with col2:
        max_clips = st.number_input("Kitni Clips Banani Hai?", min_value=1, max_value=500, value=20)
    with col3:
        crop_9_16 = st.checkbox("Auto 9:16 Vertical Crop (Reels/Shorts/TikTok)", value=True)

    if st.button("🚀 Generate Bulk Clips"):
        if os.path.exists("downloads/input_video.mp4"):
            with st.spinner("FFmpeg se fast 9:16 clips kat rahi hain..."):
                # Get video duration
                cmd_dur = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", "downloads/input_video.mp4"]
                total_duration = float(subprocess.check_output(cmd_dur).decode("utf-8").strip())
                
                count = 0
                for start_time in range(0, int(total_duration) - clip_duration, clip_duration):
                    if count >= max_clips:
                        break
                    out_file = f"clips/clip_{count+1}.mp4"
                    vf_filter = "crop=ih*9/16:ih,scale=1080:1920" if crop_9_16 else "scale=1080:1920"
                    
                    cmd = [
                        "ffmpeg", "-y", "-ss", str(start_time), "-i", "downloads/input_video.mp4",
                        "-t", str(clip_duration), "-vf", vf_filter,
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out_file
                    ]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    count += 1
                st.success(f"✅ {count} Clips Ready ho gayi hain!")
        else:
            st.error("Pehle video download ya upload karein!")

    # Show generated clips
    clip_files = sorted(os.listdir("clips"))
    if clip_files:
        st.write(f"Total Generated Clips: **{len(clip_files)}**")
        st.video(f"clips/{clip_files[0]}")

# --- TAB 2: MULTI-ACCOUNT MANAGER (CSV FOR 100s OF ACCOUNTS) ---
with tab2:
    st.subheader("Bulk Accounts Manager (Instagram, TikTok, YouTube)")
    st.info("100s of accounts ek saath connect karne ke liye CSV upload karein (Columns: platform, username, password_or_token, proxy)")
    
    sample_df = pd.DataFrame([
        {"platform": "Instagram", "username": "clip_page_01", "password_or_token": "pass123", "proxy": "http://user:pass@ip:port"},
        {"platform": "TikTok", "username": "tiktok_clips_01", "password_or_token": "session_id_token", "proxy": "http://user:pass@ip:port"},
        {"platform": "YouTube", "username": "yt_shorts_01", "password_or_token": "oauth_refresh_token", "proxy": ""}
    ])
    st.download_button("📥 Download Sample Accounts CSV Template", sample_df.to_csv(index=False), "accounts_template.csv", "text/csv")
    
    acc_file = st.file_uploader("Upload Accounts CSV", type=["csv"])
    if acc_file:
        df_acc = pd.read_csv(acc_file)
        df_acc.to_csv("accounts.csv", index=False)
        st.success(f"{len(df_acc)} Accounts Loaded Successfully!")
        st.dataframe(df_acc)

# --- TAB 3: BULK SCHEDULER & AUTO-POSTER ---
with tab3:
    st.subheader("Auto-Distribute & Schedule Clips Across All Accounts")
    caption_template = st.text_area("Default Caption & Hashtags:", "Wait for the end! 🔥 #viral #shorts #reels #fyp")
    interval_mins = st.number_input("Har post ke beech kitna gap rakhna hai? (Minutes)", min_value=5, value=30)
    
    if st.button("📅 Start Bulk Scheduling Automation"):
        clip_files = sorted(os.listdir("clips"))
        if not os.path.exists("accounts.csv") or not clip_files:
            st.error("Make sure clips generated hain aur Accounts CSV uploaded hai!")
        else:
            accounts = pd.read_csv("accounts.csv").to_dict('records')
            schedule_log = []
            now = datetime.now()
            
            for idx, clip in enumerate(clip_files):
                acc = accounts[idx % len(accounts)]
                post_time = now + timedelta(minutes=interval_mins * (idx // len(accounts)))
                schedule_log.append({
                    "Clip": clip,
                    "Platform": acc["platform"],
                    "Account": acc["username"],
                    "Scheduled Time": post_time.strftime("%Y-%m-%d %H:%M"),
                    "Proxy Used": acc.get("proxy", "None"),
                    "Status": "Queued"
                })
            st.success("🚀 All Clips Mapped & Queued Across Accounts!")
            st.dataframe(pd.DataFrame(schedule_log))
          
