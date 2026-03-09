from datetime import UTC, datetime

import pytest

from shared.github import GitHubApiUnavailableError
from shared.ingestion import IngestionService, build_ingestion_bundle
from shared.schemas import WebhookIngestionMessage


def test_build_ingestion_bundle_captures_reusable_workflow_and_steps():
    message = WebhookIngestionMessage(
        action="completed",
        delivery_id="delivery-1",
        repository_id=1,
        repository_full_name="org/caller",
        run_id=101,
        run_attempt=1,
        installation_id=999,
        sent_at=datetime.now(UTC),
    )
    workflow_payload = {
        "workflow_id": 55,
        "name": "caller",
        "path": ".github/workflows/caller.yml",
        "head_branch": "main",
        "head_sha": "abc123",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "run_started_at": "2026-03-09T00:00:00Z",
        "updated_at": "2026-03-09T00:01:00Z",
        "actor": {"login": "octocat"},
        "referenced_workflows": [
            {"path": "org/reusable/.github/workflows/reusable.yml", "ref": "main"}
        ],
    }
    jobs_pages = [
        {
            "jobs": [
                {
                    "id": 500,
                    "name": "build",
                    "runner_name": "ubuntu-latest",
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "2026-03-09T00:00:10Z",
                    "completed_at": "2026-03-09T00:00:50Z",
                    "steps": [
                        {
                            "number": 1,
                            "name": "checkout",
                            "status": "completed",
                            "conclusion": "success",
                            "started_at": "2026-03-09T00:00:11Z",
                            "completed_at": "2026-03-09T00:00:20Z",
                        }
                    ],
                }
            ]
        }
    ]

    bundle = build_ingestion_bundle(message, workflow_payload, jobs_pages)

    assert bundle.workflow_run.referenced_workflow_repo == "org/reusable"
    assert bundle.workflow_run.referenced_workflow_path == ".github/workflows/reusable.yml"
    assert bundle.workflow_run.duration_ms == 60000
    assert bundle.jobs[0].steps[0].duration_ms == 9000
    assert [event.source_type for event in bundle.raw_events] == ["workflow_run_api", "jobs_api"]


class RetryGitHubClient:
    def __init__(self, failures_before_success=0):
        self.failures_before_success = failures_before_success
        self.installation_lookup_calls = 0
        self.workflow_calls = 0
        self.jobs_calls = 0

    async def installation_id_for_repo(self, repository_full_name):
        self.installation_lookup_calls += 1
        return 99

    async def get_workflow_run(self, repository_full_name, run_id, installation_id):
        self.workflow_calls += 1
        if self.workflow_calls <= self.failures_before_success:
            raise GitHubApiUnavailableError("temporary failure")
        return {
            "workflow_id": 55,
            "name": "caller",
            "path": ".github/workflows/caller.yml",
            "head_branch": "main",
            "head_sha": "abc123",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "run_started_at": "2026-03-09T00:00:00Z",
            "updated_at": "2026-03-09T00:01:00Z",
            "actor": {"login": "octocat"},
            "referenced_workflows": [],
        }

    async def list_jobs(self, repository_full_name, run_id, installation_id):
        self.jobs_calls += 1
        return [{"jobs": []}]


class RecordingBundleRepository:
    def __init__(self):
        self.bundles = []

    async def persist_bundle(self, bundle):
        self.bundles.append(bundle)


@pytest.mark.asyncio
async def test_ingestion_service_retries_then_persists(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr("shared.ingestion.asyncio.sleep", no_sleep)
    client = RetryGitHubClient(failures_before_success=2)
    repository = RecordingBundleRepository()
    service = IngestionService(
        settings=type(
            "SettingsStub",
            (),
            {
                "initial_fetch_delay_seconds": 0,
                "github_fetch_retry_attempts": 3,
                "github_fetch_retry_interval_seconds": 0,
            },
        )(),
        github_client=client,
        repository=repository,
    )
    message = WebhookIngestionMessage(
        action="completed",
        delivery_id="delivery-1",
        repository_id=1,
        repository_full_name="org/repo",
        run_id=11,
        run_attempt=1,
        sent_at=datetime.now(UTC),
    )

    bundle = await service.ingest(message)

    assert client.installation_lookup_calls == 1
    assert client.workflow_calls == 3
    assert client.jobs_calls == 1
    assert repository.bundles[0] == bundle


@pytest.mark.asyncio
async def test_ingestion_service_raises_after_retry_exhaustion(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr("shared.ingestion.asyncio.sleep", no_sleep)
    client = RetryGitHubClient(failures_before_success=5)
    repository = RecordingBundleRepository()
    service = IngestionService(
        settings=type(
            "SettingsStub",
            (),
            {
                "initial_fetch_delay_seconds": 0,
                "github_fetch_retry_attempts": 2,
                "github_fetch_retry_interval_seconds": 0,
            },
        )(),
        github_client=client,
        repository=repository,
    )
    message = WebhookIngestionMessage(
        action="completed",
        delivery_id="delivery-1",
        repository_id=1,
        repository_full_name="org/repo",
        run_id=11,
        run_attempt=1,
        sent_at=datetime.now(UTC),
    )

    with pytest.raises(RuntimeError, match="ingestion_failed_after_retries"):
        await service.ingest(message)
