"""Gaode Maps (高德地图) provider for Life Hub.

基于 ha_gaode_server 实现，提供：
- GPSLogger 数据存储
- GCJ-02 坐标转换
- 距离计算
- 多边形范围计算
- 设备追踪器配置
"""

from __future__ import annotations

import logging
import math
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..base import ProviderSpec
from ...models import ProviderRuntime

_LOGGER = logging.getLogger(__name__)

PROVIDER_KEY = "gaode"
PROVIDER_NAME = "高德地图"

GAODE_API_BASE = "https://restapi.amap.com"
GAODE_SERVER_API = "https://restapi.amap.com/v5"


def build_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required("api_key", default=current.get("api_key", "")): str,
        vol.Optional("security_code", default=current.get("security_code", "")): str,
        vol.Optional("refresh_interval", default=current.get("refresh_interval", 30)): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=1440)
        ),
    })


async def validate_config(hass: HomeAssistant, data: dict[str, Any]) -> None:
    key = data.get("api_key", "")
    if not key:
        raise ValueError("api_key is required")
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"{GAODE_SERVER_API}/place/text",
            params={"keywords": "天安门", "city": "北京", "key": key},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            body = await resp.json(content_type=None)
            if body.get("status") != "1" and body.get("infocode") != "10000":
                raise ValueError(f"API Key 无效: {body.get('info', '未知错误')}")
    except ValueError:
        raise
    except Exception as err:
        raise ValueError(f"连接失败: {err}") from err


async def setup_provider(
    hass: HomeAssistant,
    config: dict[str, Any],
    subentry_id: str,
) -> ProviderRuntime:
    api_key = config["api_key"]
    security_code = config.get("security_code", "")
    session = async_get_clientsession(hass)
    status = "connected"

    client = GaodeClient(session, api_key, security_code)

    async def stop() -> None:
        pass

    def get_status() -> str:
        return status

    async def _health_check() -> bool:
        try:
            await client.search_poi("天安门", "北京")
            return True
        except Exception as err:
            _LOGGER.warning("Gaode health check failed: %s", err)
            return False

    return ProviderRuntime(
        key=PROVIDER_KEY, title=PROVIDER_NAME, subentry_id=subentry_id,
        client=client, stop=stop, status=get_status, status_check=_health_check,
    )


class GaodeClient:
    """高德地图客户端"""
    
    def __init__(self, session: aiohttp.ClientSession, api_key: str, security_code: str) -> None:
        self._session = session
        self._api_key = api_key
        self._security_code = security_code

    # ========== 基础地图服务 ==========

    async def search_poi(self, keywords: str, region: str = "全国",
                         types: str = "", page: int = 1, page_size: int = 20) -> list:
        """POI 关键字搜索（v5 API，数据更丰富）

        Args:
            keywords: 搜索关键词，如"希尔顿"
            region: 城市，如"温州"
            types: POI类型筛选，如"酒店"、"餐饮"（可选）
            page: 页码，默认1
            page_size: 每页条数，默认20
        """
        params = {
            "keywords": keywords,
            "city": region,
            "key": self._api_key,
            "page_num": str(page),
            "page_size": str(page_size),
        }
        if types:
            params["types"] = types
        async with self._session.get(
            f"{GAODE_SERVER_API}/place/text",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            body = await resp.json(content_type=None)
            pois = body.get("pois", [])
            # v5 返回的每个 poi 含有更丰富字段：
            # id, name, type, typecode, address, location,
            # pname, cityname, adname, adcode, distance
            return pois

    async def search_poi_detail(self, poi_id: str) -> dict | None:
        """查询 POI 详情（v5 API）

        Args:
            poi_id: POI 的唯一 ID，由 search_poi 返回
        """
        params = {
            "id": poi_id,
            "key": self._api_key,
        }
        async with self._session.get(
            f"{GAODE_SERVER_API}/place/detail",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            body = await resp.json(content_type=None)
            pois = body.get("pois", [])
            return pois[0] if pois else None

    async def search_poi_nearby(self, location: str, keywords: str = "",
                                 radius: int = 3000, types: str = "") -> list:
        """POI 周边搜索（v5 API）

        Args:
            location: 中心点坐标 "经度,纬度"
            keywords: 搜索关键词（可选）
            radius: 搜索半径（米），默认3000
            types: POI类型筛选（可选）
        """
        params = {
            "location": location,
            "key": self._api_key,
            "radius": str(radius),
        }
        if keywords:
            params["keywords"] = keywords
        if types:
            params["types"] = types
        async with self._session.get(
            f"{GAODE_SERVER_API}/place/around",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            body = await resp.json(content_type=None)
            return body.get("pois", [])

    async def geocode(self, address: str, city: str = "") -> dict | None:
        """地理编码（地址 → 坐标）"""
        params = {
            "address": address,
            "key": self._api_key,
            "output": "json",
        }
        if city:
            params["city"] = city
        async with self._session.get(
            f"{GAODE_API_BASE}/v3/geocode/geo",
            params=params,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            body = await resp.json()
            geocodes = body.get("geocodes", [])
            return geocodes[0] if geocodes else None

    async def reverse_geocode(self, location: str) -> dict | None:
        """逆地理编码（坐标 → 地址）"""
        params = {
            "location": location,
            "key": self._api_key,
            "output": "json",
        }
        async with self._session.get(
            f"{GAODE_API_BASE}/v3/geocode/regeo",
            params=params,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            body = await resp.json()
            return body.get("regeocode")

    async def get_distance(self, origins: str, destination: str, type_: int = 1) -> dict:
        """驾车路线距离查询（v3 API）"""
        params = {
            "origins": origins,
            "destination": destination,
            "key": self._api_key,
            "output": "json",
            "type": str(type_),
        }
        async with self._session.get(
            f"{GAODE_API_BASE}/v3/direction/driving",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            body = await resp.json(content_type=None)
            return body.get("route", {})

    # ========== 路径规划 ==========

    _ROUTE_TYPES = {
        "walking": "v3/direction/walking",
        "driving": "v3/direction/driving",
        "bicycling": "v3/direction/bicycling",
        "transit": "v3/direction/transit/integrated",
    }

    async def route_planning(self, origin: str, destination: str,
                             mode: str = "driving",
                             city: str = "", city_dest: str = "",
                             strategy: int = 0) -> dict:
        """路径规划（步行/驾车/骑行/公交）

        Args:
            origin: 起点坐标 "经度,纬度" 或地址
            destination: 终点坐标 "经度,纬度" 或地址
            mode: 出行方式 walking/driving/bicycling/transit
            city: 起点城市（公交规划必填）
            city_dest: 终点城市（跨城公交必填）
            strategy: 驾车策略（0=最快,1=最省钱,2=最短,3=躲避拥堵）
        """
        endpoint = self._ROUTE_TYPES.get(mode, "v3/direction/driving")
        params = {
            "origin": origin,
            "destination": destination,
            "key": self._api_key,
            "output": "json",
        }
        if mode in ("walking", "driving", "bicycling"):
            params["destination"] = destination.replace(" ", "")
            params["origin"] = origin.replace(" ", "")
        if mode == "driving":
            params["strategy"] = str(strategy)
        if mode == "transit":
            if city:
                params["city"] = city
            if city_dest:
                params["cityd"] = city_dest
            else:
                params["cityd"] = city

        async with self._session.get(
            f"{GAODE_API_BASE}/{endpoint}",
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            body = await resp.json(content_type=None)
            route = body.get("route", {})
            if not route and mode == "transit":
                transits = body.get("transits", [])
                if transits:
                    return {"transits": transits}
            return route

    async def travel_plan(self, city: str, interests: str,
                          route_type: str = "driving") -> dict:
        """智能旅游规划：自动搜索兴趣点并规划路线

        Args:
            city: 城市名
            interests: 兴趣点分类，逗号分隔如"景点,美食,酒店"
            route_type: 路线方式 walking/driving
        """
        categories = [c.strip() for c in interests.split(",") if c.strip()]
        pois_by_cat = {}
        all_locations = []

        # 搜索各类兴趣点
        for cat in categories:
            pois = await self.search_poi(cat, city, page_size=5)
            pois_by_cat[cat] = pois
            for p in pois[:3]:
                loc = p.get("location", "")
                if loc and loc not in all_locations:
                    all_locations.append(loc)

        # 规划路线：按顺序连接各点
        routes = []
        for i in range(len(all_locations) - 1):
            if all_locations[i] and all_locations[i + 1]:
                try:
                    route = await self.route_planning(
                        all_locations[i], all_locations[i + 1],
                        mode=route_type, city=city,
                    )
                    routes.append({
                        "from": all_locations[i],
                        "to": all_locations[i + 1],
                        "route": route,
                    })
                except Exception:
                    routes.append({
                        "from": all_locations[i],
                        "to": all_locations[i + 1],
                        "route": {},
                    })

        return {
            "city": city,
            "interests": categories,
            "pois": pois_by_cat,
            "route_count": len(routes),
            "routes": routes,
        }

    # ========== 设备追踪器相关 ==========

    async def convert_gcj02_to_wgs84(self, lng: float, lat: float) -> tuple[float, float]:
        """GCJ-02 坐标转 WGS-84"""
        # 简化的转换算法
        lng, lat = self._gcj02_to_wgs84(lng, lat)
        return lng, lat

    async def convert_wgs84_to_gcj02(self, lng: float, lat: float) -> tuple[float, float]:
        """WGS-84 坐标转 GCJ-02"""
        lng, lat = self._wgs84_to_gcj02(lng, lat)
        return lng, lat

    def _gcj02_to_wgs84(self, lng: float, lat: float) -> tuple[float, float]:
        """GCJ-02 → WGS-84"""
        PI = 3.14159265358979324
        a = 6378245.0
        ee = 0.00669342162296594323
        dlat = self._transform_lat(lng - 105.0, lat - 35.0)
        dlng = self._transform_lng(lng - 105.0, lat - 35.0)
        radlat = lat / 180.0 * PI
        magic = math.sin(radlat)
        magic = 1 - ee * magic * magic
        sqrtmagic = math.sqrt(magic)
        dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * PI)
        dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat / 180.0 * PI) * PI)
        return lng - dlng, lat - dlat

    def _wgs84_to_gcj02(self, lng: float, lat: float) -> tuple[float, float]:
        """WGS-84 → GCJ-02"""
        PI = 3.14159265358979324
        a = 6378245.0
        ee = 0.00669342162296594323
        dlat = self._transform_lat(lng - 105.0, lat - 35.0)
        dlng = self._transform_lng(lng - 105.0, lat - 35.0)
        radlat = lat / 180.0 * PI
        magic = math.sin(radlat)
        magic = 1 - ee * magic * magic
        sqrtmagic = math.sqrt(magic)
        dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * PI)
        dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat / 180.0 * PI) * PI)
        return lng + dlng, lat + dlat

    def _transform_lat(self, lng: float, lat: float) -> float:
        ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
        ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320.0 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
        return ret

    def _transform_lng(self, lng: float, lat: float) -> float:
        ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
        ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng * math.pi / 30.0)) * 2.0 / 3.0
        return ret

    async def calculate_distance(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """计算两点距离（米）"""
        # Haversine 公式
        R = 6371000  # 地球半径（米）
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lng / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    async def check_in_polygon(self, point_lat: float, point_lng: float, polygon: list[tuple[float, float]]) -> bool:
        """检查点是否在多边形内"""
        n = len(polygon)
        inside = False
        p1_lat, p1_lng = polygon[0]
        for i in range(n + 1):
            p2_lat, p2_lng = polygon[i % n]
            if point_lng > min(p1_lng, p2_lng):
                if point_lng <= max(p1_lng, p2_lng):
                    if point_lat <= max(p1_lat, p2_lat):
                        if p1_lng != p2_lng:
                            point_lon_intersects = (point_lat - p1_lat) * (p2_lng - p1_lng) / (p2_lat - p1_lat) + p1_lng
                        if p1_lng == p2_lng or point_lng <= point_lon_intersects:
                            inside = not inside
            p1_lat, p1_lng = p2_lat, p2_lng
        return inside


PROVIDER_SPEC = ProviderSpec(
    key=PROVIDER_KEY,
    name=PROVIDER_NAME,
    schema_builder=build_schema,
    validate_config=validate_config,
    setup_provider=setup_provider,
    allow_multiple=True,
)
