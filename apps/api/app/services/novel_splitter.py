from __future__ import annotations

import html
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import RuntimeSettings, load_settings
from app.services.genai_utils import create_genai_client


class BookBibleAssetItem(BaseModel):
    name: str
    kind: Literal["character", "scene", "prop"] = "character"
    description: str


class EpisodeSummaryItem(BaseModel):
    order_index: int
    summary: str


class BookBibleOutput(BaseModel):
    style_prompt: str
    bgm_prompt: str
    assets: list[BookBibleAssetItem] = Field(default_factory=list)
    episode_summaries: list[EpisodeSummaryItem] = Field(default_factory=list)


class EpisodeShotItem(BaseModel):
    title: str
    shot_type: str = "中景"
    camera_movement: str = "缓慢推进"
    visual_prompt_zh: str
    video_prompt_en: str
    dialogue: str = ""
    sfx_prompt: str = ""
    duration_sec: int = Field(default=6, ge=3, le=15)
    asset_names: list[str] = Field(default_factory=list)


class EpisodeBreakdownOutput(BaseModel):
    summary: str
    shots: list[EpisodeShotItem] = Field(default_factory=list)

# Matches common Chinese & English novel chapter headings at the start of a line
CHAPTER_HEADING_RE = re.compile(
    r"^(?:"
    r"(?:第[零一二三四五六七八九十百千万两\d]+[章节回卷集幕部篇](?:[\s：:·\-—]+[^\n]{0,60})?)"
    r"|(?:(?:序章|序言|楔子|引子|前言|尾声|终章|番外)(?:[\s：:·\-—]+[^\n]{0,50})?)"
    r"|(?:Chapter\s+\d+(?:[\s:\-—]+[^\n]{0,60})?)"
    r"|(?:Episode\s+\d+(?:[\s:\-—]+[^\n]{0,60})?)"
    r"|(?:#{1,3}\s+[^\n]{1,60})"
    r")\s*$",
    re.IGNORECASE,
)


def decode_text_bytes(raw: bytes) -> str:
    """Decode Chinese/English novel bytes cleanly across UTF-8, GB18030, GBK, UTF-16."""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_novel_text_from_file(filename: str, raw: bytes) -> str:
    """Extract clean plain text from .txt, .md, .docx, or .epub without heavy external dependencies."""
    lower = (filename or "novel.txt").lower()
    if lower.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs: list[str] = []
        for p in root.findall(".//w:p", ns):
            texts = [t.text for t in p.findall(".//w:t", ns) if t.text]
            line = "".join(texts).strip()
            if line:
                paragraphs.append(line)
        return "\n\n".join(paragraphs)

    if lower.endswith(".epub"):
        chunks: list[str] = []
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            html_names = sorted(
                n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))
            )
            for name in html_names:
                content = decode_text_bytes(zf.read(name))
                # Strip scripts/styles then tags
                content = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", content, flags=re.I | re.S)
                content = re.sub(r"</(p|div|h[1-6]|br|li)>", "\n", content, flags=re.I)
                content = re.sub(r"<[^>]+>", "", content)
                content = html.unescape(content)
                lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
                if lines:
                    chunks.append("\n".join(lines))
        return "\n\n".join(chunks)

    return decode_text_bytes(raw)


def _split_long_text_by_paragraphs(title: str, body: str, max_chars: int) -> list[dict[str, str]]:
    """Split a long block cleanly along paragraph boundaries."""
    body = body.strip()
    if len(body) <= int(max_chars * 1.35):
        return [{"title": title, "source_text": body}]

    paras = [p.strip() for p in re.split(r"\n+", body) if p.strip()]
    parts: list[str] = []
    buf: list[str] = []
    cur_len = 0

    for para in paras:
        if cur_len + len(para) > max_chars and buf:
            parts.append("\n\n".join(buf))
            buf = [para]
            cur_len = len(para)
        else:
            buf.append(para)
            cur_len += len(para)
    if buf:
        parts.append("\n\n".join(buf))

    if len(parts) == 1:
        return [{"title": title, "source_text": parts[0]}]
    return [
        {"title": f"{title}（上/第{i+1}段）" if len(parts) > 2 else f"{title}（{'上' if i == 0 else '下'}）", "source_text": p}
        for i, p in enumerate(parts)
    ]


def split_novel_into_episodes(
    text: str,
    split_mode: str = "auto_chapter",
    chars_per_episode: int = 2000,
) -> list[dict[str, str]]:
    """
    Split raw novel text into episodes.
    - auto_chapter: detects Chinese/English chapter titles; splits oversized chapters cleanly by paragraph.
      Falls back to by_length if fewer than 2 headings are detected.
    - by_length: ignores headings and chunks cleanly by paragraph near chars_per_episode.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    if split_mode == "auto_chapter":
        lines = normalized.split("\n")
        sections: list[tuple[str, list[str]]] = []
        current_title: str | None = None
        current_lines: list[str] = []
        preface_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if stripped and len(stripped) <= 64 and CHAPTER_HEADING_RE.match(stripped):
                heading = stripped.lstrip("#").strip()
                if current_title is not None:
                    sections.append((current_title, current_lines))
                elif preface_lines and len("".join(preface_lines).strip()) >= 80:
                    sections.append(("序幕 / 引子", preface_lines))
                current_title = heading
                current_lines = []
            else:
                if current_title is None:
                    preface_lines.append(line)
                else:
                    current_lines.append(line)

        if current_title is not None:
            sections.append((current_title, current_lines))

        if len(sections) >= 1:
            episodes: list[dict[str, str]] = []
            for sec_title, sec_lines in sections:
                sec_body = "\n".join(sec_lines).strip()
                if not sec_body:
                    continue
                episodes.extend(_split_long_text_by_paragraphs(sec_title, sec_body, chars_per_episode))
            if episodes:
                return episodes

    # Fallback or explicit by_length mode
    paras = [p.strip() for p in re.split(r"\n+", normalized) if p.strip()]
    episodes = []
    buf: list[str] = []
    cur_len = 0
    ep_num = 1
    for para in paras:
        if cur_len + len(para) > chars_per_episode and buf:
            episodes.append({"title": f"第 {ep_num} 集", "source_text": "\n\n".join(buf)})
            ep_num += 1
            buf = [para]
            cur_len = len(para)
        else:
            buf.append(para)
            cur_len += len(para)
    if buf:
        episodes.append({"title": f"第 {ep_num} 集", "source_text": "\n\n".join(buf)})
    return episodes


BOOK_BIBLE_SYSTEM_PROMPT = """你是一位顶级漫剧/影视改编制片人与美术总监。
你将阅读一部小说的完整或核心章节文本，请你提取整部作品需要跨集保持高度一致性的「全局视觉设定集（Book Bible）」。
严格返回如下 JSON（不要附加任何多余说明）：
{
  "style_prompt": "全剧统一视觉基调（中文，描述画风、色调、光影、镜头质感）",
  "bgm_prompt": "全剧主题配乐的英文 Lyria 3 提示词",
  "assets": [
    {
      "name": "简短清晰的角色/场景/关键道具名（不含特殊符号）",
      "kind": "character" 或 "scene" 或 "prop",
      "description": "极度具体的中文外貌/服装/建筑/材质设定（供 Nano Banana 2 生成定妆照与三视图，确保第1集到第50集外观不跑偏）"
    }
  ],
  "episode_summaries": [
    {"order_index": 0, "summary": "该集 50 字以内的核心剧情梗概"}
  ]
}
要求：角色提取核心人物（3~8位），场景提取高频核心地点（2~6个），关键道具（1~3个）。"""


def extract_book_bible(
    novel_title: str,
    episodes: list[dict[str, Any]],
    settings: RuntimeSettings | None = None,
) -> tuple[dict[str, Any], str, bool]:
    """Use Gemini's 1M long-context window to extract global Characters/Scenes/Props across the novel."""
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        # Extract candidate names/snippets deterministically from the imported novel text
        sample_text = "\n".join(e["source_text"][:500] for e in episodes[:3])
        snippet = sample_text.replace("\n", " ")[:60]
        return (
            {
                "style_prompt": f"《{novel_title}》专属电影级改编画风：细腻体积光、高对比度叙事光影、35mm 电影景深与高一致性人物建模",
                "bgm_prompt": "Emotional cinematic film score with warm strings, subtle piano motif and atmospheric percussion, 92 BPM",
                "assets": [
                    {
                        "name": "主角（小说核心人物）",
                        "kind": "character",
                        "description": f"基于《{novel_title}》原文提炼的核心主角形象，五官立体辨识度高，服装细节统一，适配跨集连续出镜（Demo 演示设定，接入 GEMINI_API_KEY 后将自动精准读完整本小说提炼所有真实角色名与外貌）",
                    },
                    {
                        "name": "核心故事主场景",
                        "kind": "scene",
                        "description": f"《{novel_title}》核心开篇与高频场景：{snippet}...",
                    },
                    {
                        "name": "关键线索道具",
                        "kind": "prop",
                        "description": "贯穿剧情的核心信物/道具，高细节写实材质，带电影级微距光泽",
                    },
                ],
                "episode_summaries": [
                    {
                        "order_index": e["order_index"],
                        "summary": f"本集（{e['title']}）约 {len(e['source_text'])} 字：{e['source_text'].strip().replace(chr(10), ' ')[:55]}...",
                    }
                    for e in episodes
                ],
            },
            "demo-bible",
            True,
        )

    client = create_genai_client(cfg, timeout_seconds=180)
    # Concatenate chapters up to ~280,000 chars (well within Gemini 4 1M token window!)
    parts: list[str] = [f"小说名称：《{novel_title}》\n"]
    total_chars = 0
    for ep in episodes:
        chunk = f"\n=== [order_index={ep['order_index']}] {ep['title']} ===\n{ep['source_text']}\n"
        if total_chars + len(chunk) > 280000:
            break
        parts.append(chunk)
        total_chars += len(chunk)

    interaction = client.interactions.create(
        model=cfg.text_model,
        system_instruction=BOOK_BIBLE_SYSTEM_PROMPT,
        input="".join(parts),
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": BookBibleOutput.model_json_schema(),
        },
        store=False,
    )
    raw = (interaction.output_text or "{}").strip()
    try:
        parsed = BookBibleOutput.model_validate_json(raw).model_dump()
    except Exception:
        parsed = json.loads(raw)
    return parsed, cfg.text_model, False


EPISODE_BREAKDOWN_SYSTEM_PROMPT = """你是一位擅长把网文/小说改编为高质量 AI 短剧的分镜导演。
你会收到：
1. 全局角色/场景/道具资产设定（必须严格使用资产清单中的准确名称，以便系统自动挂载定妆图保持角色不崩！）
2. 上一集剧情衔接摘要（如有）
3. 本集小说原文与目标镜头数

请将本集原文改编为极具画面感、节奏紧凑、适合 Veo 3.1 / Gemini Omni 1.2 Flash / Google Flow 生成的连续分镜脚本，严格输出 JSON：
- 每个镜头的 `video_prompt_en` 遵循 Omni 1.2 Flash 与 Veo 3.1 规范：使用自然语言描述构图、动作、光影与同期声，默认加入 "Continuous, unbroken single shot, no scene cuts"，严禁使用已废弃 XML 标签。
- `dialogue` 为该镜头内的核心台词或精炼旁白（中文，控制在 18 字内便于 6 秒镜头说完，可留空）。"""


def breakdown_episode_to_shots(
    episode_title: str,
    episode_text: str,
    prev_summary: str,
    project_style: str,
    assets: list[dict[str, str]],
    target_shots: int = 6,
    settings: RuntimeSettings | None = None,
) -> tuple[dict[str, Any], str, bool]:
    cfg = settings or load_settings()
    if cfg.effective_mode == "demo":
        paras = [p.strip() for p in re.split(r"\n+", episode_text) if p.strip()]
        if not paras:
            paras = [episode_title]
        asset_names = [a["name"] for a in assets[:2]]
        shot_types = ["远景", "中景", "中近景", "特写", "全景", "近景"]
        cam_moves = ["缓慢推进", "侧面跟拍", "横摇", "缓慢拉远", "俯拍航拍", "固定机位"]
        shots: list[dict[str, Any]] = []
        for i in range(target_shots):
            p_idx = min(len(paras) - 1, int(i * len(paras) / max(1, target_shots)))
            excerpt = paras[p_idx][:75]
            st = shot_types[i % len(shot_types)]
            cm = cam_moves[i % len(cam_moves)]
            shots.append(
                {
                    "title": f"{episode_title} · 镜{i + 1}",
                    "shot_type": st,
                    "camera_movement": cm,
                    "visual_prompt_zh": f"【改编自原文】{excerpt}",
                    "video_prompt_en": (
                        f"Cinematic {st} shot with {cm}, adapting scene from '{episode_title}': "
                        f"expressive storytelling lighting, rich atmosphere, smooth motion, synchronized ambient audio, 35mm film look"
                    ),
                    "dialogue": excerpt[:22] if i % 2 == 0 else "",
                    "sfx_prompt": "沉浸式场景环境音、自然动作拟音",
                    "duration_sec": 6,
                    "asset_names": asset_names,
                }
            )
        return (
            {
                "summary": f"{episode_title} 改编分镜（共 {target_shots} 镜）：{paras[0][:50]}...",
                "shots": shots,
            },
            "demo-episode-breakdown",
            True,
        )

    client = create_genai_client(cfg, timeout_seconds=180)
    payload_text = (
        f"全剧画风：{project_style}\n"
        f"全局资产库（asset_names 必须从以下 name 中精确挑选）：\n"
        f"{json.dumps(assets, ensure_ascii=False, indent=2)}\n\n"
        f"上一集剧情衔接摘要：{prev_summary or '（本集为开篇第一集）'}\n"
        f"目标分镜数：约 {target_shots} 个镜头（每镜 4~8 秒，推荐 6 秒）\n\n"
        f"=== 本集标题：{episode_title} ===\n"
        f"{episode_text[:30000]}"
    )

    interaction = client.interactions.create(
        model=cfg.text_model,
        system_instruction=EPISODE_BREAKDOWN_SYSTEM_PROMPT,
        input=payload_text,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": EpisodeBreakdownOutput.model_json_schema(),
        },
        store=False,
    )
    raw = (interaction.output_text or "{}").strip()
    try:
        parsed = EpisodeBreakdownOutput.model_validate_json(raw).model_dump()
    except Exception:
        parsed = json.loads(raw)
    return parsed, cfg.text_model, False
