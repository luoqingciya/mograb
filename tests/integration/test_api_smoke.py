# SPDX-License-Identifier: GPL-3.0-only
"""API 集成冒烟测试（规划书 §47 Integration Test）。

验证：应用可构造、路由已注册、健康检查可用、错误模型符合约定。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mograb_api.main import API_PREFIX, create_app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


class TestAppStructure:
    def test_health_endpoint(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_openapi_contains_v1_paths(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        paths = set(schema["paths"])
        for expected in (
            f"{API_PREFIX}/sources",
            f"{API_PREFIX}/search",
            f"{API_PREFIX}/books",
            f"{API_PREFIX}/tasks",
            f"{API_PREFIX}/tasks/{{task_id}}/events",
            f"{API_PREFIX}/exports",
        ):
            assert expected in paths, f"缺少端点: {expected}"

    def test_docs_available(self, client: TestClient) -> None:
        assert client.get("/docs").status_code == 200


class TestErrorModel:
    def test_not_found_uses_error_model(self, client: TestClient) -> None:
        """404 响应体应包含 code / message / details 三字段（规划书 §37）。"""
        response = client.get(f"{API_PREFIX}/books/does-not-exist")
        assert response.status_code == 404
        body = response.json()
        assert "detail" in body  # FastAPI HTTPException 形态

    def test_not_implemented_endpoints_return_501(self, client: TestClient) -> None:
        """骨架阶段未实现的写接口返回 501 而非 500。"""
        response = client.post(f"{API_PREFIX}/tasks", json={"type": "download_book"})
        assert response.status_code == 501
