from sqlalchemy import BigInteger

from shared.db.models import JobRun, RawIngestionEvent, Repository, WebhookDelivery, WorkflowRun


def test_large_github_identifier_columns_use_bigint():
    assert isinstance(Repository.__table__.c.github_repository_id.type, BigInteger)
    assert isinstance(WorkflowRun.__table__.c.github_run_id.type, BigInteger)
    assert isinstance(WorkflowRun.__table__.c.workflow_id.type, BigInteger)
    assert isinstance(JobRun.__table__.c.github_job_id.type, BigInteger)
    assert isinstance(RawIngestionEvent.__table__.c.repository_id.type, BigInteger)
    assert isinstance(RawIngestionEvent.__table__.c.run_id.type, BigInteger)
    assert isinstance(WebhookDelivery.__table__.c.repository_id.type, BigInteger)
    assert isinstance(WebhookDelivery.__table__.c.run_id.type, BigInteger)
