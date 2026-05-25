"""高德地图地理编码工具。"""
import httpx
from typing import Optional

# 高德 API Key（与 rest., activity 服务共用）
GEO_KEY = "a616609dcc7a04cf287e6c80361302c9"
GEO_URL = "https://restapi.amap.com/v3/geocode/geo"


async def geocode(address: str) -> tuple[str, str]:
    """
    地名 → (坐标, 完整地址)。
    
    Args:
        address: 地名，如 "朝阳大悦城" 或 "北京市朝阳区"
    
    Returns:
        (coordinates, full_address): 坐标格式 "lon,lat"，完整地址
    
    Raises:
        ValueError: 地理编码失败
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(GEO_URL, params={
            "key": GEO_KEY,
            "address": address,
            "city": "北京",
        })
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "1" or int(data.get("count", 0)) == 0:
        raise ValueError(f"地理编码失败: {data.get('info', '未知错误')}, address={address}")

    geocode_info = data["geocodes"][0]
    location = geocode_info["location"]          # "116.443239,39.921469"
    full_address = geocode_info.get("formatted_address", geocode_info.get("address", address))
    return location, full_address


async def reverse_geocode(location: str) -> str:
    """
    坐标 → 地址（逆地理编码，备用）。
    
    Args:
        location: "lon,lat"
    
    Returns:
        格式化地址
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://restapi.amap.com/v3/geocode/regeo",
            params={"key": GEO_KEY, "location": location}
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "1":
        raise ValueError(f"逆地理编码失败: {data.get('info')}")

    return data["regeocode"]["formatted_address"]


def parse_coordinates(raw: str) -> Optional[tuple[float, float]]:
    """
    解析用户输入的坐标字符串。
    
    支持格式：
      - "116.443239,39.921469"
      - "116.443239, 39.921469"
      - "39.921469,116.443239" 自动判断纬度在前
    
    Returns:
        (longitude, latitude) 或 None
    """
    import re
    parts = re.split(r'[,\s]+', raw.strip())
    if len(parts) < 2:
        return None
    try:
        a, b = float(parts[0]), float(parts[1])
    except ValueError:
        return None

    # 简单判断：纬度绝对值 ≤ 90，经度绝对值 ≤ 180
    if -90 <= a <= 90 and -180 <= b <= 180:
        lat, lon = a, b
    elif -180 <= a <= 180 and -90 <= b <= 90:
        lon, lat = a, b
    else:
        return None

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lon, lat


def format_distance(meters: float) -> str:
    """将米数格式化为可读距离。"""
    if meters < 1000:
        return f"{int(meters)}m"
    return f"{meters / 1000:.1f}km"