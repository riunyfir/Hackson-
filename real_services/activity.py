"""高德 POI 活动搜索服务。
搜索：使用高德 POI API 的体育休闲/娱乐类 POI 类型码搜索活动场所。
购票：第三方票务平台（大麦/猫眼）无公开 API，保留 Mock 实现。
"""
import random
import asyncio
from real_services.base import RealService, ServiceTimeoutError, ServiceUnavailableError

AMAP_KEY = "a616609dcc7a04cf287e6c80361302c9"

# 活动相关 POI 类型码：080100 运动场所 / 080200 娱乐场所 / 080300 休闲场所 / 080400 影剧院 / 080500 游乐园 / 080600 其他
ACTIVITY_TYPES = "080100|080200|080300|080400|080500|080600"

# 标签到关键词的映射
TAG_KEYWORD_MAP = {
    "kid_friendly": "亲子 儿童 乐园",
    "indoor": "室内",
    "outdoor": "户外 公园",
    "sports": "运动 体育 健身",
    "entertainment": "KTV 电影 演出",
    "culture": "展览 博物馆 美术馆",
    "thrill": "过山车 蹦极 攀岩",
    "social": "聚会 桌游 密室逃脱",
}


class RealActivityService(RealService):
    """活动搜索：高德 POI 真实 API；购票：Mock 兜底"""

    def __init__(self):
        super().__init__(name="ActivityService", timeout=5.0)

    async def call(self, params: dict, timeout: float | None = None) -> dict:
        """
        覆盖基类 call：action="search" 走 HTTP API；
        action="order" 走 Mock（票务无公开 API）。
        """
        action = params.get("action", "search")
        if action == "order":
            await asyncio.sleep(0.3)
            return self._mock_order(params)
        return await super().call(params, timeout)

    # ==================== 搜索（真实 API）====================

    def _build_params(self, params: dict) -> tuple[str, dict, dict]:
        # 搜索中心 = 用户位置，由 collect_location 保证不为空
        location = params.get("location", "")
        radius = params.get("distance_km", 10) * 1000

        keywords = params.get("keywords", "")
        tags = params.get("tags", [])
        if tags:
            mapped = "|".join(TAG_KEYWORD_MAP.get(t, t) for t in tags)
            keywords = mapped if not keywords else keywords + "|" + mapped

        url = "https://restapi.amap.com/v3/place/around"
        query = {
            "key": AMAP_KEY,
            "location": location,
            "radius": radius,
            "types": ACTIVITY_TYPES,
            "keywords": keywords,
            "offset": 20,
            "page": 1,
            "extensions": "all",
        }
        return url, query, {}

    def _parse_response(self, raw_data: dict, original_params: dict = None) -> dict:
        pois = raw_data.get("pois", [])
        if not pois:
            return {"items": []}

        items = []
        for poi in pois[:10]:
            loc_raw = poi.get("location", "")
            lon, lat = self._parse_lonlat(loc_raw)
            address = poi.get("address", "")
            poi_type = poi.get("type", "")
            rating = float(poi.get("biz_ext", {}).get("rating", "4.0") or "4.0")

            # 根据 POI 类型估算票价
            price_amount = self._estimate_price(poi_type)

            full_addr = address if address else poi.get("name", "")
            items.append({
                "id": poi.get("id", ""),
                "name": poi.get("name", ""),
                "description": address,
                "tags": poi_type.split(";") if poi_type else [],
                "price_level": self._price_level(price_amount),
                "price_amount": price_amount,
                "distance_km": float(poi.get("distance", 0)) / 1000 if poi.get("distance") else 3.0,
                "availability": True,
                "available_slots": ["14:00", "16:00", "19:00"],
                "location": f"{lon},{lat}",
                "full_address": full_addr,
                "latitude": lat,
                "longitude": lon,
                "extra": {
                    "tel": poi.get("tel", ""),
                    "photos": [p.get("url", "") for p in (poi.get("photos", []) or [])[:3] if p.get("url")],
                    "remaining_tickets": 0,  # 真实 API 无法获取
                    "source": "高德POI",
                },
            })

        return {"items": items, "total": raw_data.get("count", 0)}

    # ==================== 购票（Mock 兜底）====================

    def _mock_order(self, params: dict) -> dict:
        """模拟购票：第三方票务平台均无公开 API。"""
        if random.random() < 0.1:
            raise ServiceUnavailableError("Tickets sold out — 第三方票务平台（大麦/猫眼）无公开 API，此为模拟错误")
        people = params.get("people_count", 1)
        price_each = random.randint(30, 150)
        return {
            "status": "ordered",
            "activity": params.get("activity_name", ""),
            "tickets": people,
            "total_price": people * price_each,
            "order_id": f"MOCK-ORD-{random.randint(10000, 99999)}",
            "note": "购票走 Mock：大麦/猫眼无公开 API。搜索活动信息已对接真实高德 POI。",
        }

    # ==================== 辅助方法 ====================

    @staticmethod
    def _parse_lonlat(loc: str) -> tuple[float, float]:
        if loc and "," in loc:
            parts = loc.split(",")
            return float(parts[0]), float(parts[1])
        return 0.0, 0.0

    @staticmethod
    def _estimate_price(poi_type: str) -> float:
        if any(t in poi_type for t in ["影剧院", "电影院", "音乐厅"]):
            return 80
        elif any(t in poi_type for t in ["游乐园", "主题公园", "水上乐园"]):
            return 150
        elif "KTV" in poi_type:
            return 200
        elif any(t in poi_type for t in ["运动场所", "健身"]):
            return 60
        elif any(t in poi_type for t in ["展览馆", "美术馆", "博物馆"]):
            return 50
        return 40

    @staticmethod
    def _price_level(amount: float) -> str:
        if amount <= 60:
            return "low"
        elif amount <= 120:
            return "medium"
        return "high"