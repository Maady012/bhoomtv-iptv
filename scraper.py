#!/usr/bin/env python3
"""
Bhoom TV IPTV Scraper & Playlist Generator
Crawls BhoomTV categories (Tamil, Tamil Local, Tamil News), resolves dynamic streams
(JioTV tokens, SunNXT MPD/Clearkeys, Akamai, Cloudfront, Cloudflare workers), and
generates a bulletproof M3U playlist optimized for TiviMate, OTT Navigator, and VLC.
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

def fetch_url(url, headers=None, timeout=12, retries=3):
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
            time.sleep(1.0 + random.random() * 1.5)

def crawl_category(category_name, category_url):
    channels = []
    page = 1
    while True:
        target_url = category_url if page == 1 else f"{category_url.rstrip('/')}/page/{page}/"
        try:
            html_content = fetch_url(target_url)
        except Exception as e:
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
        time.sleep(0.5)

    print(f"[{category_name}] Found {len(channels)} channels across {page} page(s).")
    return channels

def resolve_channel_stream(channel):
    post_id = channel["id"]
    name = channel["name"]
    link = channel["link"]
    
    # 1. Fetch embed from BhoomTV DooPlay API with retry
    api_url = f"{BASE_URL}/wp-json/dooplayer/v2/{post_id}/movie/1"
    embed_url = ""
    for attempt in range(3):
        try:
            api_resp = fetch_url(
                api_url,
                headers={
                    "Referer": link,
                    "X-Requested-With": "XMLHttpRequest"
                },
                timeout=10,
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
            time.sleep(1.0 + random.random())

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
        "clearkey": "",
        "type": "hls"
    }

    # 2. Case A: jwplayer wrapper (Direct M3U8 inside query string)
    if "jwplayer/?source=" in embed_url:
        parsed = urllib.parse.urlparse(embed_url)
        qs = urllib.parse.parse_qs(parsed.query)
        src = qs.get("source", [""])[0]
        if src:
            stream_info["stream_url"] = src
            stream_info["referer"] = "https://bhoomtv.me/"
            return stream_info

    # 3. Case B: b4uplay player (JioTV / Discovery dynamic tokenized stream)
    if "b4uplay.com" in embed_url:
        try:
            player_html = fetch_url(embed_url, headers={"Referer": "https://bhoomtv.me/"}, timeout=10)
            m = re.search(r'const STREAM_URL\s*=\s*["\']([^"\']+)["\']', player_html)
            if m:
                stream_url = m.group(1).replace(r"\/", "/")
                stream_info["stream_url"] = stream_url
                stream_info["referer"] = "https://b4uplay.com/"
                return stream_info
        except Exception:
            pass

    # 4. Case C: nxliv.com (SunNXT DRM/Clearkey DASH MPD streams)
    if "nxliv.com" in embed_url:
        try:
            player_html = fetch_url(embed_url, headers={"Referer": "https://bhoomtv.me/"}, timeout=10)
            m = re.search(r'const STREAM_URL\s*=\s*["\']([^"\']+)["\']', player_html)
            k = re.search(r'const STREAM_CLEAR_KEYS\s*=\s*(\{.*?\});', player_html)
            if m:
                rel_url = m.group(1).replace(r"\/", "/")
                full_url = urllib.parse.urljoin("https://nxliv.com", rel_url)
                stream_info["stream_url"] = full_url
                stream_info["referer"] = "https://nxliv.com/"
                stream_info["type"] = "dash"
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

    # 5. Direct HTTP/M3U8 fallback
    if embed_url.startswith("http://") or embed_url.startswith("https://"):
        stream_info["stream_url"] = embed_url
        return stream_info

    return None

def generate_m3u(streams, output_path):
    lines = ["#EXTM3U\n"]
    valid_count = 0
    
    for s in streams:
        if not s or not s.get("stream_url"):
            continue
        
        tvg_id = re.sub(r'[^a-zA-Z0-9]', '', s["name"])
        name = s["name"]
        logo = s["logo"]
        category = s["category"]
        stream_url = s["stream_url"]
        referer = s["referer"]
        user_agent = s["user_agent"]
        clearkey = s.get("clearkey", "")

        inf_line = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="{category}"'
        if clearkey:
            inf_line += f' license_type="clearkey" license_key="{clearkey}"'

        inf_line += f',{name}\n'
        lines.append(inf_line)

        lines.append(f'#EXTVLCOPT:http-referrer={referer}\n')
        lines.append(f'#EXTVLCOPT:http-user-agent={user_agent}\n')
        
        if clearkey:
            lines.append(f'#KODIPROP:inputstream.adaptive.license_type=clearkey\n')
            lines.append(f'#KODIPROP:inputstream.adaptive.license_key={clearkey}\n')

        pipe_url = f"{stream_url}|Referer={urllib.parse.quote(referer)}&User-Agent={urllib.parse.quote(user_agent)}"
        lines.append(f"{pipe_url}\n\n")
        valid_count += 1

    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"Generated playlist at '{output_path}' with {valid_count} active channels.")
    return valid_count

def main():
    print("=== Starting Bhoom TV IPTV Scraper ===")
    all_channels = []
    
    for cat_name, cat_url in CATEGORIES:
        channels = crawl_category(cat_name, cat_url)
        all_channels.extend(channels)
        
    print(f"\nTotal channel posts discovered: {len(all_channels)}")
    print("Resolving live streaming endpoints in parallel (polite rate limit)...")

    resolved_streams = []
    # 4 workers with retries
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_channel = {executor.submit(resolve_channel_stream, ch): ch for ch in all_channels}
        for future in as_completed(future_to_channel):
            res = future.result()
            if res and res.get("stream_url"):
                resolved_streams.append(res)
                print(f"  [SUCCESS] {res['name']} ({res['category']}) -> {res['stream_url'][:60]}...")
            else:
                ch = future_to_channel[future]
                print(f"  [SKIPPED / OFFLINE] {ch['name']}")

    resolved_streams.sort(key=lambda x: (x["category"], x["name"]))

    output_file = os.path.join(os.path.dirname(__file__), "bhoomtv-tamil.m3u")
    generate_m3u(resolved_streams, output_file)
    print("=== Bhoom TV Scraper Completed Successfully ===")

if __name__ == "__main__":
    main()
