from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

# Force demo mode during automated tests so zero cloud cost is incurred even after user fills .env
os.environ["STUDIO_FORCE_DEMO"] = "1"
# Keep existing end-to-end studio suites auth-free; dedicated auth suite enables AUTH_ENABLED=true
os.environ["AUTH_ENABLED"] = "false"

from app.config import RuntimeSettings  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import EnhancePromptRequest  # noqa: E402
from app.services.director_agent import run_director_turn  # noqa: E402
from app.services.genai_utils import sanitize_error  # noqa: E402
from app.services.google_ai import generate_image, generate_music, review_video_qa  # noqa: E402
from app.services.media_renderer import (  # noqa: E402
    extract_video_frame,
    get_ffmpeg_bin,
    inspect_media,
    prep_video_clip,
    render_timeline_export,
)
from app.services.omni_engine import (  # noqa: E402
    build_natural_language_prompt,
    enhance_omni_prompt,
    generate_omni_video,
    validate_omni_request,
)


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


def _make_sample_video(path: Path, duration: float = 2.0, color: str = "blue", with_audio: bool = True) -> Path:
    ffmpeg = get_ffmpeg_bin()
    assert ffmpeg is not None
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=320x180:d={duration}:r=24",
    ]
    if with_audio:
        cmd.extend(["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"])
    cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
    if with_audio:
        cmd.extend(["-c:a", "aac", "-shortest"])
    cmd.append(str(path))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def _make_sample_image(path: Path, color: str = "red") -> Path:
    ffmpeg = get_ffmpeg_bin()
    assert ffmpeg is not None
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=320x180:d=0.1",
        "-frames:v",
        "1",
        str(path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def _wait_studio_job(client: TestClient, pid: str, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/projects/{pid}/studio/jobs/{job_id}")
        assert r.status_code == 200
        data = r.json()
        if data["status"] in ("completed", "failed"):
            return data
        time.sleep(0.25)
    raise TimeoutError(f"Studio job {job_id} timed out")


def test_omni_constraints_and_prompt_binding():
    validate_omni_request(
        mode="text_to_video",
        duration_seconds=15,
        aspect_ratio="16:9",
        resolution="4k",
        ref_image_count=6,
        ref_video_count=1,
    )

    with pytest.raises(ValueError, match="首帧"):
        validate_omni_request(
            mode="first_last_frame",
            duration_seconds=6,
            aspect_ratio="16:9",
            resolution="720p",
            has_last_frame=True,
        )

    with pytest.raises(ValueError, match="10 秒"):
        validate_omni_request(
            mode="first_last_frame",
            duration_seconds=12,
            aspect_ratio="16:9",
            resolution="720p",
            has_first_frame=True,
            has_last_frame=True,
        )

    with pytest.raises(ValueError, match="10 秒"):
        validate_omni_request(
            mode="extend",
            duration_seconds=11,
            aspect_ratio="16:9",
            resolution="720p",
            has_source_video=True,
        )

    with pytest.raises(ValueError, match="6 张"):
        validate_omni_request(
            mode="reference_to_video",
            duration_seconds=8,
            aspect_ratio="16:9",
            resolution="720p",
            ref_image_count=7,
        )

    with pytest.raises(ValueError, match="最多支持 1 段"):
        validate_omni_request(
            mode="reference_to_video",
            duration_seconds=12,
            aspect_ratio="16:9",
            resolution="720p",
            ref_video_count=2,
        )

    with pytest.raises(ValueError, match="参考视频"):
        validate_omni_request(
            mode="edit",
            duration_seconds=8,
            aspect_ratio="16:9",
            resolution="720p",
            previous_interaction_id="v1_abc",
            ref_video_count=1,
        )

    p1 = build_natural_language_prompt(
        prompt="Camera pushes forward into neon rain",
        mode="first_last_frame",
        has_first_frame=True,
        has_last_frame=True,
        same_loop_frame=False,
    )
    assert "<FIRST_FRAME>" not in p1
    assert "starting frame" in p1 and "final frame" in p1

    p_loop = build_natural_language_prompt(
        prompt="Crystal orb spinning",
        mode="first_last_frame",
        has_first_frame=True,
        has_last_frame=True,
        same_loop_frame=True,
    )
    assert "both the starting frame and the final frame" in p_loop

    p_ext = build_natural_language_prompt(
        prompt="The protagonist turns around",
        mode="extend",
        has_first_frame=False,
        has_last_frame=False,
        has_source_video=True,
    )
    assert p_ext.startswith("Extend this video")

    raw = "Failed at https://generativelanguage.googleapis.com/v1/x?key=AIzaSySecretKeyValue12345678901234567890 body={secret}"
    cleaned = sanitize_error(raw, active_key="AIzaSySecretKeyValue12345678901234567890")
    assert "AIzaSySecretKeyValue" not in cleaned
    assert "[REDACTED" in cleaned


def test_ffmpeg_prep_extract_and_crossfade_export(tmp_path: Path):
    v1 = _make_sample_video(tmp_path / "clip1.mp4", duration=2.0, color="blue", with_audio=True)
    v2 = _make_sample_video(tmp_path / "clip2.mp4", duration=2.0, color="green", with_audio=False)

    meta1 = inspect_media(v1)
    assert meta1["width"] == 320
    assert meta1["height"] == 180
    assert meta1["has_audio"] is True

    prepped = tmp_path / "prepped.mp4"
    prep_meta = prep_video_clip(v1, prepped, start_seconds=0, duration=1, strip_audio=True)
    assert prepped.exists()
    assert prep_meta["has_audio"] is False

    frame = tmp_path / "last.png"
    extract_video_frame(v1, frame, position="last")
    assert frame.exists() and frame.stat().st_size > 100

    out_xfade = tmp_path / "stitched_xfade.mp4"
    final_dur = render_timeline_export(
        clips=[
            {"path": v1, "trim_start": 0.0, "trim_end": None, "duration_sec": 2.0, "has_audio": True},
            {"path": v2, "trim_start": 0.0, "trim_end": None, "duration_sec": 2.0, "has_audio": False},
        ],
        output_path=out_xfade,
        aspect_ratio="16:9",
        resolution="360p",
        crossfade_sec=0.35,
    )
    assert out_xfade.exists()
    assert final_dur > 3.0


def test_studio_tab_and_storyboard_batch_chain_demo(tmp_path: Path):
    img_file = _make_sample_image(tmp_path / "hero.png")
    vid_file = _make_sample_video(tmp_path / "sample.mp4", duration=2.0)

    with TestClient(app) as client:
        proj = client.post("/api/projects", json={"name": "融合功能全链路测试", "aspect_ratio": "16:9"}).json()
        pid = proj["id"]

        try:
            # 1. Direct media uploads + prep + frame extraction
            with open(img_file, "rb") as f:
                r_img = client.post(f"/api/projects/{pid}/assets/upload-media", files={"file": ("hero.png", f, "image/png")})
            assert r_img.status_code == 200
            img_asset = r_img.json()
            assert img_asset["media_type"] == "image"

            with open(vid_file, "rb") as f:
                r_vid = client.post(f"/api/projects/{pid}/assets/upload-media", files={"file": ("sample.mp4", f, "video/mp4")})
            assert r_vid.status_code == 200
            vid_asset = r_vid.json()
            assert vid_asset["media_type"] == "video"

            r_prep = client.post(
                f"/api/projects/{pid}/assets/{vid_asset['id']}/prep",
                json={"start_seconds": 0, "duration": 1, "strip_audio": True, "max_edge": 640},
            )
            assert r_prep.status_code == 200
            assert r_prep.json()["has_audio"] is False

            r_frame = client.post(
                f"/api/projects/{pid}/assets/{vid_asset['id']}/extract-frame",
                json={"position": "last"},
            )
            assert r_frame.status_code == 200
            assert r_frame.json()["media_type"] == "image"

            # 2. Create 2 shots & run batch-generate with chain_last_frame=True
            s1 = client.post(
                f"/api/projects/{pid}/shots",
                json={"title": "镜1", "visual_prompt_zh": "霓虹街头", "video_prompt_en": "Neon alley", "duration_sec": 3},
            ).json()
            s2 = client.post(
                f"/api/projects/{pid}/shots",
                json={"title": "镜2", "visual_prompt_zh": "推门进入", "video_prompt_en": "Enter doorway", "duration_sec": 3},
            ).json()

            batch = client.post(
                f"/api/projects/{pid}/shots/batch-generate",
                json={
                    "engine": "omni_flash",
                    "resolution": "360p",
                    "with_audio": True,
                    "use_end_frame": False,
                    "only_pending": True,
                    "chain_last_frame": True,
                },
            ).json()
            assert batch["submitted_count"] == 1
            assert _wait_task(client, batch["tasks"][0]["id"], timeout=45.0)["status"] == "completed"

            refreshed_shots = client.get(f"/api/projects/{pid}/shots").json()
            assert len(refreshed_shots[0]["takes"]) == 1
            assert len(refreshed_shots[1]["takes"]) == 1
            # Shot 2 automatically received Shot 1's last frame!
            assert refreshed_shots[1]["start_frame_url"] is not None

            # 3. Iterate Take (edit & extend)
            t1_id = refreshed_shots[0]["selected_take_id"]
            t_edit = client.post(
                f"/api/projects/{pid}/shots/{s1['id']}/takes/{t1_id}/iterate",
                json={
                    "action": "edit",
                    "prompt": "Make it golden hour",
                    "duration_sec": 4,
                    "resolution": "360p",
                    "strip_audio": False,
                },
            ).json()
            assert _wait_task(client, t_edit["id"])["status"] == "completed"

            shots_after_edit = client.get(f"/api/projects/{pid}/shots").json()
            newest_take = shots_after_edit[0]["takes"][0]
            assert newest_take["parent_take_id"] == t1_id
            assert newest_take["mode"] == "edit"

            # 4. Studio Tab: enhance prompt + T2V -> Edit -> Extend + lineage + send to shot
            enh = client.post(
                f"/api/projects/{pid}/studio/enhance-prompt",
                json={"prompt": "雨夜赛博小猫", "single_scene": True, "include_timecodes": True, "duration_seconds": 6},
            )
            assert enh.status_code == 200
            assert "Continuous" in enh.json()["enhanced_prompt_en"]

            sj1 = client.post(
                f"/api/projects/{pid}/studio/jobs",
                json={
                    "mode": "text_to_video",
                    "prompt": "Cyber cat in neon rain",
                    "aspect_ratio": "16:9",
                    "duration_seconds": 4,
                    "resolution": "360p",
                    "ref_image_asset_ids": [img_asset["id"]],
                },
            ).json()
            sj1_done = _wait_studio_job(client, pid, sj1["id"])
            assert sj1_done["status"] == "completed", sj1_done.get("error_message")
            assert sj1_done["interaction_id"] is not None

            sj2 = client.post(
                f"/api/projects/{pid}/studio/jobs",
                json={
                    "mode": "extend",
                    "prompt": "Extend seamlessly as cat jumps",
                    "aspect_ratio": "16:9",
                    "duration_seconds": 4,
                    "resolution": "360p",
                    "parent_job_id": sj1["id"],
                },
            ).json()
            sj2_done = _wait_studio_job(client, pid, sj2["id"])
            assert sj2_done["status"] == "completed", sj2_done.get("error_message")

            lineage = client.get(f"/api/projects/{pid}/studio/jobs/{sj2['id']}/lineage").json()
            assert len(lineage) == 2
            assert lineage[0]["id"] == sj1["id"]

            assert client.post(f"/api/projects/{pid}/studio/jobs/{sj2['id']}/extract-frame", json={"position": "last"}).status_code == 200
            assert client.post(f"/api/projects/{pid}/studio/jobs/{sj2['id']}/save-as-asset").status_code == 200
            sent_take = client.post(f"/api/projects/{pid}/studio/jobs/{sj2['id']}/send-to-shot/{s2['id']}")
            assert sent_take.status_code == 200

            # 5. Crossfade timeline export
            exp = client.post(
                f"/api/projects/{pid}/exports",
                json={"resolution": "720p", "crossfade_sec": 0.35, "include_bgm": False, "burn_subtitles": False},
            ).json()
            exp_done = _wait_task(client, exp["id"], timeout=45.0)
            assert exp_done["status"] == "completed", exp_done.get("error")
        finally:
            client.delete(f"/api/projects/{pid}")


def test_mocked_live_interactions_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify Live-mode Interactions API contracts for Omni 1.2 Flash, Gemini 4, Nano Banana 2.1, and Lyria 3.5."""
    sample_mp4 = _make_sample_video(tmp_path / "gen_out.mp4", duration=2.0, color="purple")
    sample_img = _make_sample_image(tmp_path / "ref.png", color="green")
    mp4_bytes = sample_mp4.read_bytes()
    img_bytes = sample_img.read_bytes()

    live_cfg = RuntimeSettings(
        app_mode="live",
        gemini_api_key="AIzaSyTestDummyKey12345678901234567890",
        text_model="gemini-4-hydrogen",
        image_model="gemini-nano-banana-2.1",
        omni_video_model="gemini-omni-1.2-flash",
        music_model="lyria-3.5",
    )

    recorded_calls: list[dict] = []
    upload_count = 0

    class DummyFiles:
        def upload(self, file, config=None):
            nonlocal upload_count
            upload_count += 1
            return SimpleNamespace(
                name=f"files/dummy_{upload_count}",
                uri=f"https://generativelanguage.googleapis.com/files/dummy_{upload_count}",
                mime_type="image/png",
                state=SimpleNamespace(name="ACTIVE"),
            )

        def get(self, name):
            return SimpleNamespace(
                name=name,
                uri=f"https://generativelanguage.googleapis.com/{name}",
                mime_type="video/mp4",
                state=SimpleNamespace(name="ACTIVE"),
            )

        def download(self, file):
            return mp4_bytes

    class DummyInteractions:
        def create(self, **kwargs):
            recorded_calls.append(kwargs)
            model = kwargs.get("model", "")
            if "omni" in model:
                return SimpleNamespace(
                    id="v1_omni_live_001",
                    output_video=SimpleNamespace(
                        uri="https://generativelanguage.googleapis.com/files/outvid123",
                        data=None,
                    ),
                )
            if "nano-banana" in model:
                return SimpleNamespace(
                    id="v1_img_001",
                    output_image=SimpleNamespace(data=img_bytes, mime_type="image/png"),
                )
            if "lyria" in model:
                return SimpleNamespace(
                    id="v1_music_001",
                    output_audio=SimpleNamespace(data=b"ID3DUMMYMP3", mime_type="audio/mpeg"),
                )
            schema_str = str((kwargs.get("response_format") or {}).get("schema") or "")
            if "enhanced_prompt_en" in schema_str:
                return SimpleNamespace(
                    id="v1_enh_001",
                    output_text=json.dumps(
                        {
                            "enhanced_prompt_en": "Continuous, unbroken tracking shot in neon rain.",
                            "summary_zh": "一镜到底霓虹雨夜跟拍",
                            "audio_cue": "雨声与合成器低音",
                            "camera_notes": "35mm 平推",
                            "tips": ["可挂载角色定妆图"],
                        }
                    ),
                )
            if "improved_prompt_en" in schema_str:
                return SimpleNamespace(
                    id="v1_qa_001",
                    output_text=json.dumps(
                        {
                            "score": 9,
                            "summary": "构图流畅",
                            "issues": [],
                            "improved_prompt_en": "Keep steady 35mm tracking",
                        }
                    ),
                )
            return SimpleNamespace(
                id="v1_dir_001",
                output_text=json.dumps(
                    {
                        "reply": "已为你规划分镜。",
                        "proposal": {
                            "title": "测试提案",
                            "mode": "replace_shots",
                            "style_prompt": "Cinematic",
                            "bgm_prompt": "Ambient synth",
                            "assets": [{"name": "林澈", "kind": "character", "description": "侦探"}],
                            "shots": [
                                {
                                    "title": "镜头1",
                                    "shot_type": "远景",
                                    "camera_movement": "缓慢推进",
                                    "visual_prompt_zh": "雨夜长街",
                                    "video_prompt_en": "Continuous, unbroken single shot.",
                                    "duration_sec": 6,
                                    "asset_names": ["林澈"],
                                }
                            ],
                        },
                    }
                ),
            )

    dummy_client = SimpleNamespace(files=DummyFiles(), interactions=DummyInteractions())
    monkeypatch.setattr("app.services.omni_engine.create_genai_client", lambda *a, **kw: dummy_client)
    monkeypatch.setattr("app.services.google_ai.create_genai_client", lambda *a, **kw: dummy_client)
    monkeypatch.setattr("app.services.director_agent.create_genai_client", lambda *a, **kw: dummy_client)

    # 1. Omni 1.2 Flash generation
    out_vid = tmp_path / "omni_out.mp4"
    _, model_used, is_demo, iid = generate_omni_video(
        prompt_en="A cyber detective walking",
        output_path=out_vid,
        mode="first_frame",
        duration_sec=8,
        aspect_ratio="16:9",
        resolution="1080p",
        start_frame_path=sample_img,
        settings=live_cfg,
    )
    assert out_vid.exists() and not is_demo
    assert model_used == "gemini-omni-1.2-flash"
    assert iid == "v1_omni_live_001"
    omni_call = recorded_calls[-1]
    assert omni_call["response_format"] == {
        "type": "video",
        "delivery": "uri",
        "duration": "8s",
        "resolution": "1080p",
        "aspect_ratio": "16:9",
    }

    # 2. Omni stateful follow-up passes previous_interaction_id
    out_ext = tmp_path / "omni_ext.mp4"
    generate_omni_video(
        prompt_en="He opens the neon door",
        output_path=out_ext,
        mode="extend",
        duration_sec=6,
        aspect_ratio="16:9",
        resolution="720p",
        previous_interaction_id=iid,
        settings=live_cfg,
    )
    assert recorded_calls[-1]["previous_interaction_id"] == iid

    # 2b. Verify 40h Gemini Files API URI caching on DB Asset rows
    from app.database import Asset, Project, SessionLocal, init_db

    init_db()
    cache_pid = "test_cache_proj"
    cache_aid = "test_cache_asset"
    session = SessionLocal()
    try:
        session.add(Project(id=cache_pid, name="Cache Test Project"))
        session.add(
            Asset(
                id=cache_aid,
                project_id=cache_pid,
                name="cached_ref.png",
                kind="character",
                file_path=str(sample_img),
                media_type="image",
                mime_type="image/png",
            )
        )
        session.commit()
    finally:
        session.close()

    try:
        before_uploads = upload_count
        generate_omni_video(
            prompt_en="First cached call",
            output_path=tmp_path / "omni_cache_1.mp4",
            mode="first_frame",
            duration_sec=4,
            aspect_ratio="16:9",
            resolution="360p",
            start_frame_path=sample_img,
            first_frame_asset_id=cache_aid,
            settings=live_cfg,
        )
        assert upload_count == before_uploads + 1

        generate_omni_video(
            prompt_en="Second cached call reuses 40h URI",
            output_path=tmp_path / "omni_cache_2.mp4",
            mode="first_frame",
            duration_sec=4,
            aspect_ratio="16:9",
            resolution="360p",
            start_frame_path=sample_img,
            first_frame_asset_id=cache_aid,
            settings=live_cfg,
        )
        assert upload_count == before_uploads + 1
    finally:
        session = SessionLocal()
        try:
            proj_row = session.get(Project, cache_pid)
            if proj_row:
                session.delete(proj_row)
                session.commit()
        finally:
            session.close()

    # 3. Gemini 4 prompt enhance
    enh_out, _, _ = enhance_omni_prompt(
        EnhancePromptRequest(prompt="霓虹街头", single_scene=True),
        settings=live_cfg,
    )
    assert "Continuous" in enh_out.enhanced_prompt_en

    # 4. Nano Banana 2.1 image gen via Interactions API
    out_png = tmp_path / "nb21.png"
    _, img_model, _ = generate_image("Cyber detective", out_png, aspect_ratio="16:9", settings=live_cfg)
    assert out_png.exists() and img_model == "gemini-nano-banana-2.1"

    # 5. Lyria 3.5 music gen
    out_mp3 = tmp_path / "bgm.mp3"
    _, mus_model, _ = generate_music("Ambient synthwave", out_mp3, settings=live_cfg)
    assert out_mp3.exists() and mus_model == "lyria-3.5"

    # 6. Gemini 4 Director Turn & QA Review
    dir_res, dir_model, _ = run_director_turn({"name": "Test", "assets": [], "shots": []}, [], "拍一条短片", settings=live_cfg)
    assert dir_model == "gemini-4-hydrogen" and dir_res["proposal"] is not None

    qa_res, qa_model, _ = review_video_qa(out_vid, "镜头1", "雨夜", "Neon alley", settings=live_cfg)
    assert qa_model == "gemini-4-hydrogen" and qa_res["score"] == 9


def test_auth_system_and_media_protection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify single-admin setup, HttpOnly session gating, rate limit, password rotation, and /media isolation."""
    from app.database import SessionLocal, User, UserSession, init_db
    from app.services.auth import COOKIE_NAME, reset_rate_limiter

    monkeypatch.setenv("AUTH_ENABLED", "true")
    reset_rate_limiter()
    init_db()

    # Ensure clean user state before test
    db = SessionLocal()
    try:
        db.query(UserSession).delete()
        db.query(User).delete()
        db.commit()
    finally:
        db.close()

    img_file = _make_sample_image(tmp_path / "auth_asset.png")
    created_pid: str | None = None

    try:
        with TestClient(app) as client:
            # 1. Public health & initial auth status
            h = client.get("/api/health")
            assert h.status_code == 200
            assert h.json()["auth_enabled"] is True

            st = client.get("/api/auth/status")
            assert st.status_code == 200
            assert st.json()["auth_enabled"] is True
            assert st.json()["initialized"] is False
            assert st.json()["authenticated"] is False

            # 2. All protected endpoints & media/docs paths must reject unauthenticated callers with 401
            for protected_path in (
                "/api/projects",
                "/api/settings",
                "/api/tasks/events",
                "/media/projects/nonexistent/file.png",
                "/media/runtime.env",
                "/media/studio.db",
                "/docs",
            ):
                resp = client.get(protected_path)
                assert resp.status_code == 401, f"Expected 401 for {protected_path}, got {resp.status_code}"

            # 3. First-time admin setup succeeds and sets HttpOnly cookie; second setup is 403
            setup_res = client.post(
                "/api/auth/setup",
                json={"username": "OwnerAdmin", "password": "StrongPass123!"},
            )
            assert setup_res.status_code == 200, setup_res.text
            assert setup_res.json()["authenticated"] is True
            assert setup_res.json()["username"] == "owneradmin"
            assert COOKIE_NAME in setup_res.cookies
            first_cookie = setup_res.cookies[COOKIE_NAME]

            dup_res = client.post(
                "/api/auth/setup",
                json={"username": "attacker", "password": "Password123!"},
            )
            assert dup_res.status_code == 403

            # 4. Authenticated API & project media work; /media/runtime.env & /media/studio.db are 404
            assert client.get("/api/projects").status_code == 200
            assert client.get("/api/settings").status_code == 200

            proj = client.post("/api/projects", json={"name": "鉴权媒体测试", "aspect_ratio": "16:9"}).json()
            created_pid = proj["id"]
            with open(img_file, "rb") as f:
                up = client.post(
                    f"/api/projects/{created_pid}/assets/upload-media",
                    files={"file": ("auth_asset.png", f, "image/png")},
                )
            assert up.status_code == 200
            media_url = up.json()["file_url"]
            assert media_url.startswith("/media/projects/")
            assert client.get(media_url).status_code == 200

            assert client.get("/media/runtime.env").status_code == 404
            assert client.get("/media/studio.db").status_code == 404

            # Unauthenticated second client cannot read uploaded project media
            with TestClient(app) as anon_client:
                assert anon_client.get(media_url).status_code == 401

            # 5. Password change validates current password and revokes older session tokens
            bad_chg = client.post(
                "/api/auth/change-password",
                json={"current_password": "WrongPassword", "new_password": "NewStrongPass456!"},
            )
            assert bad_chg.status_code == 400

            ok_chg = client.post(
                "/api/auth/change-password",
                json={"current_password": "StrongPass123!", "new_password": "NewStrongPass456!"},
            )
            assert ok_chg.status_code == 200
            assert client.get("/api/projects").status_code == 200

            # Old session token from before password rotation must be rejected
            with TestClient(app) as old_client:
                old_client.cookies.set(COOKIE_NAME, first_cookie)
                assert old_client.get("/api/projects").status_code == 401

            # 6. Logout revokes active session
            out = client.post("/api/auth/logout")
            assert out.status_code == 200
            assert client.get("/api/projects").status_code == 401

            # 7. Rate limit on failed logins, then clean login with rotated password
            for _ in range(10):
                bad_login = client.post(
                    "/api/auth/login",
                    json={"username": "owneradmin", "password": "BadPassword"},
                )
                assert bad_login.status_code == 401

            limited = client.post(
                "/api/auth/login",
                json={"username": "owneradmin", "password": "BadPassword"},
            )
            assert limited.status_code == 429

            reset_rate_limiter()
            ok_login = client.post(
                "/api/auth/login",
                json={"username": "OwnerAdmin", "password": "NewStrongPass456!", "remember": True},
            )
            assert ok_login.status_code == 200
            assert ok_login.json()["authenticated"] is True
            assert client.get("/api/projects").status_code == 200
    finally:
        if created_pid:
            from app.services.storage import delete_project_files

            delete_project_files(created_pid)
        db = SessionLocal()
        try:
            if created_pid:
                from app.database import Project

                prow = db.get(Project, created_pid)
                if prow:
                    db.delete(prow)
            db.query(UserSession).delete()
            db.query(User).delete()
            db.commit()
        finally:
            db.close()
        reset_rate_limiter()

