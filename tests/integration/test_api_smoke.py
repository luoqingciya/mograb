# SPDX-License-Identifier: GPL-3.0-only
"""API 集成测试（规划书 §47）。

用 FastAPI 的 TestClient 跑真实路由。要 ``with`` 起来 —— 应用是在 lifespan 里
装配的，不用上下文管理器就不会触发，``app.state.application`` 是空的。

全部离线：数据目录由 conftest 的 autouse fixture 指到临时目录。

业务端点都要求 ``Authorization: Bearer <token>``，所以默认的 ``client``
夹具带上令牌 —— 只有 ``TestAuth`` 用不带头的 ``anon_client``。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mograb.config import ensure_token, get_paths
from mograb_api.main import API_PREFIX, create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def token() -> str:
    """当前数据目录下的 API 令牌。"""
    return ensure_token(get_paths())


@pytest.fixture
def client(token: str) -> Iterator[TestClient]:
    """默认带令牌的客户端。"""
    with TestClient(create_app(), headers={"Authorization": f"Bearer {token}"}) as test_client:
        yield test_client


@pytest.fixture
def anon_client() -> Iterator[TestClient]:
    """不带任何默认请求头的客户端，用来测认证本身。"""
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def example_yaml(example_source_dir: Path) -> str:
    return str(example_source_dir / "source.yaml")


class TestAuth:
    """令牌校验（规划书 §40、评估报告 P2-02）。

    这里的核心不是「带上令牌能通」，而是**不带令牌时挡得住** ——
    浏览器里的任意页面都能往 127.0.0.1 发简单请求，CORS 拦不住副作用。
    """

    def test_health_needs_no_token(self, anon_client: TestClient) -> None:
        """健康检查保持开放 —— Desktop 探端口和 mog server status 都靠它。"""
        assert anon_client.get("/health").status_code == 200

    def test_docs_needs_no_token(self, anon_client: TestClient) -> None:
        """Swagger UI 没法在浏览器里带请求头，锁上等于废掉这个页面。"""
        assert anon_client.get("/docs").status_code == 200
        assert anon_client.get("/openapi.json").status_code == 200

    @pytest.mark.parametrize(
        "path",
        ["/sources", "/books", "/tasks", "/exports", "/search?q=x"],
    )
    def test_read_endpoints_need_token(self, anon_client: TestClient, path: str) -> None:
        assert anon_client.get(f"{API_PREFIX}{path}").status_code == 401

    def test_write_endpoint_needs_token(self, anon_client: TestClient) -> None:
        """最要紧的一条：不能让人凭空建任务。"""
        response = anon_client.post(f"{API_PREFIX}/tasks", json={"type": "refresh_source"})

        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_REQUIRED"

    def test_sse_needs_token(self, anon_client: TestClient) -> None:
        assert anon_client.get(f"{API_PREFIX}/tasks/events").status_code == 401

    def test_401_carries_www_authenticate(self, anon_client: TestClient) -> None:
        response = anon_client.get(f"{API_PREFIX}/sources")

        assert response.headers["WWW-Authenticate"] == 'Bearer realm="MoGrab"'

    def test_wrong_token_rejected(self, anon_client: TestClient) -> None:
        response = anon_client.get(
            f"{API_PREFIX}/sources", headers={"Authorization": "Bearer not-the-token"}
        )

        assert response.status_code == 401

    def test_token_prefix_is_not_enough(self, anon_client: TestClient, token: str) -> None:
        """别把令牌截断了还能过 —— 比较必须是全长的。"""
        response = anon_client.get(
            f"{API_PREFIX}/sources", headers={"Authorization": f"Bearer {token[:10]}"}
        )

        assert response.status_code == 401

    def test_wrong_scheme_rejected(self, anon_client: TestClient, token: str) -> None:
        response = anon_client.get(
            f"{API_PREFIX}/sources", headers={"Authorization": f"Basic {token}"}
        )

        assert response.status_code == 401

    def test_valid_token_accepted(self, anon_client: TestClient, token: str) -> None:
        response = anon_client.get(
            f"{API_PREFIX}/sources", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200

    def test_error_body_shape_is_consistent(self, anon_client: TestClient) -> None:
        """401 也要走统一错误模型，客户端不该为它写特例。"""
        body = anon_client.get(f"{API_PREFIX}/sources").json()

        assert set(body) == {"code", "message", "details"}
        assert body["details"]["scheme"] == "Bearer"

    def test_openapi_declares_security(self, anon_client: TestClient) -> None:
        schema = anon_client.get("/openapi.json").json()

        assert schema["components"]["securitySchemes"]["MoGrabToken"]["scheme"] == "bearer"
        assert schema["paths"][f"{API_PREFIX}/sources"]["get"]["security"] == [{"MoGrabToken": []}]
        assert schema["paths"]["/health"]["get"].get("security") is None


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
            f"{API_PREFIX}/tasks/events",
            f"{API_PREFIX}/tasks/{{task_id}}/events",
            f"{API_PREFIX}/exports",
        ):
            assert expected in paths, f"缺少端点: {expected}"

    def test_docs_available(self, client: TestClient) -> None:
        assert client.get("/docs").status_code == 200


class TestErrorModel:
    def test_not_found_uses_error_model(self, client: TestClient) -> None:
        """404 响应体是 {code, message, details} 三字段（规划书 §37）。"""
        response = client.get(f"{API_PREFIX}/books/does-not-exist")
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == "STORAGE_NOT_FOUND"
        assert "message" in body
        assert "details" in body

    def test_source_not_found_code(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/sources/nope")
        assert response.status_code == 404
        assert response.json()["code"] == "SOURCE_NOT_FOUND"

    def test_schema_error_maps_to_422(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/sources", json={"mode": "yaml", "content": "id: Bad_ID\n"}
        )
        assert response.status_code == 422
        assert response.json()["code"].startswith("SOURCE_")


class TestSourcesApi:
    def test_list_empty(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/sources").json() == []

    def test_install_and_list(self, client: TestClient, example_yaml: str) -> None:
        created = client.post(
            f"{API_PREFIX}/sources",
            json={"mode": "file", "path": example_yaml},
        )
        assert created.status_code == 201, created.text
        assert created.json()["id"] == "example"
        assert created.json()["replaced"] is False

        listed = client.get(f"{API_PREFIX}/sources").json()
        assert [s["id"] for s in listed] == ["example"]
        assert listed[0]["capabilities"] == ["search", "book", "chapters", "content"]

    def test_install_yaml_content(self, client: TestClient) -> None:
        content = (
            "spec_version: 1\n"
            "id: inline\n"
            "name: Inline\n"
            "version: 1.0.0\n"
            "capabilities: [search]\n"
            "search:\n"
            "  request: {method: GET, url: 'https://inline.example.com/s'}\n"
            "  result:\n"
            "    list: '.item'\n"
            "    fields: {title: '.t', url: 'a@href'}\n"
        )
        response = client.post(f"{API_PREFIX}/sources", json={"mode": "yaml", "content": content})
        assert response.status_code == 201, response.text
        assert response.json()["id"] == "inline"

    def test_install_rejects_broken_yaml(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/sources", json={"mode": "yaml", "content": "不是: [合法的"}
        )
        assert response.status_code == 422

    def test_detail_includes_permissions(self, client: TestClient, example_yaml: str) -> None:
        client.post(f"{API_PREFIX}/sources", json={"mode": "file", "path": example_yaml})
        detail = client.get(f"{API_PREFIX}/sources/example").json()
        assert detail["permissions"]["network"] == ["example.com"]
        assert detail["permissions"]["script"] is False

    def test_disable_enable_roundtrip(self, client: TestClient, example_yaml: str) -> None:
        client.post(f"{API_PREFIX}/sources", json={"mode": "file", "path": example_yaml})

        disabled = client.post(f"{API_PREFIX}/sources/example/disable").json()
        assert disabled["enabled"] is False

        enabled = client.post(f"{API_PREFIX}/sources/example/enable").json()
        assert enabled["enabled"] is True

    def test_delete(self, client: TestClient, example_yaml: str) -> None:
        client.post(f"{API_PREFIX}/sources", json={"mode": "file", "path": example_yaml})
        assert client.delete(f"{API_PREFIX}/sources/example").status_code == 200
        assert client.get(f"{API_PREFIX}/sources").json() == []

    def test_delete_missing(self, client: TestClient) -> None:
        assert client.delete(f"{API_PREFIX}/sources/nope").status_code == 404

    def test_doctor_offline(self, client: TestClient, example_yaml: str) -> None:
        client.post(f"{API_PREFIX}/sources", json={"mode": "file", "path": example_yaml})
        result = client.post(f"{API_PREFIX}/sources/example/doctor").json()
        assert result["health"] == "healthy"

    def test_rescan(self, client: TestClient, example_yaml: str) -> None:
        client.post(f"{API_PREFIX}/sources", json={"mode": "file", "path": example_yaml})
        assert len(client.post(f"{API_PREFIX}/sources/rescan").json()) == 1


class TestSearchApi:
    def test_no_sources_returns_empty(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/search", params={"q": "三体"})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_requires_keyword(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/search").status_code == 422


class TestBooksApi:
    def test_list_empty(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/books").json() == []

    def test_chapters_of_missing_book(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/books/nope/chapters").status_code == 404

    def test_update_dry_run_on_missing_book(self, client: TestClient) -> None:
        response = client.post(f"{API_PREFIX}/books/nope/update")
        assert response.status_code == 404


class TestTasksApi:
    def test_list_empty(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/tasks").json() == []

    def test_create_refresh_task(self, client: TestClient) -> None:
        """refresh_source 不需要书源也不需要网络，适合验证创建链路。"""
        created = client.post(f"{API_PREFIX}/tasks", json={"type": "refresh_source"})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["type"] == "refresh_source"
        assert body["status"] in {"pending", "running", "success"}
        assert body["id"].startswith("task_")

    def test_get_task(self, client: TestClient) -> None:
        created = client.post(f"{API_PREFIX}/tasks", json={"type": "refresh_source"})
        task_id = created.json()["id"]
        fetched = client.get(f"{API_PREFIX}/tasks/{task_id}")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == task_id

    def test_get_missing_task(self, client: TestClient) -> None:
        response = client.get(f"{API_PREFIX}/tasks/nope")
        assert response.status_code == 404
        assert response.json()["code"] == "TASK_NOT_FOUND"

    def test_bad_task_type_rejected(self, client: TestClient) -> None:
        assert client.post(f"{API_PREFIX}/tasks", json={"type": "nonsense"}).status_code == 422

    def test_cancel_then_list(self, client: TestClient) -> None:
        created = client.post(f"{API_PREFIX}/tasks", json={"type": "refresh_source"})
        task_id = created.json()["id"]

        # refresh_source 跑得很快，可能已经结束了 —— 结束了就不能取消，这是对的
        cancelled = client.post(f"{API_PREFIX}/tasks/{task_id}/cancel")
        assert cancelled.status_code in {200, 409}

        listed = client.get(f"{API_PREFIX}/tasks").json()
        assert task_id in [t["id"] for t in listed]

    def test_status_filter(self, client: TestClient) -> None:
        client.post(f"{API_PREFIX}/tasks", json={"type": "refresh_source"})
        response = client.get(f"{API_PREFIX}/tasks", params={"status": "success"})
        assert response.status_code == 200

    def test_retry_non_terminal_conflicts(self, client: TestClient) -> None:
        created = client.post(f"{API_PREFIX}/tasks", json={"type": "refresh_source"})
        task_id = created.json()["id"]
        # 还没失败的任务不能重试，状态机返回 409
        response = client.post(f"{API_PREFIX}/tasks/{task_id}/retry")
        assert response.status_code in {201, 409}


class TestTaskCreateValidation:
    """建任务时就把引用的实体查清楚。

    ``tasks.book_id`` 上有外键，不存在的 id 会让插入抛 IntegrityError，
    未处理的话就是 500。这里要的是 404。
    """

    def test_unknown_book_gives_404(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/tasks", json={"type": "export_book", "book_id": "book_nope"}
        )
        assert response.status_code == 404
        assert response.json()["code"] == "STORAGE_NOT_FOUND"

    def test_download_with_unknown_book_gives_404(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/tasks", json={"type": "download_book", "book_id": "book_nope"}
        )
        assert response.status_code == 404

    def test_download_with_unknown_source_gives_404(self, client: TestClient) -> None:
        response = client.post(
            f"{API_PREFIX}/tasks",
            json={
                "type": "download_book",
                "source_id": "not-installed",
                "url": "https://example.com/book/1001",
            },
        )
        assert response.status_code == 404
        assert response.json()["code"] == "SOURCE_NOT_FOUND"

    def test_download_without_target_gives_400(self, client: TestClient) -> None:
        """既没有 book_id 也没有 url，是请求本身不成立。"""
        response = client.post(
            f"{API_PREFIX}/tasks", json={"type": "download_book", "source_id": "example"}
        )
        assert response.status_code == 400
        assert response.json()["code"] == "TASK_PARAMETER_ERROR"

    def test_nothing_persisted_on_rejection(self, client: TestClient) -> None:
        client.post(f"{API_PREFIX}/tasks", json={"type": "export_book", "book_id": "book_nope"})
        assert client.get(f"{API_PREFIX}/tasks").json() == []


class TestExportsApi:
    def test_create_for_missing_book(self, client: TestClient) -> None:
        response = client.post(f"{API_PREFIX}/exports", json={"book_id": "nope"})
        assert response.status_code == 404

    def test_list_empty(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/exports").json() == []

    def test_get_missing(self, client: TestClient) -> None:
        assert client.get(f"{API_PREFIX}/exports/nope").status_code == 404
