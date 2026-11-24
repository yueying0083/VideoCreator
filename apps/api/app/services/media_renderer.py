from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence


def get_ffmpeg_bin() -> str | None:
    system_bin = shutil.which("ffmpeg")
    if system_bin:
        return system_bin
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def aspect_to_dimensions(aspect_ratio: str, resolution: str = "1080p") -> tuple[int, int]:
    is_720 = resolution == "720p"
    if aspect_ratio == "9:16":
        return (720, 1280) if is_720 else (1080, 1920)
    if aspect_ratio == "1:1":
        return (720, 720) if is_720 else (1080, 1080)
    return (1280, 720) if is_720 else (1920, 1080)


def probe_media_info(video_path: Path) -> tuple[float, bool]:
    """Return (duration_sec, has_audio_stream) using ffmpeg -i."""
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg or not video_path.exists():
        return 6.0, False
    proc = subprocess.run(
        [ffmpeg, "-i", str(video_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    stderr = proc.stderr or ""
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    duration = 6.0
    if dur_match:
        h, m, s = int(dur_match.group(1)), int(dur_match.group(2)), float(dur_match.group(3))
        duration = round(h * 3600 + m * 60 + s, 2)
    has_audio = bool(re.search(r"Stream #\d+:\d+.*:\s*Audio:", stderr))
    return duration, has_audio


def extract_frame(video_path: Path, output_image_path: Path, at_end: bool = False) -> bool:
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg or not video_path.exists():
        return False
    output_image_path.parent.mkdir(parents=True, exist_ok=True)
    if at_end:
        duration, _ = probe_media_info(video_path)
        seek_pos = max(0.0, duration - 0.15)
        cmd = [
            ffmpeg, "-y",
            "-ss", f"{seek_pos:.2f}",
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output_image_path),
        ]
    else:
        cmd = [
            ffmpeg, "-y",
            "-ss", "0.1",
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output_image_path),
        ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return res.returncode == 0 and output_image_path.exists()


def generate_demo_video(
    output_path: Path,
    image_path: Path,
    duration_sec: int = 4,
    aspect_ratio: str = "16:9",
    with_audio: bool = True,
) -> Path:
    """Create a real playable MP4 from a keyframe image with smooth Ken Burns zoom + optional ambient tone."""
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("未找到 FFmpeg（请安装系统 FFmpeg 或确保 imageio-ffmpeg 可用）")

    w, h = aspect_to_dimensions(aspect_ratio, "720p")
    fps = 24
    total_frames = max(24, duration_sec * fps)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    zoom_filter = (
        f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
        f"crop={w*2}:{h*2},"
        f"zoompan=z='min(zoom+0.0012,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={w}x{h}:fps={fps},"
        f"format=yuv420p"
    )

    cmd = [ffmpeg, "-y", "-loop", "1", "-i", str(image_path)]
    if with_audio:
        # Soft cinematic ambient drone tone
        cmd += [
            "-f", "lavfi",
            "-i", f"aevalsrc=0.05*sin(2*PI*220*t)+0.03*sin(2*PI*330*t):d={duration_sec}:s=44100",
        ]
    cmd += ["-vf", zoom_filter, "-t", str(duration_sec), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if with_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    else:
        cmd += ["-an"]
    cmd.append(str(output_path))

    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if res.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"FFmpeg 生成演示视频失败: {res.stderr[-400:]}")
    return output_path


def generate_demo_music(output_path: Path, duration_sec: int = 16) -> Path:
    """Synthesize a pleasant ambient chord progression MP3 via FFmpeg for Demo Mode."""
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("未找到 FFmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    expr = (
        "0.08*sin(2*PI*261.63*t)*sin(2*PI*0.25*t)+"
        "0.06*sin(2*PI*329.63*t)+"
        "0.05*sin(2*PI*392.00*t)*cos(2*PI*0.125*t)+"
        "0.04*sin(2*PI*523.25*t)"
    )
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi",
        "-i", f"aevalsrc={expr}:d={duration_sec}:s=44100",
        "-af", f"afade=t=in:st=0:d=1.2,afade=t=out:st={max(1, duration_sec - 2)}:d=2",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        str(output_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if res.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"FFmpeg 生成演示配乐失败: {res.stderr[-400:]}")
    return output_path


def _escape_ffmpeg_sub_path(path: Path) -> str:
    # FFmpeg subtitles filter on Windows requires forward slashes and escaped colon
    s = path.resolve().as_posix()
    s = s.replace(":", "\\:")
    s = s.replace("'", "\\'")
    return s


def render_timeline_export(
    clips: Sequence[dict],
    output_path: Path,
    aspect_ratio: str = "16:9",
    resolution: str = "1080p",
    bgm_path: Path | None = None,
    bgm_volume: float = 0.25,
    subtitle_srt: str = "",
) -> float:
    """
    Concatenate shot clips with normalization, optional BGM mixing, and optional SRT subtitle burn-in.
    Each clip dict: {"path": Path, "trim_start": float, "trim_end": float | None, "duration_sec": float, "has_audio": bool}
    Returns final exported duration in seconds.
    """
    ffmpeg = get_ffmpeg_bin()
    if not ffmpeg:
        raise RuntimeError("未找到 FFmpeg，无法合片导出")
    if not clips:
        raise ValueError("时间线上没有已选中的镜头视频，请先为至少一个镜头生成或导入视频并锁定 Take")

    w, h = aspect_to_dimensions(aspect_ratio, resolution)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [ffmpeg, "-y"]
    filter_parts: list[str] = []
    concat_inputs: list[str] = []
    total_duration = 0.0

    for idx, clip in enumerate(clips):
        clip_path: Path = clip["path"]
        raw_dur, detected_audio = probe_media_info(clip_path)
        t_start = max(0.0, float(clip.get("trim_start") or 0.0))
        t_end_raw = clip.get("trim_end")
        t_end = float(t_end_raw) if (t_end_raw is not None and float(t_end_raw) > t_start) else raw_dur
        t_end = min(raw_dur, t_end)
        seg_dur = max(0.2, t_end - t_start)
        total_duration += seg_dur

        cmd += ["-ss", f"{t_start:.3f}", "-t", f"{seg_dur:.3f}", "-i", str(clip_path)]

        filter_parts.append(
            f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=24,format=yuv420p[v{idx}]"
        )
        if detected_audio:
            filter_parts.append(
                f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                f"aresample=async=1[a{idx}]"
            )
        else:
            filter_parts.append(
                f"anullsrc=channel_layout=stereo:sample_rate=44100,atrim=duration={seg_dur:.3f}[a{idx}]"
            )
        concat_inputs.append(f"[v{idx}][a{idx}]")

    n = len(clips)
    filter_parts.append(f"{''.join(concat_inputs)}concat=n={n}:v=1:a=1[vcat][acat]")

    video_label = "[vcat]"
    audio_label = "[acat]"

    if bgm_path and bgm_path.exists():
        bgm_idx = n
        cmd += ["-stream_loop", "-1", "-i", str(bgm_path)]
        fade_out_start = max(0.0, total_duration - 1.5)
        vol = max(0.0, min(1.5, float(bgm_volume)))
        filter_parts.append(
            f"[{bgm_idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"atrim=duration={total_duration:.3f},volume={vol:.2f},"
            f"afade=t=in:st=0:d=0.8,afade=t=out:st={fade_out_start:.2f}:d=1.5[bgm]"
        )
        filter_parts.append(
            f"[acat][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[amixout]"
        )
        audio_label = "[amixout]"

    temp_srt_file: Path | None = None
    try:
        if subtitle_srt and subtitle_srt.strip():
            with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", delete=False, encoding="utf-8") as tf:
                tf.write(subtitle_srt.strip() + "\n")
                temp_srt_file = Path(tf.name)
            escaped = _escape_ffmpeg_sub_path(temp_srt_file)
            font_part = "" if os.name == "nt" else "FontName=WenQuanYi Zen Hei,"
            filter_parts.append(
                f"{video_label}subtitles='{escaped}':force_style='{font_part}FontSize=20,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,Outline=2,MarginV=28'[vsub]"
            )
            video_label = "[vsub]"

        filter_complex = ";".join(filter_parts)
        cmd += [
            "-filter_complex", filter_complex,
            "-map", video_label,
            "-map", audio_label,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if res.returncode != 0 or not output_path.exists():
            raise RuntimeError(f"FFmpeg 导出失败: {res.stderr[-600:]}")
    finally:
        if temp_srt_file and temp_srt_file.exists():
            temp_srt_file.unlink(missing_ok=True)

    final_dur, _ = probe_media_info(output_path)
    return final_dur
