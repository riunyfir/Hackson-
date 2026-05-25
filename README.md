# 美团Hackson - 智能活动规划系统

一个基于多Agent协作的智能活动规划系统，能够理解用户意图、搜索服务、生成方案并自动执行预订。

## 项目结构

```
美团hackson/
├── agents/                    # Agent层（4个核心Agent）
│   ├── __init__.py
│   ├── planner.py           # Planner Agent：意图解析 + 方案生成
│   ├── searcher.py          # Searcher Agent：并发搜索 + 降级
│   ├── executor.py          # Executor Agent：确认循环 + 批量执行
│   └── memory.py            # Memory Agent：偏好查询与记录
├── config/                   # 配置
│   ├── __init__.py
│   └── settings.py          # Pydantic配置
├── data/
│   ├── mock/                # Mock数据集
│   │   ├── restaurants.json
│   │   ├── activities.json
│   │   ├── weather.json
│   │   └── flowers.json
│   └── runtime/             # 运行时数据（偏好记录等）
├── mock_services/           # Mock服务层（5个服务）
│   ├── __init__.py
│   ├── base.py             # 基类（超时、失败率模拟）
│   ├── restaurant.py       # 餐厅搜索 + 订座
│   ├── activity.py         # 活动搜索 + 购票
│   ├── weather.py          # 天气查询
│   ├── flower.py           # 鲜花配送
│   └── messenger.py        # 消息发送
├── models/                  # 数据模型
│   ├── __init__.py
│   └── messages.py         # 所有Pydantic模型
├── utils/                   # 工具模块
│   ├── __init__.py
│   ├── logger.py           # Rich日志
│   ├── display.py          # CLI美化输出
│   └── retry.py            # 异步重试装饰器
├── requirements.txt         # 依赖列表
├── Makefile                # 快捷命令
├── .env.example            # 环境变量示例
├── .gitignore
├── main.py                 # 主入口
└── README.md
```

## 核心功能

### 1. 多Agent协作流程
```
用户输入 → Planner解析意图 → Searcher并发搜索 → 生成多个方案 → 
用户选择 → 转化为执行计划 → Executor确认循环 → 批量执行 → 记录偏好
```

### 2. 支持场景
- **亲子场景** (family): 带孩子的家庭活动，优先考虑儿童友好、安全
- **朋友聚会** (friends): 朋友社交，优先考虑互动性、氛围
- **情侣约会** (couple): 浪漫氛围，优先考虑环境、私密性
- **个人探索** (solo): 个人活动，优先考虑灵活性、兴趣匹配

### 3. 服务覆盖
- **餐厅搜索 + 订座** (restaurant): 按标签、距离、人数过滤
- **活动搜索 + 购票** (activity): 按标签、时长、人数过滤
- **天气查询** (weather): 影响户外/室内活动推荐
- **鲜花配送** (flower): 庆祝场景自动触发
- **消息通知** (messenger): 执行结果通知

### 4. 智能特性
- **意图解析**: LLM解析用户自然语言，提取结构化参数
- **偏好记忆**: 记录历史选择，影响未来推荐权重
- **降级策略**: 服务失败时自动使用备选标签
- **确认循环**: 执行前反复确认，支持时间/项目/人数调整
- **并发执行**: 批量预订并行执行，提高效率

## 快速开始

### 1. 环境准备
```bash
# 克隆项目
git clone <repository>
cd 美团hackson

# 创建虚拟环境（推荐）
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入 OpenAI API Key
```

### 2. 运行演示
```bash
# 亲子场景演示
python main.py --demo family

# 朋友聚会演示
python main.py --demo friends
```

### 3. 交互模式
```bash
# 启动交互式规划
python main.py

# 示例输入：
# "这周末下午想带5岁孩子出去玩，找个地方吃饭，预算中等"
# "下午和几个朋友聚聚，找个有意思的活动，然后吃个饭，预算高一点"
```

## 开发指南

### 添加新服务
1. 在 `mock_services/` 创建新服务类，继承 `MockService`
2. 实现 `_handle` 方法，返回 `{"items": [...]}` 格式
3. 在 `data/mock/` 添加对应的JSON数据集
4. 在 `agents/searcher.py` 的 `SearcherAgent` 中添加服务映射
5. 在 `agents/planner.py` 的 `stage1_plan_search` 中添加搜索查询

### 修改搜索逻辑
- **标签系统**: 修改 `planner.py` 中的 `_get_restaurant_tags` 和 `_get_activity_tags`
- **权重计算**: 修改 `searcher.py` 中的 `_parse_and_rank` 方法
- **降级策略**: 修改 `searcher.py` 中的 `_search_with_fallback` 方法

### 调整确认流程
- **LLM调整**: `executor.py` 中的 `_llm_adjust` 方法
- **规则调整**: `executor.py` 中的 `_rule_adjust` 方法
- **调整轮次**: 修改 `ExecutorAgent.max_adjustment_rounds`

## 配置说明

### 环境变量 (.env)
```ini
OPENAI_API_KEY=sk-...          # OpenAI API Key
LOG_LEVEL=INFO                 # 日志级别：DEBUG/INFO/WARNING/ERROR
PREFERENCE_STORAGE=data/runtime/preferences.json  # 偏好存储路径
```

### 服务参数 (mock_services/base.py)
每个Mock服务可配置：
- `latency_range`: 延迟范围（秒）
- `failure_rate`: 失败率（0-1）
- `timeout`: 超时时间（秒）
- `data_file`: 数据集JSON路径

## 模型定义

所有数据模型定义在 `models/messages.py`，包括：

### 核心模型
- `ParsedIntent`: 解析后的用户意图
- `SearchQuery` / `SearchRequest` / `SearchResult`: 搜索相关
- `ServiceCandidate` / `ServiceResult`: 服务候选结果
- `TimelineSlot` / `Plan` / `PlanSet`: 方案规划
- `BookingAction` / `ExecutionPlan` / `ExecutionResult`: 执行相关
- `PreferenceRecord` / `PreferenceQueryResult`: 偏好记忆

### 类型枚举
- `ServiceType`: 服务类型（restaurant/activity/weather/flower）
- `SceneType`: 场景类型（family/friends/couple/solo）
- `BudgetLevel`: 预算等级（low/medium/high）

## 测试

```bash
# 运行所有测试
make test

# 运行特定模块测试
python -m pytest tests/test_planner.py -v

# 覆盖率报告
make coverage
```

## 部署

### 生产环境建议
1. **替换Mock服务**: 将 `mock_services/` 替换为真实API调用
2. **数据库持久化**: 将 `MemoryAgent` 的JSON存储改为数据库
3. **异步任务队列**: 将 `ExecutorAgent` 的执行改为任务队列
4. **监控告警**: 添加日志监控、性能指标、错误告警
5. **API网关**: 提供RESTful API接口

### Docker部署
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

## 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建Pull Request

## 许可证

MIT License

## 联系方式

项目维护者: [Your Name]
问题反馈: [GitHub Issues](https://github.com/your-repo/issues)

---

*本项目为美团Hackson参赛作品，展示多Agent协作在活动规划领域的应用。*