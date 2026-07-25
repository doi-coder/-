"""YouTube Data API v3로 최근 화제가 된 건강 콘텐츠를 찾는다.

- search.list 는 호출당 쿼터 100 (하루 10,000 쿼터) 이라 비쌈 -> MAX_QUERIES로 하루 호출 수 제한.
- videos.list 는 호출당 쿼터 1로 저렴 -> search 결과의 통계(조회수/좋아요)는 여기서 채운다.
"""
import os
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

DEFAULT_KEYWORDS = [
    "다이어트", "불면증", "영양제", "스트레스 해소", "면역력",
    "허리디스크", "갱년기", "당뇨 관리", "탈모",
]

MAX_QUERIES = 8  # search.list 쿼터(100/call) 보호용 상한


def _api_key():
    return os.environ["YOUTUBE_API_KEY"]


def _search_recent_videos(query, published_after, region_code="KR", max_results=10):
    params = {
        "key": _api_key(),
        "q": query,
        "part": "id",
        "type": "video",
        "order": "viewCount",
        "publishedAfter": published_after,
        "regionCode": region_code,
        "relevanceLanguage": "ko",
        "maxResults": max_results,
    }
    resp = requests.get(SEARCH_URL, params=params, timeout=15)
    resp.raise_for_status()
    return [item["id"]["videoId"] for item in resp.json().get("items", [])]


def _fetch_video_stats(video_ids):
    if not video_ids:
        return []
    params = {
        "key": _api_key(),
        "id": ",".join(video_ids),
        "part": "snippet,statistics",
    }
    resp = requests.get(VIDEOS_URL, params=params, timeout=15)
    resp.raise_for_status()
    videos = []
    for item in resp.json().get("items", []):
        stats = item.get("statistics", {})
        snippet = item["snippet"]
        videos.append({
            "video_id": item["id"],
            "title": snippet["title"],
            "channel": snippet["channelTitle"],
            "published_at": snippet["publishedAt"],
            "view_count": int(stats.get("viewCount", 0)),
            "like_count": int(stats.get("likeCount", 0)),
            "url": f"https://www.youtube.com/watch?v={item['id']}",
        })
    return videos


def trending_health_videos(keywords=None, published_within_days=3, top_n=15):
    keywords = (keywords or DEFAULT_KEYWORDS)[:MAX_QUERIES]
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=published_within_days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    video_ids = []
    seen = set()
    for kw in keywords:
        for vid in _search_recent_videos(kw, published_after):
            if vid not in seen:
                seen.add(vid)
                video_ids.append(vid)

    videos = []
    for i in range(0, len(video_ids), 50):  # videos.list는 id 최대 50개/call
        videos.extend(_fetch_video_stats(video_ids[i:i + 50]))

    videos.sort(key=lambda v: v["view_count"], reverse=True)
    return videos[:top_n]


if __name__ == "__main__":
    import json
    print(json.dumps(trending_health_videos(), ensure_ascii=False, indent=2))
