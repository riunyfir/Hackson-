import asyncio
import traceback
import sys
sys.path.insert(0, r"D:\美团hackson")
from utils.geo import geocode

async def main():
    try:
        loc, addr = await geocode("朝阳大悦城")
        with open(r"D:\美团hackson\geo_test_result.txt", "w", encoding="utf-8") as f:
            f.write(f"OK: loc={loc}, addr={addr}\n")
    except Exception as e:
        with open(r"D:\美团hackson\geo_test_result.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())

asyncio.run(main())