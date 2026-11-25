# Maddy TV Boom Tamil IPTV Playlist (Auto-Updating)

100% Free, Automated, and Bulletproof IPTV M3U Playlist generator for **Maddy TV Boom Tamil Channels** designed specifically for **TiviMate**, **OTT Navigator**, and **VLC**.

---

## 📺 TiviMate Setup (Direct M3U URL)

To add this playlist to TiviMate:

1. Open **TiviMate** on your Android TV / Phone.
2. Go to **Settings** -> **Playlists** -> **Add Playlist**.
3. Select **M3U playlist**.
4. Enter the URL:
   ```text
   https://raw.githubusercontent.com/Maady012/maddytvboom/main/bhoomtv-tamil.m3u
   ```
5. Set Playlist name to **Maddy TV Boom Tamil**.
6. Set **Update interval** to **At app start** or **Every 2 hours**.
7. Click **Done** and enjoy seamless playback!

---

## ⚡ Features

- **350+ Tamil Channels**: Entertainment, Local Cable Channels, and Live News.
- **Auto-Updating Tokens**: GitHub Actions workflow automatically refreshes HMAC tokens and stream URLs every 3 hours.
- **TiviMate & VLC Compatibility**: Stream links include proper `#EXTVLCOPT:http-referrer` and inline pipe delimiters (`|Referer=...&User-Agent=...`) for zero HTTP 403 errors.
- **Clearkey DRM Support**: Includes license parameters for encrypted DASH streams (SunNXT / NXLIV).

---

## 🔄 Automated Schedule
Powered by GitHub Actions (`.github/workflows/update.yml`) running every 3 hours completely free.
