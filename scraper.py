#!/usr/bin/env python3
"""
Bhoom TV IPTV Scraper & Playlist Generator
Crawls BhoomTV categories, resolves real streaming endpoints (HLS/m3u8, DASH/mpd),
verifies stream connectivity (skipping dead links), and generates clean playlists
fully compatible with VLC, TiviMate, OTT Navigator, and mobile video players.
"""

import sys
import os
import re
import json
import html
import time
import random
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://bhoomtv.me"
CATEGORIES = [
    ("Tamil Entertainment", "https://bhoomtv.me/channel/tamil/"),
    ("Tamil Local TV", "https://bhoomtv.me/channel/tamil-local-tv/"),
    ("Tamil News", "https://bhoomtv.me/channel/tamil-news/")
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://bhoomtv.me/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

def fetch_url(url, headers=None, timeout=10, retries=3):
    req_headers = DEFAULT_HEADERS.copy()
    if headers:
        req_headers.update(headers)
    
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            if attempt == retries - 1:
                raise e
            time.sleep(0.8 + random.random())

def crawl_category(category_name, category_url):
    channels = []
    page = 1
    while True:
        target_url = category_url if page == 1 else f"{category_url.rstrip('/')}/page/{page}/"
        try:
            html_content = fetch_url(target_url, timeout=12)
        except Exception:
            break
        
        items = re.findall(
            r'<article id=["\']post-(\d+)["\'].*?<img [^>]*src=["\']([^"\']+)["\'].*?<a href=["\']([^"\']+)["\']>([^<]+)</a>',
            html_content,
            re.DOTALL
        )
        if not items:
            break
            
        for post_id, logo, link, title in items:
            clean_title = html.unescape(title).strip()
            channels.append({
                "id": post_id,
                "name": clean_title,
                "logo": logo.strip(),
                "link": link.strip(),
                "category": category_name
            })
            
        if f"/page/{page + 1}/" not in html_content:
            break
        page += 1
        time.sleep(0.3)

    print(f"[{category_name}] Discovered {len(channels)} channels across {page} page(s).")
    return channels

def resolve_channel_stream(channel):
    post_id = channel["id"]
    name = channel["name"]
    link = channel["link"]
    
    # 1. Fetch embed from BhoomTV DooPlay API
    api_url = f"{BASE_URL}/wp-json/dooplayer/v2/{post_id}/movie/1"
    embed_url = ""
    for attempt in range(3):
        try:
            api_resp = fetch_url(
                api_url,
                headers={"Referer": link, "X-Requested-With": "XMLHttpRequest"},
                timeout=8,
                retries=1
            )
            data = json.loads(api_resp)
            raw_embed = data.get("embed_url", "")
            iframe_match = re.search(r'src=["\']([^"\']+)["\']', raw_embed)
            embed_url = iframe_match.group(1) if iframe_match else raw_embed
            embed_url = html.unescape(embed_url).strip()
            if embed_url:
                break
        except Exception:
            time.sleep(0.8 + random.random() * 0.5)

    if not embed_url:
        return None

    stream_info = {
        "id": post_id,
        "name": name,
        "logo": channel["logo"],
        "category": channel["category"],
        "stream_url": "",
        "referer": "https://bhoomtv.me/",
        "user_agent": USER_AGENT,
        "clearkey": ""
    }

    # Case A: jwplayer wrapper (Direct M3U8 inside query string)
    if "jwplayer/?source=" in embed_url:
        parsed = urllib.parse.urlparse(embed_url)
        qs = urllib.parse.parse_qs(parsed.query)
        src = qs.get("source", [""])[0]
        if src and src.startswith("http"):
            stream_info["stream_url"] = src
            stream_info["referer"] = "https://bhoomtv.me/"
            return stream_info

    # Case B: b4uplay player
    if "b4uplay.com" in embed_url:
        try:
            player_html = fetch_url(embed_url, headers={"Referer": "https://bhoomtv.me/"}, timeout=8)
            
            # Check const STREAM_URL / let STREAM_URL
            m = re.search(r'(?:const|let)\s+STREAM_URL\s*=\s*["\']([^"\']+)["\']', player_html)
            if m:
                stream_url = m.group(1).replace(r"\/", "/")
                stream_info["stream_url"] = stream_url
                stream_info["referer"] = "https://b4uplay.com/"
                return stream_info

            # Check const CFG = { "url": "..." }
            m_cfg = re.search(r'const\s+CFG\s*=\s*(\{.*?\});', player_html)
            if m_cfg:
                cfg_data = json.loads(m_cfg.group(1))
                cfg_url = cfg_data.get("url", "")
                if cfg_url and cfg_url.startswith("http"):
                    stream_info["stream_url"] = cfg_url
                    stream_info["referer"] = "https://b4uplay.com/"
                    return stream_info

            # Check activeChannel (Zee / VYZ streams)
            m_chan = re.search(r'const\s+activeChannel\s*=\s*(\{.*?\});', player_html)
            if m_chan:
                chan_data = json.loads(m_chan.group(1))
                stream_url = chan_data.get("m3u8Url") or chan_data.get("mpdUrl") or chan_data.get("url", "")
                if stream_url:
                    stream_info["stream_url"] = stream_url.replace(r"\/", "/")
                    stream_info["referer"] = "https://b4uplay.com/"
                    return stream_info
        except Exception:
            pass

    # Case C: nxliv.com (SunNXT DASH MPD streams)
    if "nxliv.com" in embed_url:
        try:
            player_html = fetch_url(embed_url, headers={"Referer": "https://bhoomtv.me/"}, timeout=8)
            m = re.search(r'const\s+STREAM_URL\s*=\s*["\']([^"\']+)["\']', player_html)
            k = re.search(r'const\s+STREAM_CLEAR_KEYS\s*=\s*(\{.*?\});', player_html)
            if m:
                rel_url = m.group(1).replace(r"\/", "/")
                full_url = urllib.parse.urljoin("https://nxliv.com", rel_url)
                stream_info["stream_url"] = full_url
                stream_info["referer"] = "https://nxliv.com/"
                if k:
                    try:
                        key_dict = json.loads(k.group(1))
                        clearkeys = [f"{kid}:{kval}" for kid, kval in key_dict.items()]
                        stream_info["clearkey"] = ",".join(clearkeys)
                    except Exception:
                        pass
                return stream_info
        except Exception:
            pass

    # Case D: Direct HTTP stream (.m3u8 or .mpd)
    if embed_url.startswith("http://") or embed_url.startswith("https://"):
        if any(ext in embed_url for ext in [".m3u8", ".mpd", "/hls/", "/live/"]):
            stream_info["stream_url"] = embed_url
            return stream_info

    return None

def verify_stream_playable(s):
    """Verifies that the target stream actually responds with HTTP 200."""
    url = s.get("stream_url", "")
    if not url or not url.startswith("http"):
        return False
    
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": s.get("referer", "https://bhoomtv.me/")
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass
    return False

def generate_playlists(streams, base_dir):
    # Sort streams by Category then Name
    streams.sort(key=lambda x: (x["category"], x["name"]))

    # 1. Main Universal Playlist (TiviMate, OTT Navigator, Televizo)
    m3u_main = os.path.join(base_dir, "bhoomtv-tamil.m3u")
    lines_main = ["#EXTM3U\n"]

    # 2. Clean VLC Playlist (Without pipe delimiters, pure #EXTVLCOPT for native VLC)
    m3u_vlc = os.path.join(base_dir, "bhoomtv-vlc.m3u")
    lines_vlc = ["#EXTM3U\n"]

    for s in streams:
        tvg_id = re.sub(r'[^a-zA-Z0-9]', '', s["name"])
        name = s["name"]
        logo = s["logo"]
        category = s["category"]
        url = s["stream_url"]
        referer = s["referer"]
        user_agent = s["user_agent"]
        clearkey = s.get("clearkey", "")

        inf = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="{category}"'
        if clearkey:
            inf += f' license_type="clearkey" license_key="{clearkey}"'
        inf += f',{name}\n'

        # Main playlist: pipe-delimited headers for IPTV apps
        pipe_url = f"{url}|Referer={urllib.parse.quote(referer)}&User-Agent={urllib.parse.quote(user_agent)}"
        lines_main.append(inf)
        lines_main.append(f'#EXTVLCOPT:http-referrer={referer}\n')
        lines_main.append(f'#EXTVLCOPT:http-user-agent={user_agent}\n')
        if clearkey:
            lines_main.append(f'#KODIPROP:inputstream.adaptive.license_type=clearkey\n')
            lines_main.append(f'#KODIPROP:inputstream.adaptive.license_key={clearkey}\n')
        lines_main.append(f"{pipe_url}\n\n")

        # VLC playlist: clean direct stream URL with VLC options
        lines_vlc.append(inf)
        lines_vlc.append(f'#EXTVLCOPT:http-referrer={referer}\n')
        lines_vlc.append(f'#EXTVLCOPT:http-user-agent={user_agent}\n')
        lines_vlc.append(f"{url}\n\n")

    with open(m3u_main, "w", encoding="utf-8") as f:
        f.writelines(lines_main)

    with open(m3u_vlc, "w", encoding="utf-8") as f:
        f.writelines(lines_vlc)

    print(f"Generated {len(streams)} verified channels in:")
    print(f" - {m3u_main}")
    print(f" - {m3u_vlc}")

def main():
    print("=== Starting Bhoom TV IPTV Scraper & Verifier ===")
    all_channels = []
    for cat_name, cat_url in CATEGORIES:
        channels = crawl_category(cat_name, cat_url)
        all_channels.extend(channels)

    print(f"\nDiscovered {len(all_channels)} channels. Resolving streams...")
    resolved = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {executor.submit(resolve_channel_stream, ch): ch for ch in all_channels}
        for future in as_completed(future_map):
            res = future.result()
            if res and res.get("stream_url"):
                resolved.append(res)

    print(f"Resolved {len(resolved)} raw stream URLs. Verifying live connectivity...")
    playable = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {executor.submit(verify_stream_playable, s): s for s in resolved}
        for future in as_completed(future_map):
            s = future_map[future]
            if future.result():
                playable.append(s)
                print(f"  [PLAYABLE] {s['name']} -> {s['stream_url'][:50]}...")
            else:
                print(f"  [OFFLINE / 404] {s['name']}")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    generate_playlists(playable, base_dir)
    print("=== Complete! ===")

if __name__ == "__main__":
    main()
