from __future__ import annotations

import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from app.config import DATA_DIR, DB_PATH


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


DATA_DIR.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    f"sqlite:///{DB_PATH.as_posix()}",
    connect_args={"check_same_thread": False, "timeout": 30},
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    aspect_ratio: Mapped[str] = mapped_column(String(16), default="16:9")
    style_prompt: Mapped[str] = mapped_column(Text, default="电影质感，自然光影，高细节写实摄影")
    bgm_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bgm_prompt: Mapped[str] = mapped_column(Text, default="")
    bgm_volume: Mapped[float] = mapped_column(Float, default=0.25)
    subtitle_srt: Mapped[str] = mapped_column(Text, default="")
    novel_title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    assets: Mapped[list["Asset"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    episodes: Mapped[list["Episode"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Episode.order_index")
    shots: Mapped[list["Shot"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="Shot.order_index")
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="ChatMessage.created_at")
    exports: Mapped[list["ExportRecord"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="ExportRecord.created_at.desc()")
    studio_jobs: Mapped[list["StudioJob"]] = relationship(back_populates="project", cascade="all, delete-orphan", order_by="StudioJob.created_at.desc()")


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    target_shots: Mapped[int] = mapped_column(Integer, default=6)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending | parsed | produced
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="episodes")
    shots: Mapped[list["Shot"]] = relationship(back_populates="episode", order_by="Shot.order_index")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="character")  # character | scene | prop | audio | video
    description: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    turnaround_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_type: Mapped[str] = mapped_column(String(16), default="image")  # image | video | audio
    mime_type: Mapped[str] = mapped_column(String(64), default="")
    thumb_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    fps: Mapped[str | None] = mapped_column(String(32), nullable=True)
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    gemini_file_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gemini_file_expires_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="assets")


class Shot(Base):
    __tablename__ = "shots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[str | None] = mapped_column(ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True, index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(200), default="未命名镜头")
    shot_type: Mapped[str] = mapped_column(String(64), default="中景")
    camera_movement: Mapped[str] = mapped_column(String(64), default="缓慢推进")
    visual_prompt_zh: Mapped[str] = mapped_column(Text, default="")
    video_prompt_en: Mapped[str] = mapped_column(Text, default="")
    dialogue: Mapped[str] = mapped_column(Text, default="")
    sfx_prompt: Mapped[str] = mapped_column(Text, default="")
    duration_sec: Mapped[int] = mapped_column(Integer, default=6)
    asset_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    start_frame_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    end_frame_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    selected_take_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trim_start: Mapped[float] = mapped_column(Float, default=0.0)
    trim_end: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="shots")
    episode: Mapped["Episode | None"] = relationship(back_populates="shots")
    takes: Mapped[list["Take"]] = relationship(back_populates="shot", cascade="all, delete-orphan", order_by="Take.created_at.desc()")


class Take(Base):
    __tablename__ = "takes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    engine: Mapped[str] = mapped_column(String(32), default="veo_lite")
    model_id: Mapped[str] = mapped_column(String(120), default="")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_sec: Mapped[float] = mapped_column(Float, default=6.0)
    resolution: Mapped[str] = mapped_column(String(16), default="720p")
    has_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    prompt_used: Mapped[str] = mapped_column(Text, default="")
    interaction_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    parent_take_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="generate")  # generate | edit | extend | flow_import
    qa_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qa_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    shot: Mapped["Shot"] = relationship(back_populates="takes")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    proposal_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="messages")


class JobTask(Base):
    __tablename__ = "job_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    shot_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued | running | completed | failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(300), default="")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CostLog(Base):
    __tablename__ = "cost_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExportRecord(Base):
    __tablename__ = "export_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    resolution: Mapped[str] = mapped_column(String(32), default="1080p")
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    crossfade_sec: Mapped[float] = mapped_column(Float, default=0.0)
    include_bgm: Mapped[bool] = mapped_column(Boolean, default=True)
    burn_subtitles: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="exports")


class StudioJob(Base):
    __tablename__ = "studio_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str] = mapped_column(String(300), default="")
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    enhanced_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(120), default="gemini-omni-1.2-flash")
    aspect_ratio: Mapped[str] = mapped_column(String(16), default="16:9")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=10)
    resolution: Mapped[str] = mapped_column(String(16), default="720p")
    strip_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    task_override: Mapped[str | None] = mapped_column(String(32), nullable=True)
    first_frame_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_frame_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_video_asset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ref_image_asset_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    ref_video_asset_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    parent_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    previous_interaction_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    interaction_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    output_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_thumb_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_has_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    output_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="studio_jobs")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="sessions")


def _add_column_if_missing(conn, insp, table: str, column: str, ddl: str) -> None:
    if table not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column not in cols:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # Lightweight additive migrations for existing local SQLite databases
    insp = inspect(engine)
    with engine.begin() as conn:
        _add_column_if_missing(conn, insp, "projects", "novel_title", "VARCHAR(200) DEFAULT ''")
        _add_column_if_missing(conn, insp, "shots", "episode_id", "VARCHAR(32)")

        _add_column_if_missing(conn, insp, "assets", "media_type", "VARCHAR(16) DEFAULT 'image'")
        _add_column_if_missing(conn, insp, "assets", "mime_type", "VARCHAR(64) DEFAULT ''")
        _add_column_if_missing(conn, insp, "assets", "thumb_path", "VARCHAR(500)")
        _add_column_if_missing(conn, insp, "assets", "size_bytes", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, insp, "assets", "width", "INTEGER")
        _add_column_if_missing(conn, insp, "assets", "height", "INTEGER")
        _add_column_if_missing(conn, insp, "assets", "duration_sec", "FLOAT")
        _add_column_if_missing(conn, insp, "assets", "fps", "VARCHAR(32)")
        _add_column_if_missing(conn, insp, "assets", "has_audio", "BOOLEAN DEFAULT 0")
        _add_column_if_missing(conn, insp, "assets", "gemini_file_uri", "VARCHAR(500)")
        _add_column_if_missing(conn, insp, "assets", "gemini_file_expires_at", "VARCHAR(64)")

        _add_column_if_missing(conn, insp, "takes", "resolution", "VARCHAR(16) DEFAULT '720p'")
        _add_column_if_missing(conn, insp, "takes", "interaction_id", "VARCHAR(200)")
        _add_column_if_missing(conn, insp, "takes", "parent_take_id", "VARCHAR(32)")
        _add_column_if_missing(conn, insp, "takes", "mode", "VARCHAR(32) DEFAULT 'generate'")

        _add_column_if_missing(conn, insp, "export_records", "crossfade_sec", "FLOAT DEFAULT 0.0")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
