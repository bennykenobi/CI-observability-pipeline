from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from shared.config import Settings


class GitHubApiUnavailableError(RuntimeError):
    pass


class GitHubAppAuth:
    def __init__(self, settings: Settings):
        self.settings = settings

    def build_jwt(self) -> str:
        if not self.settings.github_app_id or not self.settings.github_app_private_key:
            raise RuntimeError("GitHub App credentials are not configured")
        now = datetime.now(UTC)
        payload = {
            "iat": int(now.timestamp()) - 60,
            "exp": int((now + timedelta(minutes=9)).timestamp()),
            "iss": self.settings.github_app_id,
        }
        return jwt.encode(payload, self.settings.github_app_private_key, algorithm="RS256")

    async def installation_token(self, client: httpx.AsyncClient, installation_id: int) -> str:
        response = await client.post(
            f"{self.settings.github_api_url}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {self.build_jwt()}",
                "Accept": "application/vnd.github+json",
            },
        )
        response.raise_for_status()
        return response.json()["token"]


class GitHubClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.auth = GitHubAppAuth(settings)
        self.http_client = http_client or httpx.AsyncClient(timeout=30.0)
        self._installation_cache: dict[str, int] = {}
        self._token_cache: dict[int, str] = {}

    async def installation_id_for_repo(self, repository_full_name: str) -> int:
        installation_id = self._installation_cache.get(repository_full_name)
        if installation_id is not None:
            return installation_id
        response = await self.http_client.get(
            f"{self.settings.github_api_url}/repos/{repository_full_name}/installation",
            headers={
                "Authorization": f"Bearer {self.auth.build_jwt()}",
                "Accept": "application/vnd.github+json",
            },
        )
        if response.status_code >= 500:
            raise GitHubApiUnavailableError(response.text)
        response.raise_for_status()
        installation_id = response.json()["id"]
        self._installation_cache[repository_full_name] = installation_id
        return installation_id

    async def _headers(self, installation_id: int) -> dict[str, str]:
        token = self._token_cache.get(installation_id)
        if token is None:
            token = await self.auth.installation_token(self.http_client, installation_id)
            self._token_cache[installation_id] = token
        return {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }

    async def get_workflow_run(
        self,
        repository_full_name: str,
        run_id: int,
        installation_id: int,
    ) -> dict[str, Any]:
        headers = await self._headers(installation_id)
        response = await self.http_client.get(
            f"{self.settings.github_api_url}/repos/{repository_full_name}/actions/runs/{run_id}",
            headers=headers,
        )
        if response.status_code >= 500:
            raise GitHubApiUnavailableError(response.text)
        response.raise_for_status()
        return response.json()

    async def list_jobs(
        self,
        repository_full_name: str,
        run_id: int,
        installation_id: int,
    ) -> list[dict[str, Any]]:
        headers = await self._headers(installation_id)
        page = 1
        pages: list[dict[str, Any]] = []
        while True:
            response = await self.http_client.get(
                f"{self.settings.github_api_url}/repos/{repository_full_name}/actions/runs/{run_id}/jobs",
                headers=headers,
                params={"per_page": 100, "page": page},
            )
            if response.status_code >= 500:
                raise GitHubApiUnavailableError(response.text)
            response.raise_for_status()
            payload = response.json()
            pages.append(payload)
            if len(payload.get("jobs", [])) < 100:
                return pages
            page += 1
