from __future__ import annotations

import io
import zipfile


def test_resume_workspace_api(client, fake_runtime):
    created = client.post(
        "/api/workspace/resumes/masters",
        json={"title": "通用母版", "content": "Java 工程师\n负责 API"},
    )
    assert created.status_code == 201, created.text
    master = created.json()
    base = client.get(f"/api/workspace/resumes/masters/{master['id']}/versions").json()[0]
    derived = client.post(
        f"/api/workspace/resumes/masters/{master['id']}/versions",
        json={"label": "AI 岗位版", "content": "Java 工程师\n负责 RAG API", "parent_version_id": base["id"], "kind": "derived"},
    )
    assert derived.status_code == 201, derived.text
    diff = client.get(
        "/api/workspace/resumes/diff",
        params={"left_version_id": base["id"], "right_version_id": derived.json()["id"]},
    )
    assert diff.status_code == 200 and diff.json()["changed"] is True

    material = client.post(
        "/api/workspace/resumes/materials",
        json={"title": "项目素材", "context": "检索", "role": "负责人", "actions": "重排", "results": "提升", "tags": ["RAG"]},
    )
    assert material.status_code == 201
    annotation = client.post(
        f"/api/workspace/resumes/versions/{derived.json()['id']}/annotations",
        json={"start_offset": 0, "end_offset": 3, "note": "核对"},
    )
    assert annotation.status_code == 201

    job = client.post(
        "/api/workspace/resumes/exports",
        json={"version_ids": [base["id"], derived.json()["id"]], "formats": ["pdf", "docx"]},
    )
    assert job.status_code == 202, job.text
    job_id = job.json()["id"]
    status = client.get(f"/api/workspace/resumes/exports/{job_id}")
    assert status.status_code == 200 and status.json()["status"] == "done"
    download = client.get(f"/api/workspace/resumes/exports/{job_id}/download")
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert len(archive.namelist()) == 4


def test_resume_workspace_api_hides_foreign_master(tenant_api):
    client, runtime, headers, ids = tenant_api
    # create with the authenticated Alice token, then query with Bob
    created = client.post(
        "/api/workspace/resumes/masters", headers=headers["alice"],
        json={"title": "Alice", "content": "private"},
    )
    assert created.status_code == 201
    master_id = created.json()["id"]
    assert client.get(f"/api/workspace/resumes/masters/{master_id}", headers=headers["bob"]).status_code == 404
