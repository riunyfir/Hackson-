"""高德地图 POI 搜索 API 服务。
用于餐厅/活动/鲜花等周边搜索，通过 params 中的 types 切换领域。
"""
from real_services.base import RealService

AMAP_KEY = "a616609dcc7a04cf287e6c80361302c9"

# 高德 POI 类型码参考
POI_TYPE_MAP = {
    "restaurant": {
        "types": "050000|060000",  # 餐饮
        "keywords": "",
    },
    "activity": {
        "types": "080000|080100|080200|080300|080400|080500|080600",  # 体育休闲+娱乐
        "keywords": "",
    },
    "flower": {
        "types": "060900",  # 花店
        "keywords": "鲜花",
    },
}

# 简易城市编码映射
CITY_MAP = {
    "北京": "010",
    "上海": "020",
    "广州": "280",
    "深圳": "440300",
}


class RealRestaurantService(RealService):
    """高德 POI 搜索：餐厅"""

    def __init__(self):
        super().__init__(name="RestaurantService", timeout=5.0)

    def _build_params(self, params: dict) -> tuple[str, dict, dict]:
        # 搜索中心 = 用户位置，由 collect_location 保证不为空
        location = params.get("location", "")
        radius = params.get("distance_km", 10) * 1000  # km → m

        keywords = params.get("keywords", "")
        tags = params.get("tags", [])
        if tags:
            keywords = "|".join(tags) if not keywords else keywords + "|" + "|".join(tags)

        poi_config = POI_TYPE_MAP.get(params.get("poi_type", "restaurant"), POI_TYPE_MAP["restaurant"])
        types = poi_config["types"]
        if not keywords:
            keywords = poi_config["keywords"]

        url = "https://restapi.amap.com/v3/place/around"
        query = {
            "key": AMAP_KEY,
            "location": location,
            "radius": radius,
            "types": types,
            "keywords": keywords,
            "offset": 20,
            "page": 1,
            "extensions": "all",
        }

        # 存入实例变量供 _parse_response 使用
        self._original_params = params
        return url, query, {}

    def _parse_response(self, raw_data: dict, original_params: dict = None) -> dict:
        pois = raw_data.get("pois", [])
        if not pois:
            return {"items": []}

        items = []
        for poi in pois[:10]:
            location = poi.get("location", "")
            lon_str, lat_str = ("", "")
            if location and "," in location:
                lon_str, lat_str = location.split(",")

            items.append({
                "id": poi.get("id", ""),
                "name": poi.get("name", ""),
                "description": poi.get("address", ""),
                "tags": poi.get("type", "").split(";"),
                "price_level": "medium",
                "price_amount": float(poi.get("biz_ext", {}).get("cost", "0").replace("￥", "") or 80),
                "distance_km": float(poi.get("distance", 0)) / 1000 if poi.get("distance") else 5,
                "full_address": poi.get("address", ""),
                "latitude": float(lat_str) if lat_str else 0,
                "longitude": float(lon_str) if lon_str else 0,
                "availability": True,
                "available_slots": ["17:30", "18:00", "18:30"],
                "extra": {
                    "tel": poi.get("tel", ""),
                    "rating": float(poi.get("biz_ext", {}).get("rating", "4.0") or "4.0"),
                    "photos": [p.get("url", "") for p in (poi.get("photos", []) or [])[:3] if p.get("url")],
                },
            })

        return {"items": items, "total": raw_data.get("count", 0)}