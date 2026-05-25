"""Searcher Agent：并发搜索 + 降级 + 权重排序。"""
import asyncio
from models.messages import (
    SearchRequest, SearchResult, SearchQuery,
    ServiceCandidate, ServiceResult, ServiceType,
)
from mock_services.base import MockService, ServiceTimeoutError, ServiceUnavailableError
from real_services.base import RealService, ServiceTimeoutError as RealTimeoutError, ServiceUnavailableError as RealUnavailableError
from utils.logger import searcher_logger


class SearcherAgent:
    def __init__(self, services: dict[str, MockService | RealService]):
        self.services = services

    async def search(self, request: SearchRequest) -> SearchResult:
        """主入口：并发执行所有搜索"""
        tasks = []
        for query in request.queries:
            service = self.services.get(query.service)
            if service is None:
                tasks.append(asyncio.sleep(0, result=None))
                continue
            tasks.append(
                self._search_with_fallback(service, query, request.preference_weights)
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        service_results = []
        for i, result in enumerate(results):
            query = request.queries[i]
            if isinstance(result, Exception):
                service_results.append(ServiceResult(
                    service=query.service,
                    candidates=[],
                    status="failed",
                    error_message=str(result),
                ))
            elif result is None:
                service_results.append(ServiceResult(
                    service=query.service,
                    candidates=[],
                    status="failed",
                    error_message="Service not found",
                ))
            else:
                service_results.append(result)

        success_count = sum(1 for r in service_results if r.status == "success")
        if success_count == len(service_results):
            overall = "full"
        elif success_count == 0:
            overall = "failed"
        else:
            overall = "partial"

        searcher_logger.info(
            f"搜索完成: {success_count}/{len(service_results)} 成功, 状态={overall}"
        )
        return SearchResult(
            task_id=request.task_id,
            results=service_results,
            overall_status=overall,
        )

    async def _search_with_fallback(
        self, service: MockService | RealService, query: SearchQuery, weights: dict
    ) -> ServiceResult:
        """调用单个服务，带降级逻辑"""
        try:
            result = await service.call(query.params, timeout=2.0)
            candidates = self._parse_and_rank(result, weights)
            return ServiceResult(
                service=query.service,
                candidates=candidates,
                status="success",
            )
        except (ServiceTimeoutError, RealTimeoutError, ServiceUnavailableError, RealUnavailableError):
            # 尝试降级
            if query.fallback_tags:
                try:
                    fallback_params = {**query.params, "tags": query.fallback_tags}
                    result = await service.call(fallback_params, timeout=2.0)
                    candidates = self._parse_and_rank(result, weights)
                    searcher_logger.warning(f"{query.service} 降级搜索成功")
                    return ServiceResult(
                        service=query.service,
                        candidates=candidates,
                        status="success",
                        fallback_used=True,
                    )
                except Exception:
                    pass
            return ServiceResult(
                service=query.service,
                candidates=[],
                status="timeout",
                error_message="Service timeout",
            )
        except Exception as e:
            return ServiceResult(
                service=query.service,
                candidates=[],
                status="failed",
                error_message=str(e),
            )

    def _parse_and_rank(self, raw_result: dict, weights: dict) -> list[ServiceCandidate]:
        """将原始结果解析并排序"""
        items = raw_result.get("items", [])
        candidates = []
        for item in items:
            try:
                c = ServiceCandidate(**item)
                candidates.append(c)
            except Exception:
                continue

        # 按权重排序
        for c in candidates:
            score = sum(weights.get(t, 1.0) for t in c.tags)
            c.extra["_score"] = score

        candidates.sort(key=lambda x: x.extra.get("_score", 0), reverse=True)
        return candidates[:5]