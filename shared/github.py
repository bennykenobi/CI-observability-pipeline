"""GitHub App authentication and GitHub Actions API access helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from opentelemetry.trace import SpanKind

from shared.config import Settings
from shared.otel import get_tracer, set_span_attributes


class GitHubApiUnavailableError(RuntimeError):
    """Raised for transient GitHub API failures that may succeed on retry."""

    pass


class GitHubApiPermanentError(RuntimeError):
    """Raised for GitHub API failures that should not be retried blindly."""

    pass


tracer = get_tracer(__name__)


class GitHubAppAuth:
    """Build GitHub App JWTs and installation tokens for API access."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def build_jwt(self) -> str:
        """Build a short-lived GitHub App JWT for installation discovery and auth."""

        if not self.settings.github_app_id or not self.settings.github_app_private_key:
            raise RuntimeError("GitHub App credentials are not configured")
        now = datetime.now(UTC)
        payload = {
            "iat": int(now.timestamp()) - 60,
            "exp": int((now + timedelta(minutes=9)).timestamp()),
            "iss": self.settings.github_app_id,
        }
        return jwt.encode(payload, self.settings.github_app_private_key, algorithm="RS256")

    def app_headers(self) -> dict[str, str]:
        """Return GitHub App authentication headers for app-scoped endpoints."""

        return {
            "Authorization": f"Bearer {self.build_jwt()}",
            "Accept": "application/vnd.github+json",
        }

    async def installation_token(self, client: httpx.AsyncClient, installation_id: int) -> str:
        """Exchange the app JWT for an installation token scoped to one installation."""

        with tracer.start_as_current_span(
            "github.installation_token",
            kind=SpanKind.CLIENT,
        ) as span:
            set_span_attributes(span, github_installation_id=installation_id)
            response = await client.post(
                f"{self.settings.github_api_url}/app/installations/{installation_id}/access_tokens",
                headers=self.app_headers(),
            )
        response.raise_for_status()
        return response.json()["token"]


class GitHubClient:
    """Fetch workflow and job data from GitHub Actions using a GitHub App."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.auth = GitHubAppAuth(settings)
        self.http_client = http_client or httpx.AsyncClient(timeout=30.0)
        self._installation_cache: dict[str, int] = {}
        self._token_cache: dict[int, str] = {}

    async def installation_id_for_repo(self, repository_full_name: str) -> int:
        """Resolve and cache the installation ID for a repository."""

        installation_id = self._installation_cache.get(repository_full_name)
        if installation_id is not None:
            return installation_id
        with tracer.start_as_current_span(
            "github.installation_lookup",
            kind=SpanKind.CLIENT,
        ) as span:
            set_span_attributes(span, repository=repository_full_name)
            response = await self.http_client.get(
                f"{self.settings.github_api_url}/repos/{repository_full_name}/installation",
                headers=self.auth.app_headers(),
            )
        self._raise_for_status(response)
        installation_id = response.json()["id"]
        self._installation_cache[repository_full_name] = installation_id
        return installation_id

    async def _headers(self, installation_id: int) -> dict[str, str]:
        """Return installation-scoped API headers, caching tokens per installation."""

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
        """Fetch the authoritative GitHub workflow-run payload for one run."""

        headers = await self._headers(installation_id)
        with tracer.start_as_current_span(
            "github.get_workflow_run",
            kind=SpanKind.CLIENT,
        ) as span:
            set_span_attributes(
                span,
                repository=repository_full_name,
                github_run_id=run_id,
                github_installation_id=installation_id,
            )
            response = await self.http_client.get(
                f"{self.settings.github_api_url}/repos/{repository_full_name}/actions/runs/{run_id}",
                headers=headers,
            )
        self._raise_for_status(response)
        return response.json()

    async def list_jobs(
        self,
        repository_full_name: str,
        run_id: int,
        installation_id: int,
    ) -> list[dict[str, Any]]:
        """Fetch all paginated job payloads for a workflow run."""

        headers = await self._headers(installation_id)
        page = 1
        pages: list[dict[str, Any]] = []
        while True:
            with tracer.start_as_current_span(
                "github.list_jobs_page",
                kind=SpanKind.CLIENT,
            ) as span:
                set_span_attributes(
                    span,
                    repository=repository_full_name,
                    github_run_id=run_id,
                    github_installation_id=installation_id,
                    page=page,
                )
                response = await self.http_client.get(
                    f"{self.settings.github_api_url}/repos/{repository_full_name}/actions/runs/{run_id}/jobs",
                    headers=headers,
                    params={"per_page": 100, "page": page},
                )
            self._raise_for_status(response)
            payload = response.json()
            pages.append(payload)
            if len(payload.get("jobs", [])) < 100:
                return pages
            page += 1

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Classify GitHub HTTP errors into retryable and permanent failure types."""

        if response.status_code >= 500:
            raise GitHubApiUnavailableError(response.text)
        if response.status_code >= 400:
            raise GitHubApiPermanentError(response.text)
        response.raise_for_status()
