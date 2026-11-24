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
    kind: Mapped[str] = mapped_column(String(32), default="character")  # character | scene | prop | audio
    description: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    turnaround_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
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
    has_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    prompt_used: Mapped[str] = mapped_column(Text, default="")
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
    include_bgm: Mapped[bool] = mapped_column(Boolean, default=True)
    burn_subtitles: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="exports")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # Lightweight additive migrations for existing local SQLite databases
    insp = inspect(engine)
    with engine.begin() as conn:
        if "projects" in insp.get_table_names():
            p_cols = {c["name"] for c in insp.get_columns("projects")}
            if "novel_title" not in p_cols:
                conn.execute(text("ALTER TABLE projects ADD COLUMN novel_title VARCHAR(200) DEFAULT ''"))
        if "shots" in insp.get_table_names():
            s_cols = {c["name"] for c in insp.get_columns("shots")}
            if "episode_id" not in s_cols:
                conn.execute(text("ALTER TABLE shots ADD COLUMN episode_id VARCHAR(32)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
