from __future__ import annotations

import httpx
import pytest

from shared.config import Settings
from shared.github import GitHubApiPermanentError, GitHubApiUnavailableError, GitHubClient


def make_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_github_client_reuses_installation_token_for_multiple_calls():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if request.url.path == "/app/installations/99/access_tokens":
            return httpx.Response(200, json={"token": "abc"})
        if request.url.path == "/repos/org/repo/actions/runs/11":
            assert request.headers["Authorization"] == "token abc"
            return httpx.Response(200, json={"id": 11})
        if request.url.path == "/repos/org/repo/actions/runs/11/jobs":
            return httpx.Response(200, json={"jobs": []})
        raise AssertionError(f"unexpected request: {request.url}")

    settings = Settings(
        github_api_url="https://api.github.test",
        github_app_id="123",
        github_app_private_key="dummy",
    )
    client = GitHubClient(
        settings=settings,
        http_client=httpx.AsyncClient(transport=make_transport(handler)),
    )
    client.auth.installation_token = lambda http_client, installation_id: _resolved_token("abc")

    await client.get_workflow_run("org/repo", 11, 99)
    await client.list_jobs("org/repo", 11, 99)

    token_calls = [call for call in calls if call[1].endswith("/access_tokens")]
    assert token_calls == []


async def _resolved_token(token: str) -> str:
    return token


@pytest.mark.asyncio
async def test_github_client_discovers_and_caches_installation_id():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if request.url.path == "/repos/org/repo/installation":
            return httpx.Response(200, json={"id": 99})
        raise AssertionError(f"unexpected request: {request.url}")

    settings = Settings(
        github_api_url="https://api.github.test",
        github_app_id="123",
        github_app_private_key="dummy",
    )
    client = GitHubClient(
        settings=settings,
        http_client=httpx.AsyncClient(transport=make_transport(handler)),
    )
    client.auth.build_jwt = lambda: "jwt"

    first = await client.installation_id_for_repo("org/repo")
    second = await client.installation_id_for_repo("org/repo")

    assert first == 99
    assert second == 99
    assert calls == [("GET", "https://api.github.test/repos/org/repo/installation")]


@pytest.mark.asyncio
async def test_github_client_paginates_jobs():
    pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        page = int(params["page"])
        pages.append(page)
        if page == 1:
            return httpx.Response(200, json={"jobs": [{"id": i} for i in range(100)]})
        return httpx.Response(200, json={"jobs": [{"id": 101}]})

    settings = Settings(
        github_api_url="https://api.github.test",
        github_app_id="123",
        github_app_private_key="dummy",
    )
    client = GitHubClient(
        settings=settings,
        http_client=httpx.AsyncClient(transport=make_transport(handler)),
    )
    client.auth.installation_token = lambda http_client, installation_id: _resolved_token("abc")

    payloads = await client.list_jobs("org/repo", 11, 99)

    assert pages == [1, 2]
    assert len(payloads) == 2


@pytest.mark.asyncio
async def test_github_client_raises_on_server_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    settings = Settings(
        github_api_url="https://api.github.test",
        github_app_id="123",
        github_app_private_key="dummy",
    )
    client = GitHubClient(
        settings=settings,
        http_client=httpx.AsyncClient(transport=make_transport(handler)),
    )
    client.auth.installation_token = lambda http_client, installation_id: _resolved_token("abc")

    with pytest.raises(GitHubApiUnavailableError):
        await client.get_workflow_run("org/repo", 11, 99)


@pytest.mark.asyncio
async def test_github_client_raises_permanent_error_on_client_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    settings = Settings(
        github_api_url="https://api.github.test",
        github_app_id="123",
        github_app_private_key="dummy",
    )
    client = GitHubClient(
        settings=settings,
        http_client=httpx.AsyncClient(transport=make_transport(handler)),
    )
    client.auth.installation_token = lambda http_client, installation_id: _resolved_token("abc")

    with pytest.raises(GitHubApiPermanentError):
        await client.get_workflow_run("org/repo", 11, 99)
