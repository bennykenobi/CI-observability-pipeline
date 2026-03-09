from shared.ingestion import build_ingestion_bundle
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
