import asyncio
import json
import logging
import os
import time

import httpx

QWEATHER_CITY = ""
QWEATHER_CITY_NAME = ""

CACHE_TTL = 1800  # 30 分钟
_cache: dict = {}
_cache_ts: float = 0


def _get_key():
    return os.getenv("QWEATHER_API_KEY", "")


def _get_host():
    return os.getenv("QWEATHER_HOST", "")


def _get_city():
    return QWEATHER_CITY or os.getenv("QWEATHER_CITY", "101190205")


async def fetch_weather() -> dict | None:
    """拉取实时天气 + 3天预报，缓存30分钟"""
    global _cache, _cache_ts

    if _cache and time.time() - _cache_ts < CACHE_TTL:
        return _cache

    key = _get_key()
    host = _get_host()
    if not key or not host:
        logging.warning("天气 API 未配置")
        return None

    base = f"https://{host}"
    city = _get_city()
    params = {"location": city, "key": key}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            now_resp = await client.get(f"{base}/v7/weather/now", params=params)
            forecast_resp = await client.get(f"{base}/v7/weather/3d", params=params)
            if not QWEATHER_CITY_NAME:
                await _resolve_city_name(client, base, city, key)

        now_data = now_resp.json()
        forecast_data = forecast_resp.json()

        if now_data.get("code") != "200":
            logging.warning(f"天气 API now 返回: {now_data.get('code')}")
            return _cache or None

        now = now_data.get("now", {})
        days = forecast_data.get("daily", []) if forecast_data.get("code") == "200" else []

        result = {
            "cityName": QWEATHER_CITY_NAME,
            "temp": now.get("temp"),
            "feelsLike": now.get("feelsLike"),
            "text": now.get("text"),
            "icon": now.get("icon"),
            "humidity": now.get("humidity"),
            "windDir": now.get("windDir"),
            "windScale": now.get("windScale"),
            "precip": now.get("precip"),
            "vis": now.get("vis"),
            "updateTime": now_data.get("updateTime"),
            "forecast": [
                {
                    "date": d.get("fxDate"),
                    "textDay": d.get("textDay"),
                    "textNight": d.get("textNight"),
                    "tempMin": d.get("tempMin"),
                    "tempMax": d.get("tempMax"),
                    "iconDay": d.get("iconDay"),
                }
                for d in days[:3]
            ],
        }

        _cache = result
        _cache_ts = time.time()
        return result

    except Exception as e:
        logging.warning(f"天气拉取失败: {e}")
        return _cache or None


async def _resolve_city_name(client: httpx.AsyncClient, base: str, city_id: str, key: str):
    global QWEATHER_CITY_NAME
    try:
        resp = await client.get(f"{base}/geo/v2/city/lookup", params={"location": city_id, "key": key})
        data = resp.json()
        if data.get("code") == "200" and data.get("location"):
            loc = data["location"][0]
            QWEATHER_CITY_NAME = f"{loc.get('adm2', '')} {loc.get('name', '')}".strip()
    except Exception:
        pass


def weather_summary(data: dict | None) -> str:
    """生成给小予看的天气摘要"""
    if not data:
        return ""
    parts = [f"{data['temp']}°C {data['text']}"]
    if data.get("humidity"):
        parts.append(f"湿度{data['humidity']}%")
    if data.get("windDir"):
        parts.append(f"{data['windDir']}{data.get('windScale', '')}级")
    forecast = data.get("forecast", [])
    if forecast:
        today = forecast[0]
        parts.append(f"今天{today['tempMin']}~{today['tempMax']}°C")
    return "，".join(parts)


async def search_city(query: str) -> list[dict]:
    """搜索城市，返回 [{id, name, adm1, adm2}]"""
    key = _get_key()
    host = _get_host()
    if not key or not host:
        return []
    base = f"https://{host}"
    params = {"location": query, "key": key, "number": "5"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base}/geo/v2/city/lookup", params=params)
        data = resp.json()
        if data.get("code") != "200":
            return []
        return [
            {"id": loc["id"], "name": loc["name"], "adm1": loc["adm1"], "adm2": loc["adm2"]}
            for loc in data.get("location", [])
        ]
    except Exception as e:
        logging.warning(f"城市搜索失败: {e}")
        return []
