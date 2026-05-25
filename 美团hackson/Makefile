.PHONY: install run test demo clean

install:
	pip install -r requirements.txt

run:
	python main.py

test:
	pytest tests/ -v --asyncio-mode=auto

demo:
	@echo "=== 场景1: 小明家庭场景 ==="
	python main.py --demo family
	@echo ""
	@echo "=== 场景2: 小明朋友场景 ==="
	python main.py --demo friends

clean:
	powershell -Command "Get-ChildItem -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force"
	powershell -Command "if (Test-Path data/runtime/preferences.json) { Remove-Item data/runtime/preferences.json -Force }"
