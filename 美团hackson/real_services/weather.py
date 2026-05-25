"""高德地图天气 API 服务。根据用户位置坐标逆地理编码获取 adcode，再查询实时天气。"""
import httpx
from real_services.base import RealService

AMAP_KEY = "a616609dcc7a04cf287e6c80361302c9"


class RealWeatherService(RealService):
    """高德天气：实时 + 预报（根据用户坐标查询对应区域天气）"""

    def __init__(self):
        super().__init__(name="WeatherService", timeout=5.0)

    def _build_params(self, params: dict) -> tuple[str, dict, dict]:
        """实现抽象方法，但 call 已覆盖"""
        return "", {}, {}

    async def _get_adcode(self, location: str) -> str:
        """通过逆地理编码将坐标转换为 adcode（行政区划代码）。"""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://restapi.amap.com/v3/geocode/regeo",
                params={"key": AMAP_KEY, "location": location},
                timeout=5.0,
            )
            r.raise_for_status()
            data = r.json()
        if data.get("status") == "1":
            adcode = data["regeocode"].get("addressComponent", {}).get("adcode", "")
            if adcode:
                return adcode
        return "110000"  # 最终兜底：北京市

    async def call(self, params: dict, timeout: float | None = None) -> dict:
        """根据用户坐标获取 adcode，再并发请求实时天气和预报。"""
        import asyncio
        effective_timeout = timeout or self.timeout

        # 从用户坐标获取 adcode
        location = params.get("location", "")
        if location:
            try:
                adcode = await self._get_adcode(location)
            except Exception:
                adcode = "110000"
        else:
            adcode = params.get("adcode", "110000")

        async def fetch(extensions):
            url = "https://restapi.amap.com/v3/weather/weatherInfo"
            p = {"key": AMAP_KEY, "city": adcode, "extensions": extensions}
            async with httpx.AsyncClient() as client:
                try:
                    r = await client.get(url, params=p, timeout=effective_timeout)
                    r.raise_for_status()
                    return r.json()
                except Exception as e:
                    return {"error": str(e)}

        live_result, forecast_result = await asyncio.gather(
            fetch("base"),
            fetch("all"),
        )
        return self._parse_response(live_result, forecast_result, params)

    def _parse_response(self, live_raw: dict, forecast_raw: dict, params: dict) -> dict:
        """解析高德天气响应，输出与其他服务一致的结构。"""
        # 实时天气
        lives = live_raw.get("lives", [])
        live = lives[0] if lives else {}
        weather_text = live.get("weather", "未知")
        temp = live.get("temperature", "N/A")
        humidity = live.get("humidity", "N/A")
        wind_dir = live.get("winddirection", "N/A")
        wind_power = live.get("windpower", "N/A")
        wind = f"{wind_dir} {wind_power}级"
        report_time = live.get("reporttime", "")

        # 预报
        forecasts = forecast_raw.get("forecasts", [])
        casts = forecasts[0].get("casts", []) if forecasts else []
        today = casts[0] if casts else {}
        today_day = today.get("dayweather", "未知")
        today_night = today.get("nightweather", "未知")
        day_temp = today.get("daytemp", "N/A")
        night_temp = today.get("nighttemp", "N/A")

        # 生存建议
        advice = self._build_advice(weather_text, temp, humidity)

        summary = f"天气{weather_text}，{temp}°C，{wind}，湿度{humidity}%。"
        summary += f"今天白天{today_day}，夜间{today_night}，{night_temp}~{day_temp}°C。"

        return {
            "items": [{
                "id": "weather_live",
                "name": summary,
                "description": summary,
                "tags": [weather_text, "weather"],
                "extra": {
                    "condition": weather_text,
                    "temperature": f"{temp}°C，白天{day_temp}°C / 夜间{night_temp}°C",
                    "advice": advice,
                    "impact": f"当前{weather_text}，{temp}°C，{wind}",
                    "detail": {
                        "temp": temp,
                        "humidity": humidity,
                        "wind": wind,
                        "day_weather": today_day,
                        "night_weather": today_night,
                        "day_temp": day_temp,
                        "night_temp": night_temp,
                        "report_time": report_time,
                    },
                },
            }],
            "summary": summary,
        }

    @staticmethod
    def _build_advice(weather: str, temp: str, humidity: str) -> str:
        parts = []
        try:
            t = float(temp)
        except (ValueError, TypeError):
            t = 20
        if t >= 35:
            parts.append("注意防暑降温")
        elif t <= 5:
            parts.append("注意保暖")
        if weather in ("雨", "阵雨", "小雨", "中雨", "大雨", "暴雨", "雷阵雨", "雷雨"):
            parts.append("建议带伞")
        try:
            h = float(humidity)
            if h > 80:
                parts.append("湿度较高，体感闷热")
        except (ValueError, TypeError):
            pass
        return "；".join(parts) if parts else "适合出行，享受下午时光"