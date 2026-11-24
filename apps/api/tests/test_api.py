from __future__ import annotations

import os
import time
from fastapi.testclient import TestClient

# Force demo mode during automated tests so zero cloud cost is incurred even after user fills .env
os.environ["STUDIO_FORCE_DEMO"] = "1"

from app.main import app  # noqa: E402


def _wait_task(client: TestClient, task_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/tasks/{task_id}")
        assert r.status_code == 200
        data = r.json()
        if data["status"] in ("completed", "failed"):
            return data
        time.sleep(0.25)
    raise TimeoutError(f"Task {task_id} timed out")


def test_full_demo_studio_workflow():
    with TestClient(app) as client:
        # 1. Health, SPA serving & Settings
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        spa = client.get("/")
        assert spa.status_code == 200
        assert "<!doctype html>" in spa.text.lower()
        settings = client.get("/api/settings").json()
        assert settings["ffmpeg_available"] is True

        # 2. Create project
        proj = client.post(
            "/api/projects",
            json={
                "name": "测试赛博短片",
                "description": "自动化端到端测试项目",
                "aspect_ratio": "16:9",
            },
        ).json()
        pid = proj["id"]

        try:
            # 3. Chat with Director Agent & apply proposal
            msg = client.post(
                f"/api/projects/{pid}/chat",
                json={"content": "做一个雨夜赛博侦探发现神秘光球的短片"},
            ).json()
            assert msg["role"] == "assistant"
            assert msg["proposal"] is not None

            applied = client.post(f"/api/projects/{pid}/chat/{msg['id']}/apply").json()
            assert applied["ok"] is True
            assert applied["applied_shots"] >= 2

            assets = client.get(f"/api/projects/{pid}/assets").json()
            shots = client.get(f"/api/projects/{pid}/shots").json()
            assert len(assets) >= 1
            assert len(shots) >= 2

            # 4. Generate asset image & 3-view turnaround
            t_img = client.post(f"/api/projects/{pid}/assets/{assets[0]['id']}/generate", json={}).json()
            assert _wait_task(client, t_img["id"])["status"] == "completed"

            t_turn = client.post(f"/api/projects/{pid}/assets/{assets[0]['id']}/turnaround").json()
            assert _wait_task(client, t_turn["id"])["status"] == "completed"

            # 5. Generate keyframes & demo videos for first 2 shots
            for s in shots[:2]:
                t_kf = client.post(
                    f"/api/projects/{pid}/shots/{s['id']}/keyframe/generate",
                    json={"which": "start"},
                ).json()
                assert _wait_task(client, t_kf["id"])["status"] == "completed"

                t_vid = client.post(
                    f"/api/projects/{pid}/shots/{s['id']}/video/generate",
                    json={"engine": "veo_lite", "duration_sec": 2, "with_audio": True},
                ).json()
                res_vid = _wait_task(client, t_vid["id"])
                assert res_vid["status"] == "completed", res_vid.get("error")

            # 6. Continuity: copy shot 1 end frame -> shot 2 start frame
            cont = client.post(f"/api/projects/{pid}/shots/{shots[1]['id']}/keyframe/from-prev-end")
            assert cont.status_code == 200
            assert cont.json()["start_frame_url"] is not None

            # 7. Run QA review on shot 1 selected take
            updated_shots = client.get(f"/api/projects/{pid}/shots").json()
            take_id = updated_shots[0]["selected_take_id"]
            assert take_id is not None
            t_qa = client.post(f"/api/projects/{pid}/shots/{shots[0]['id']}/takes/{take_id}/qa").json()
            assert _wait_task(client, t_qa["id"])["status"] == "completed"

            # 8. Generate BGM & auto SRT subtitles
            t_bgm = client.post(
                f"/api/projects/{pid}/audio/bgm/generate",
                json={"prompt": "Cyberpunk ambient synth", "mode": "clip"},
            ).json()
            assert _wait_task(client, t_bgm["id"])["status"] == "completed"

            srt_res = client.post(f"/api/projects/{pid}/audio/subtitles/auto-from-script").json()
            assert "-->" in srt_res["subtitle_srt"]

            # 9. Real FFmpeg multi-clip export with BGM + burned SRT subtitles!
            t_exp = client.post(
                f"/api/projects/{pid}/exports",
                json={"resolution": "720p", "include_bgm": True, "burn_subtitles": True},
            ).json()
            res_exp = _wait_task(client, t_exp["id"], timeout=45.0)
            assert res_exp["status"] == "completed", res_exp.get("error")
            assert res_exp["result"]["duration_sec"] >= 3.5

            # 10. Verify budget endpoint
            budget = client.get("/api/settings/budget").json()
            assert budget["monthly_budget_usd"] > 0
            assert budget["demo_simulated_usd"] > 0
        finally:
            client.delete(f"/api/projects/{pid}")


def test_novel_import_and_episode_workflow():
    with TestClient(app) as client:
        proj = client.post(
            "/api/projects",
            json={"name": "长篇小说测试", "aspect_ratio": "9:16"},
        ).json()
        pid = proj["id"]

        novel_content = (
            "第一章 暴雨夜归\n"
            + ("林澈推开侦探事务所生锈的铁门，桌上全息晶体缓缓旋转。窗外电闪雷鸣。\n" * 8)
            + "\n第二章 星港线索\n"
            + ("苏晚展开泛黄的星图，红蓝警灯扫过百叶窗，两人沿着消防梯冲上天台。\n" * 8)
        )

        try:
            # 1. Import novel via GBK-encoded TXT file upload (common Chinese novel format)
            resp = client.post(
                f"/api/projects/{pid}/novel/import-file",
                files={"file": ("星港雨夜.txt", novel_content.encode("gb18030"), "text/plain")},
                data={"split_mode": "auto_chapter", "chars_per_episode": "1500", "replace_existing": "true"},
            )
            assert resp.status_code == 200, resp.text
            eps = resp.json()
            assert len(eps) == 2
            assert "第一章" in eps[0]["title"]
            assert "第二章" in eps[1]["title"]

            # 2. Extract Global Book Bible (Characters/Scenes/Props)
            t_bible = client.post(f"/api/projects/{pid}/novel/extract-bible", json={"max_episodes": 10}).json()
            res_bible = _wait_task(client, t_bible["id"])
            assert res_bible["status"] == "completed", res_bible.get("error")

            assets = client.get(f"/api/projects/{pid}/assets").json()
            assert len(assets) >= 2

            # 3. Break down Episode 1 into 4 structured shots
            ep1_id = eps[0]["id"]
            t_bd = client.post(
                f"/api/projects/{pid}/novel/episodes/{ep1_id}/breakdown",
                json={"target_shots": 4, "replace_existing": True},
            ).json()
            res_bd = _wait_task(client, t_bd["id"])
            assert res_bd["status"] == "completed", res_bd.get("error")
            assert res_bd["result"]["created_shots"] == 4

            ep1_shots = client.get(f"/api/projects/{pid}/shots?episode_id={ep1_id}").json()
            assert len(ep1_shots) == 4
            assert all(s["episode_id"] == ep1_id for s in ep1_shots)
            assert len(ep1_shots[0]["asset_ids"]) >= 1

            # 4. Generate 1 take in Episode 1 and verify episode-scoped export
            t_vid = client.post(
                f"/api/projects/{pid}/shots/{ep1_shots[0]['id']}/video/generate",
                json={"engine": "veo_lite", "duration_sec": 2, "with_audio": True},
            ).json()
            assert _wait_task(client, t_vid["id"])["status"] == "completed"

            t_exp = client.post(
                f"/api/projects/{pid}/exports",
                json={"episode_id": ep1_id, "resolution": "720p", "include_bgm": False, "burn_subtitles": False},
            ).json()
            res_exp = _wait_task(client, t_exp["id"])
            assert res_exp["status"] == "completed", res_exp.get("error")
        finally:
            client.delete(f"/api/projects/{pid}")
