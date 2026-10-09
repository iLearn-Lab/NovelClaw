from __future__ import annotations

import uuid

import pytest


def test_service_health_and_anonymous_entry(service):
    service.client.cookies.clear()
    assert service.client.get("/healthz").json() == {"ok": True}
    path = "/select-mode" if service.name == "auth-portal" else "/dashboard"
    response = service.client.get(path, follow_redirects=False)
    assert response.status_code == (200 if service.name == "auth-portal" else 303)


def test_all_templates_compile(service):
    for name in service.main.templates.env.list_templates():
        if name.endswith(".html"):
            service.main.templates.env.get_template(name)


def test_all_workspace_pages_render(signed_in):
    routes = ["/dashboard", "/providers", "/jobs", "/sessions"]
    if signed_in.name == "novelclaw":
        routes = ["/dashboard"] + [
            "/console/" + path
            for path in (
                "chat",
                "tasks",
                "sessions",
                "models",
                "env",
                "status",
                "skills",
                "agents",
                "mcp",
                "manuscript/read",
                "manuscript/outline",
                "manuscript/planning",
                "memory/banks",
                "memory/entries",
                "storyboard",
                "characters",
                "world",
                "style",
            )
        ]
    for route in routes:
        response = signed_in.client.get(route)
        assert response.status_code == 200, (route, response.text[:200])
        assert "<html" in response.text


def test_portal_preserves_browser_host(service):
    if service.name != "auth-portal":
        pytest.skip("Portal routing only")
    for host in ("localhost", "127.0.0.1"):
        response = service.client.get(
            f"http://{host}:8010/mode-b", follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"http://{host}:8012/dashboard"
    # Starlette 0.47's TestClient cannot parse IPv6 netlocs; exercise routing directly.
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "scheme": "http",
            "path": "/mode-b",
            "headers": [(b"host", b"[::1]:8010")],
        }
    )
    assert (
        service.main._workspace_url(request, "", "8012", "/dashboard")
        == "http://[::1]:8012/dashboard"
    )


def test_jobs_belong_to_their_author(signed_in):
    with signed_in.db.SessionLocal() as db:
        other = signed_in.models.User(
            email=f"other-{uuid.uuid4().hex}@example.test", password_hash="test"
        )
        db.add(other)
        db.flush()
        job = signed_in.models.GenerationJob(
            user_id=other.id,
            provider="deepseek",
            idea="private manuscript",
            status="succeeded",
        )
        db.add(job)
        db.commit()
        job_id = job.id
    for route in (
        f"/jobs/{job_id}/logs",
        f"/jobs/{job_id}/chapters",
        f"/jobs/{job_id}/download/output",
    ):
        assert signed_in.client.get(route).status_code == 404


@pytest.fixture
def manuscript(signed_in):
    if signed_in.name != "novelclaw":
        pytest.skip("NovelClaw editing API only")
    run_id = "test_" + uuid.uuid4().hex
    with signed_in.db.SessionLocal() as db:
        job = signed_in.models.GenerationJob(
            user_id=signed_in.user_id,
            provider="deepseek",
            idea="测试小说",
            status="succeeded",
            run_id=run_id,
        )
        db.add(job)
        db.commit()
    run_dir = signed_in.main._resolve_run_dir(run_id)
    chapters = run_dir / "chapters"
    chapters.mkdir(parents=True)
    chapter = chapters / "chapter_01_iter_1_final.txt"
    chapter.write_text("第一章\n原稿。\n", encoding="utf-8")
    return signed_in, run_id, chapter


def test_chapter_edit_detects_stale_draft_and_preserves_newer_text(manuscript):
    service, run_id, path = manuscript
    endpoint = f"/api/runs/{run_id}/chapters/1/content"
    response = service.client.post(
        endpoint, json={"content": "第一章\n修订稿。", "base_content": "第一章\n原稿。"}
    )
    assert response.status_code == 200
    stale = service.client.post(
        endpoint, json={"content": "旧窗口的修改", "base_content": "第一章\n原稿。"}
    )
    assert stale.status_code == 409
    assert path.read_text(encoding="utf-8") == "第一章\n修订稿。\n"


@pytest.mark.parametrize("body", ["{", "[]", "null", '"text"'])
def test_edit_rejects_invalid_json_without_server_error(manuscript, body):
    service, run_id, path = manuscript
    for endpoint in (
        f"/api/runs/{run_id}/chapters/1/content",
        f"/api/runs/{run_id}/memory-banks/story_premise/entries",
    ):
        response = service.client.post(
            endpoint, content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400
    assert path.read_text(encoding="utf-8") == "第一章\n原稿。\n"


def test_memory_edits_use_configured_storage_and_round_trip(manuscript):
    service, run_id, _ = manuscript
    endpoint = f"/api/runs/{run_id}/memory-banks/story_premise/entries"
    response = service.client.post(
        endpoint, json={"content": "月球城市", "topic": "测试小说"}
    )
    assert response.status_code == 200
    entry_id = response.json()["entry"]["id"]
    path = service.main._memory_index_candidates(run_id)[0]
    assert path.is_relative_to(service.temp)
    updated = service.client.post(
        f"{endpoint}/{entry_id}", json={"content": "海底城市"}
    )
    assert updated.status_code == 200
    assert "海底城市" in path.read_text(encoding="utf-8")
    assert service.client.get(f"/api/runs/{run_id}/memory-banks").status_code == 200


def test_agent_api_auth_and_story_lifecycle(workspace):
    if workspace.name != "novelclaw":
        pytest.skip("NovelClaw token API only")
    client = workspace.client
    assert client.get("/api/v1/health").status_code == 401
    assert (
        client.get("/api/v1/health", headers={"X-API-Key": "wrong"}).status_code == 401
    )
    headers = {"Authorization": "Bearer test-agent-token"}
    assert client.get("/api/v1/health", headers=headers).status_code == 200
    response = client.post(
        "/api/v1/stories",
        headers=headers,
        json={"premise": "海上灯塔的最后一夜", "provider": "deepseek"},
    )
    assert response.status_code == 201
    story_id = response.json()["story_id"]
    assert (
        client.get(f"/api/v1/stories/{story_id}", headers=headers).json()["status"]
        == "queued"
    )
    assert client.post(f"/api/v1/stories/{story_id}/cancel", headers=headers).json()[
        "canceled"
    ]
    assert not client.post(
        f"/api/v1/stories/{story_id}/cancel", headers=headers
    ).json()["canceled"]


def test_env_write_failure_is_reported_without_applying_changes(signed_in, monkeypatch):
    if signed_in.name != "novelclaw":
        pytest.skip("NovelClaw environment editor only")
    previous = signed_in.main.settings.claw_max_steps

    def fail_write(*args, **kwargs):
        raise PermissionError("read-only mount")

    monkeypatch.setattr(signed_in.main, "atomic_write_text", fail_write)
    response = signed_in.client.post(
        "/console/env/save", data={"web_claw_max_steps": "99"}, follow_redirects=False
    )
    assert response.status_code == 303 and "error=" in response.headers["location"]
    assert signed_in.main.settings.claw_max_steps == previous
