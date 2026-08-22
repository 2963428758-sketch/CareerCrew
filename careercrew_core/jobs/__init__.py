"""岗位库：查询路径读库、采集器去重入库（search_jobs 与爬取解耦）。"""
from careercrew_core.jobs.store import (
    FakeJobsStore,
    JobsStore,
    PostgresJobsStore,
    create_jobs_store,
    job_fingerprint,
)

__all__ = [
    "FakeJobsStore",
    "JobsStore",
    "PostgresJobsStore",
    "create_jobs_store",
    "job_fingerprint",
]
