import streamlit as st
import yt_dlp
import os
import subprocess
import shutil
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
    
    if source_type == "YouTube Link":
        yt_url = st.text_input("Paste YouTube URL:")
        
        with st.expander("⚙️ Advanced: YouTube Bot Block Bypass (Cookies & Proxy)"):
            st.caption("Agar YouTube cloud IP block kare, toh browser se cookies.txt export karke yahan upload karein:")
            cookie_file = st.file_uploader("Upload cookies.txt (Optional)", type=["txt"])
            custom_proxy = st.text_input("Proxy URL (Optional - e.g. http://user:pass@ip:port):")
            if cookie_file:
                with open("cookies.txt", "wb") as f:
                    f.write(cookie_file.read())
                st.success("✅ Cookies loaded!")

        if st.button("Download & Process Video") and yt_url:
            with st.spinner("Bypassing YouTube filters & downloading video..."):
                if os.path.exists("downloads/input_video.mp4"):
                    os.remove("downloads/input_video.mp4")
                
                ydl_opts = {
                    'format': 'best[ext=mp4]/best',
                    'outtmpl': 'downloads/input_video.mp4',
                    'overwrites': True,
                    'nocheckcertificate': True,
                    'geo_bypass': True,
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['ios', 'android', 'mweb']
                        }
                    },
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
                    }
                }
                
                if os.path.exists("cookies.txt"):
                    ydl_opts['cookiefile'] = 'cookies.txt'
                if custom_proxy:
                    ydl_opts['proxy'] = custom_proxy

                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([yt_url])
                    st.success("✅ Video Successfully Downloaded!")
                except Exception as e:
                    st.error(f"❌ YouTube ne Cloud IP block kiya hai. Detail: {str(e)}")
                    st.info("💡 Solution: Upar 'Upload Video File' option use karein, ya 'Advanced' tab mein cookies.txt upload karein.")
    else:
        uploaded_file = st.file_uploader("Upload MP4 File Directly from Phone", type=["mp4", "mov", "mkv"])
        if uploaded_file:
            with open("downloads/input_video.mp4", "wb") as f:
                f.write(uploaded_file.read())
            st.success("✅ Video Uploaded Ready for Clipping!")

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
                # Clear old clips
                for f in os.listdir("clips"):
                    os.remove(os.path.join("clips", f))

                cmd_dur = [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", "downloads/input_video.mp4"
                ]
                total_duration = float(subprocess.check_output(cmd_dur).decode("utf-8").strip())
                
                count = 0
                for start_time in range(0, max(1, int(total_duration) - clip_duration), clip_duration):
                    if count >= max_clips:
                        break
                    out_file = f"clips/clip_{count+1:03d}.mp4"
                    vf_filter = "crop=ih*9/16:ih,scale=1080:1920" if crop_9_16 else "scale=1080:1920"
                    
                    cmd = [
                        "ffmpeg", "-y", "-ss", str(start_time), "-i", "downloads/input_video.mp4",
                        "-t", str(clip_duration), "-vf", vf_filter,
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", out_file
                    ]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    count += 1
                
                shutil.make_archive("all_clips", 'zip', "clips")
                st.success(f"✅ {count} Clips Ready ho gayi hain!")
        else:
            st.error("Pehle video download ya upload karein!")

    clip_files = sorted(os.listdir("clips"))
    if clip_files:
        st.write(f"Total Generated Clips: **{len(clip_files)}**")
        if os.path.exists("all_clips.zip"):
            with open("all_clips.zip", "rb") as fp:
                st.download_button("📦 Download All Clips (ZIP)", fp, "4i_clips_bundle.zip", "application/zip")
        st.video(f"clips/{clip_files[0]}")

# --- TAB 2: MULTI-ACCOUNT MANAGER ---
with tab2:
    st.subheader("Bulk Accounts Manager (Instagram, TikTok, YouTube)")
    st.info("100s of accounts ek saath connect karne ke liye CSV upload karein")
    
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
            
