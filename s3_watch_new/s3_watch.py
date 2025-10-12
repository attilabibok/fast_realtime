#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S3 & URL Status Dashboard

- Matches the original watcher defaults:
  * SCAN_INTERVAL_SECONDS (default 10 min)
  * REFRESH_INTERVAL_SECONDS (default 60 min freshness window)
  * S3_UNSIGNED default True (public buckets)
  * WATCHES_JSON bootstrap
  * Parallel S3 HEADs with S3_MAX_CONCURRENCY
  * Streak counters, 90-day dashboard, /download behavior

- Adds URL checks WITHOUT DB migrations:
  * URL watches are stored using a sentinel bucket name "__URL__"
  * key holds the full URL string
  * Checker routes to HTTP/HTTPS logic when bucket == "__URL__"
"""

from __future__ import annotations
import asyncio
import enum
import logging
import json
import isodate
import re
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple

import io, csv
import httpx
from pydantic import BaseModel, Field, HttpUrl
from pydantic_settings import BaseSettings

from botocore import UNSIGNED
from botocore.config import Config
import boto3
from botocore.exceptions import ClientError
from fastapi import Query
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    JSONResponse,
    PlainTextResponse,
)
from fastapi.middleware.cors import CORSMiddleware

from jinja2 import Environment, BaseLoader, select_autoescape
from statistics import mean

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Float,
    Enum as SAEnum,
    UniqueConstraint,
    ForeignKey,
    select,
    func,
    text,
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from urllib.parse import quote  # for safe S3 key URLs


# ---------------- Settings ----------------
class Settings(BaseSettings):
    # Point this to your bind mount, e.g., sqlite+aiosqlite:////data/s3_watch.db
    DATABASE_URL: str = "sqlite+aiosqlite:///./s3_watch.db"

    # Scan cadence vs staleness window (MATCH ORIGINAL)
    SCAN_INTERVAL_SECONDS: int = 600  # default: 10 minutes between scans
    REFRESH_INTERVAL_SECONDS: int = 3600  # default: expect new object within 1 hour

    # Optional bootstrap list (MATCH ORIGINAL)
    WATCHES_JSON: Optional[
        str
    ] = """[
            {"bucket":"knatempstorage","key":"nwm_txdot_output/short_range_da_kf/streamflow_kf_sr.nc","name":"Data Assimilation output"},
            {"bucket":"knatempstorage","key":"nwm_txdot_output/short_range_da_kf/streamflow_gages.geojson","name":"Data Assimilation flow gage layer"},
            {"bucket":"knatempstorage","key":"fast_realtime/da/TXFull/bridge_warning_pnts.geojson","name":"DA - Bridges"},
            {"bucket":"knatempstorage","key":"fast_realtime/da/TXFull/flood_ar.geojson","name":"DA - Inundation"},
            {"bucket":"knatempstorage","key":"fast_realtime/da/TXFull/flood_road_trim_ln.geojson","name":"DA - Roads"},
            {"bucket":"knatempstorage","key":"fast_realtime/da_nc/TXFull/bridge_warning_pnts.geojson","name":"DA Nowcast - Bridges"},
            {"bucket":"knatempstorage","key":"fast_realtime/da_nc/TXFull/flood_ar.geojson","name":"DA Nowcast - Inundation"},
            {"bucket":"knatempstorage","key":"fast_realtime/da_nc/TXFull/flood_road_trim_ln.geojson","name":"DA Nowcast - Roads"},
            {"bucket":"knatempstorage","key":"fast_realtime/nwm/TXFull/bridge_warning_pnts.geojson","name":"NWM - Bridges"},
            {"bucket":"knatempstorage","key":"fast_realtime/nwm/TXFull/flood_ar.geojson","name":"NWM - Inundation"},
            {"bucket":"knatempstorage","key":"fast_realtime/nwm/TXFull/flood_road_trim_ln.geojson","name":"NWM - Roads"},
            {"bucket":"knatempstorage","key":"fast_realtime/nwm_nc/TXFull/bridge_warning_pnts.geojson","name":"NWM Nowcast - Bridges"},
            {"bucket":"knatempstorage","key":"fast_realtime/nwm_nc/TXFull/flood_ar.geojson","name":"NWM Nowcast - Inundation"},
            {"bucket":"knatempstorage","key":"fast_realtime/nwm_nc/TXFull/flood_road_trim_ln.geojson","name":"NWM Nowcast - Roads"},
            {"url":"https://bridges.txdot.kisters.cloud/eval/monitoring/fast","name":"FAST monitoring"},
            {"url":"https://bridges.txdot.kisters.cloud/eval/fast","name":"FAST dashboard"}
            ]"""

    # S3 config
    S3_UNSIGNED: bool = True
    S3_MAX_CONCURRENCY: int = 20  # parallel S3 requests cap

    # URL checking
    URL_COMPUTE_AGE: bool = False  # Only availability by default


settings = Settings()

# URL sentinel to avoid any DB migration
URL_SENTINEL_BUCKET = "__URL__"

# ---------------- DB models ----------------
Base = declarative_base()


class Status(str, enum.Enum):
    ok = "OK"
    missing = "MISSING"
    error = "ERROR"


class Watch(Base):
    __tablename__ = "watches"
    id = Column(Integer, primary_key=True)
    bucket = Column(String, nullable=False)  # keep NOT NULL to match existing DB
    key = Column(String, nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    logs = relationship(
        "CheckLog", back_populates="watch", cascade="all, delete-orphan"
    )
    __table_args__ = (UniqueConstraint("bucket", "key", name="uq_bucket_key"),)


class CheckLog(Base):
    __tablename__ = "check_logs"
    id = Column(Integer, primary_key=True)
    watch_id = Column(Integer, ForeignKey("watches.id"), nullable=False, index=True)
    checked_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_modified = Column(
        DateTime(timezone=True), nullable=True
    )  # for S3 and URL (if LM header)
    status = Column(SAEnum(Status), nullable=False)
    lag_minutes = Column(Float, nullable=True)
    message = Column(String, nullable=True)
    # Consecutive streak counters
    consec_ok = Column(Integer, nullable=False, default=0)
    consec_missing = Column(Integer, nullable=False, default=0)

    watch = relationship("Watch", back_populates="logs")


# -------------- Engine / Session --------------
async_engine = create_async_engine(settings.DATABASE_URL, future=True, echo=False)
AsyncSessionLocal = sessionmaker(
    async_engine, expire_on_commit=False, class_=AsyncSession
)


async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # best-effort add streak columns if they don't exist yet
        for col in ("consec_ok", "consec_missing"):
            try:
                await conn.execute(
                    text(
                        f"ALTER TABLE check_logs ADD COLUMN {col} INTEGER DEFAULT 0 NOT NULL"
                    )
                )
            except Exception:
                pass  # column exists


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ---------------- AWS helper (MATCH ORIGINAL) ----------------
@lru_cache(maxsize=1)
def _get_s3_client():
    cfg = Config(
        signature_version=UNSIGNED if settings.S3_UNSIGNED else None,
        max_pool_connections=max(10, settings.S3_MAX_CONCURRENCY * 2),
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=5,
        read_timeout=10,
    )
    return boto3.client("s3", config=cfg)


def _head_s3_object_sync(bucket: str, key: str) -> Optional[datetime]:
    client = _get_s3_client()
    try:
        resp = client.head_object(Bucket=bucket, Key=key)
        return resp["LastModified"].astimezone(timezone.utc)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


async def head_s3_object_async(bucket: str, key: str) -> Optional[datetime]:
    # run blocking boto3 in a thread
    return await asyncio.to_thread(_head_s3_object_sync, bucket, key)


# ---------------- HTTP/HTTPS helper (NEW) ----------------
async def check_http(
    url: str, method: str = "HEAD", timeout_s: float = 10.0
) -> Tuple[Status, str, Optional[datetime], Optional[float]]:
    """
    Return (status, message, last_modified, lag_minutes)
    Age only if Last-Modified header can be parsed.
    """
    try:
        t0 = datetime.now(timezone.utc)
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=timeout_s
        ) as client:
            try:
                r = await client.request(method.upper(), url)
            except httpx.HTTPStatusError as e:
                r = e.response
            except httpx.RequestError as e:
                return Status.error, f"RequestError: {e}", None, None

            # 405 on HEAD? Fall back to GET.
            if r.status_code == 405 and method.upper() == "HEAD":
                r = await client.get(url)

        t1 = datetime.now(timezone.utc)
        latency_ms = int((t1 - t0).total_seconds() * 1000)

        if 200 <= r.status_code < 400:
            lm = None
            lag = 0.0
            if settings.URL_COMPUTE_AGE:
                lm_hdr = r.headers.get("Last-Modified")
                if lm_hdr:
                    try:
                        from email.utils import parsedate_to_datetime

                        lm = parsedate_to_datetime(lm_hdr)
                        if lm.tzinfo is None:
                            lm = lm.replace(tzinfo=timezone.utc)
                        lm = lm.astimezone(timezone.utc)
                        lag = (t1 - lm).total_seconds() / 60.0
                    except Exception:
                        lm, lag = None, None
            msg = f"OK ({r.status_code}), {latency_ms} ms"
            return Status.ok, msg, lm, lag
        else:
            return Status.missing, f"HTTP {r.status_code}", None, None
    except Exception as e:
        return Status.error, f"Error: {type(e).__name__}: {e}", None, None


def ensure_utc(dt):
    if dt is None:
        return None
    # If the DB row is naive, assume it is UTC and attach tzinfo
    return (
        dt.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None
        else dt.astimezone(timezone.utc)
    )


# ---------------- Dashboard helpers ----------------
def _fmt_minutes(mins: float | None) -> str:
    if mins is None:
        return "—"
    mins = int(round(mins))
    h, m = divmod(mins, 60)
    if h == 0:
        return f"{m} min"
    if m == 0:
        return f"{h} hr"
    return f"{h} hr {m} min"


_SHORTHAND_RE = re.compile(r"^\s*(\d+)\s*([dhwDHw])\s*$")
def _parse_period(s: str) -> timedelta:
    if not s:
        raise HTTPException(400, "Empty period")
    s = s.strip()

    # 1) Support Nd/Nh/Nw
    m = _SHORTHAND_RE.match(s)
    if m:
        num = int(m.group(1))
        unit = m.group(2).lower()
        if num <= 0:
            raise HTTPException(400, f"Invalid period: {s}")
        return (
            timedelta(days=num)   if unit == "d" else
            timedelta(hours=num)  if unit == "h" else
            timedelta(weeks=num)  # unit == "w"
        )

    # 2) ISO 8601 via isodate (e.g., P1D, PT48H, P1DT2H30M)
    try:
        dur = isodate.parse_duration(s)
    except Exception:
        raise HTTPException(400, f"Unsupported period format: {s}. Use Nd/Nh/Nw or ISO 8601 like P1D, PT12H.")

    # If months/years are present, this becomes ambiguous -> reject
    # (isodate uses Duration for these; only allow conversion when Y/M are zero)
    if hasattr(dur, "years") or hasattr(dur, "months"):
        years = getattr(dur, "years", 0) or 0
        months = getattr(dur, "months", 0) or 0
        if years or months:
            raise HTTPException(400, "Year/Month durations are not supported. Use weeks/days/hours/minutes/seconds.")
        # Safe to convert:
        return dur.totimedelta()

    # Already a timedelta
    return dur

def _resolve_range(from_param: Optional[str], to_param: Optional[str], period: Optional[str]) -> tuple[datetime, datetime]:
    """
    If period is given and from/to are missing, compute [now - period, now].
    Otherwise require from & to.
    """
    if period and (from_param is None and to_param is None):
        end = datetime.now(timezone.utc)
        start = end - _parse_period(period)
        return start, end
    if from_param is None or to_param is None:
        raise HTTPException(400, "Provide either 'period' OR both 'from' and 'to'")
    start = _parse_when(from_param)
    end = _parse_when(to_param)
    if end <= start:
        raise HTTPException(400, "'to' must be after 'from'")
    return start, end

def _donut_svg(
    pct: float, size: int = 140, stroke: int = 12, color: str = "#2ecc71"
) -> str:
    pct = max(0.0, min(100.0, pct))
    r = (size - stroke) / 2
    c = 2 * 3.1415926535 * r
    dash = (pct / 100.0) * c
    gap = c - dash
    cx = cy = size / 2
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" aria-label="{pct:.1f}% uptime">
      <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#e5e7eb" stroke-width="{stroke}" />
      <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}"
              stroke-dasharray="{dash:.3f} {gap:.3f}" stroke-linecap="round"
              transform="rotate(-90 {cx} {cy})"/>
      <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
            font-size="{size*0.22:.0f}" font-weight="700" fill="#1f2937">{pct:.0f}%</text>
    </svg>
    """


def _uptime_color(pct: float) -> str:
    """Return a hex color for the donut based on uptime percentage."""
    if pct > 99.0:
        return "#16a34a"  # green
    if pct >= 95.0:
        return "#f59e0b"  # yellow
    if pct >= 90.0:
        return "#f97316"  # orange
    return "#ef4444"  # red

def _arrow(curr: float | None, prev: float | None, higher_is_better: bool) -> str:
    """Return a small colored arrow/equal badge as HTML."""
    if curr is None or prev is None:
        return '<span style="color:#9ca3af;font-weight:700">–</span>'
    if abs(curr - prev) < 1e-9:
        return '<span style="color:#9ca3af;font-weight:700">=</span>'
    up = curr > prev
    good = (up if higher_is_better else not up)
    color = "#16a34a" if good else "#ef4444"  # green / red
    sym = "▲" if up else "▼"
    return f'<span style="color:{color};font-weight:700">{sym}</span>'

def _pct_fmt(v: float | None) -> str:
    return ("—" if v is None else f"{v:.0f}%")

def _mins_fmt(v: float | None) -> str:
    return _fmt_minutes(v)  # you already have this helper

# ---------------- Datetime parser ----------------
def _parse_when(s: str) -> datetime:
    """
    Accepts ISO-8601 (with or without 'Z') or yyyymmddhhmm.
    Naive datetimes are treated as UTC.
    """
    s = s.strip()
    # yyyymmddhhmm (12 digits)
    if len(s) == 12 and s.isdigit():
        dt = datetime.strptime(s, "%Y%m%d%H%M")
        return dt.replace(tzinfo=timezone.utc)
    # ISO
    try:
        # Allow trailing Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except Exception:
        raise HTTPException(400, f"Invalid datetime: {s}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------- Pydantic ----------------
class WatchIn(BaseModel):
    # EITHER a bucket/key OR a URL
    bucket: Optional[str] = None
    key: Optional[str] = None
    url: Optional[HttpUrl] = None
    name: Optional[str] = None


class WatchOut(BaseModel):
    id: int
    bucket: str
    key: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------- Monitor loop (MATCH + URL) ----------------
log = logging.getLogger("s3watch")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)


def _is_url_watch(w: Watch) -> bool:
    return w.bucket == URL_SENTINEL_BUCKET


def _display_target(w: Watch) -> str:
    return w.key if _is_url_watch(w) else f"s3://{w.bucket}/{w.key}"


async def upsert_watch(db: AsyncSession, w: WatchIn) -> Watch:
    # Normalize input
    if w.url and (w.bucket or w.key):
        raise HTTPException(400, "Provide either (bucket & key) OR url")

    if w.url:
        bucket = URL_SENTINEL_BUCKET
        key = str(w.url)
        name = w.name or f"URL: {key}"
    else:
        if not (w.bucket and w.key):
            raise HTTPException(400, "Provide either (bucket & key) OR url")
        bucket = w.bucket
        key = w.key
        name = w.name or f"{bucket}/{key}"

    existing = await db.execute(
        select(Watch).where(Watch.bucket == bucket, Watch.key == key)
    )
    obj = existing.scalar_one_or_none()
    if obj:
        obj.name = name
    else:
        obj = Watch(bucket=bucket, key=key, name=name)
        db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def scan_once(db: AsyncSession):
    now = datetime.now(timezone.utc)
    freshness = timedelta(seconds=settings.REFRESH_INTERVAL_SECONDS)

    res = await db.execute(select(Watch))
    watches: List[Watch] = list(res.scalars())

    sem = asyncio.Semaphore(settings.S3_MAX_CONCURRENCY)

    async def check_watch(w: Watch):
        status: Status
        lm: Optional[datetime] = None
        lag: Optional[float] = None
        msg: Optional[str] = None
        try:
            async with sem:
                if _is_url_watch(w):
                    status, msg, lm, lag = await check_http(w.key, "HEAD")
                else:
                    lm = await head_s3_object_async(w.bucket, w.key)

            if _is_url_watch(w):
                # For URLs: OK/MISSING already set in check_http
                pass
            else:
                if lm is None:
                    status, msg = Status.missing, "Object missing"
                else:
                    lag_td = now - lm
                    lag = lag_td.total_seconds() / 60.0
                    status = Status.ok if lag_td <= freshness else Status.missing
                    if status is Status.missing:
                        msg = f"Stale: last update {lag:.1f} minutes ago"
                    else:
                        msg = "OK"
        except Exception as e:
            status, msg = Status.error, f"Error: {type(e).__name__}: {e}"
        return {"watch": w, "lm": lm, "status": status, "lag": lag, "msg": msg}

    # run all checks in parallel
    results = await asyncio.gather(*(check_watch(w) for w in watches))

    # fetch last logs for ALL watches (for streaks)
    if watches:
        watch_ids = [w.id for w in watches]
        subq = (
            select(CheckLog.watch_id, func.max(CheckLog.checked_at).label("mx"))
            .where(CheckLog.watch_id.in_(watch_ids))
            .group_by(CheckLog.watch_id)
            .subquery()
        )
        q_last = select(CheckLog).join(
            subq,
            (CheckLog.watch_id == subq.c.watch_id) & (CheckLog.checked_at == subq.c.mx),
        )
        last_map = {row.watch_id: row for row in (await db.execute(q_last)).scalars()}
    else:
        last_map = {}

    # insert logs in one transaction
    for r in results:
        w: Watch = r["watch"]
        status: Status = r["status"]
        prev: Optional[CheckLog] = last_map.get(w.id)

        consec_ok = (
            (prev.consec_ok + 1)
            if (prev and prev.status == Status.ok and status == Status.ok)
            else (1 if status == Status.ok else 0)
        )
        consec_missing = (
            (prev.consec_missing + 1)
            if (prev and prev.status == Status.missing and status == Status.missing)
            else (1 if status == Status.missing else 0)
        )

        db.add(
            CheckLog(
                watch_id=w.id,
                checked_at=now,
                last_modified=r["lm"],
                status=status,
                lag_minutes=r["lag"],
                message=r["msg"],
                consec_ok=consec_ok,
                consec_missing=consec_missing,
            )
        )

        # log lines
        tgt = _display_target(w)
        if status is Status.ok:
            age = 0 if r["lag"] is None else round(r["lag"], 1)
            log.info(
                f"[{w.name}] OK (age {age} min) target={tgt} streak_ok={consec_ok}"
            )
        elif status is Status.missing:
            log.warning(
                f"[{w.name}] MISSING ({r['msg']}) target={tgt} streak_missing={consec_missing}"
            )
        else:
            log.error(f"[{w.name}] ERROR ({r['msg']}) target={tgt}")

    await db.commit()


async def monitor_loop():
    await init_db()
    # Optional bootstrap from env (MATCH ORIGINAL)
    if settings.WATCHES_JSON:
        try:
            data = json.loads(settings.WATCHES_JSON)
            async with AsyncSessionLocal() as db:
                for item in data:
                    # Allow bootstrap to also include {"url": "..."} if desired
                    await upsert_watch(db, WatchIn(**item))
        except Exception as e:
            log.error(f"Failed to load WATCHES_JSON: {e}")

    log.info("Starting monitor loop...")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await scan_once(db)
        except Exception as e:
            log.error(f"scan_once failed: {e}")
        await asyncio.sleep(settings.SCAN_INTERVAL_SECONDS)


async def _compute_rows(db: AsyncSession, start: datetime, end: datetime):
    # Mostly the same logic used in /stats to produce per-watch rows
    res_w = await db.execute(select(Watch).order_by(Watch.id))
    watches = list(res_w.scalars())
    if not watches:
        return []

    watch_ids = [w.id for w in watches]
    q = (
        select(CheckLog)
        .where(
            CheckLog.watch_id.in_(watch_ids),
            CheckLog.checked_at >= start,
            CheckLog.checked_at < end,
        )
        .order_by(CheckLog.watch_id.asc(), CheckLog.checked_at.asc())
    )
    res_logs = await db.execute(q)
    logs = list(res_logs.scalars())

    buckets: dict[int, list[CheckLog]] = {}
    for lg in logs:
        buckets.setdefault(lg.watch_id, []).append(lg)

    scan_minutes = settings.SCAN_INTERVAL_SECONDS / 60.0
    rows = []
    for w in watches:
        items = buckets.get(w.id, [])
        n_ok = sum(1 for x in items if x.status == Status.ok)
        n_miss = sum(1 for x in items if x.status == Status.missing)
        n_err = sum(1 for x in items if x.status == Status.error)
        total = n_ok + n_miss + n_err
        uptime = (100.0 * n_ok / total) if total > 0 else 0.0

        # missing streaks → outages
        max_consec_miss = 0
        total_outage_mins = 0.0
        max_outage_mins = 0.0
        streak = 0
        for x in items:
            if x.status == Status.missing:
                streak += 1
            else:
                if streak:
                    dur = streak * scan_minutes
                    total_outage_mins += dur
                    if dur > max_outage_mins:
                        max_outage_mins = dur
                    if streak > max_consec_miss:
                        max_consec_miss = streak
                streak = 0
        if streak:
            dur = streak * scan_minutes
            total_outage_mins += dur
            if dur > max_outage_mins:
                max_outage_mins = dur
            if streak > max_consec_miss:
                max_consec_miss = streak

        is_url = w.bucket == URL_SENTINEL_BUCKET
        ages = [
            x.lag_minutes for x in items if (not is_url and x.lag_minutes is not None)
        ]
        min_age = min(ages) if ages else None
        max_age = max(ages) if ages else None
        avg_age = mean(ages) if ages else None

        rows.append(
            {
                "watch_id": w.id,
                "watch_name": w.name,
                "type": "url" if is_url else "s3",
                "url": (w.key if is_url else f"s3://{w.bucket}/{w.key}"),
                "uptime": uptime,
                "n_ok": n_ok,
                "n_miss": n_miss,
                "n_err": n_err,
                "max_consec_miss": max_consec_miss,
                "max_outage_mins": max_outage_mins,
                "total_outage_mins": total_outage_mins,
                "min_age": min_age,
                "max_age": max_age,
                "avg_age": avg_age,
            }
        )
    return rows


# ---------------- FastAPI ----------------
app = FastAPI(title="S3 & URL Watch", version="1.2.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.on_event("startup")
async def on_start():
    asyncio.create_task(monitor_loop())


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    row = await db.execute(select(func.max(CheckLog.checked_at)))
    last = row.scalar()
    return {
        "ok": True,
        "last_scan_utc": last,
        "scan_interval_s": settings.SCAN_INTERVAL_SECONDS,
        "refresh_window_s": settings.REFRESH_INTERVAL_SECONDS,
    }


# ---- Watches CRUD ----
@app.get("/watches", response_model=List[WatchOut])
async def list_watches(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Watch).order_by(Watch.id))
    return list(res.scalars())


@app.post("/watches", response_model=WatchOut)
async def add_watch(w: WatchIn, db: AsyncSession = Depends(get_db)):
    try:
        return await upsert_watch(db, w)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not add watch: {e}")


@app.delete("/watches/{watch_id}")
async def delete_watch(watch_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Watch).where(Watch.id == watch_id))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(404, "Not found")
    await db.delete(obj)
    await db.commit()
    return {"deleted": watch_id}


@app.get("/watches/{watch_id}/logs")
async def logs_for_watch(
    watch_id: int, limit: int = 200, db: AsyncSession = Depends(get_db)
):
    q = (
        select(CheckLog)
        .where(CheckLog.watch_id == watch_id)
        .order_by(CheckLog.checked_at.desc())
        .limit(limit)
    )
    res = await db.execute(q)
    items: List[CheckLog] = list(res.scalars())
    return [
        {
            "checked_at": x.checked_at,
            "last_modified": x.last_modified,
            "status": x.status.value,
            "lag_minutes": x.lag_minutes,
            "message": x.message,
            "consec_ok": x.consec_ok,
            "consec_missing": x.consec_missing,
        }
        for x in items
    ]


# ---------------- Download ----------------
@app.get("/download/{watch_id}")
async def download_watch(watch_id: int, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Watch).where(Watch.id == watch_id))
    w = res.scalar_one_or_none()
    if not w:
        raise HTTPException(status_code=404, detail="Watch not found")

    if _is_url_watch(w):
        return RedirectResponse(w.key)  # key holds the URL

    key_esc = quote(w.key, safe="/")
    # If bucket is public (unsigned), direct link works:
    if settings.S3_UNSIGNED:
        url = f"https://{w.bucket}.s3.amazonaws.com/{key_esc}"
        return RedirectResponse(url)

    # Otherwise try a short-lived presigned URL; fall back to direct link.
    try:
        client = boto3.client("s3")
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": w.bucket, "Key": w.key},
            ExpiresIn=300,
        )
        return RedirectResponse(url)
    except Exception:
        url = f"https://{w.bucket}.s3.amazonaws.com/{key_esc}"
        return RedirectResponse(url)


# ---------------- Dashboard (MATCH ORIGINAL) ----------------
DASH_TEMPLATE = r"""
<!doctype html>
<html lang="en"><head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FAST Availability Statistics</title>
  <style>
    :root{
      /* FAST palette */
      --navy:#153a57;           /* top bar */
      --hero:#6b7280;           /* gray hero band */
      --bg:#eef1f4;             /* page bg */
      --card:#ffffff;           /* card bg */
      --text:#1f2937;           /* base text */
      --muted:#6b7280;          /* muted text */
      --shadow:0 6px 20px rgba(0,0,0,.12);

      /* status colors */
      --ok:#2ecc71;
      --warn:#f1c40f;
      --miss:#e74c3c;
      --err:#8e44ad;
      --none:#9ca3af;
    }

    /* Layout */
    html,body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,sans-serif;}
    .topbar{background:var(--navy);color:#fff;}
    .topbar .inner{max-width:1200px;margin:0 auto;padding:10px 16px;font-weight:600;letter-spacing:.2px;}
    .hero{background:var(--hero);color:#fff;}
    .hero .inner{max-width:1200px;margin:0 auto;padding:20px 16px;}

    /* Container width: cap at exactly 4 columns + gaps + side paddings
       card min width = 420px, gap = 16px, side padding = 16px each */
    .wrap{
      max-width: calc(4 * 420px + 3 * 16px + 32px);
      margin:16px auto 40px;
      padding:0 16px;
    }

    /* Auto-fit cards: only add a column when ≥420px is available */
    .grid{
      display:grid;
      grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
      gap:16px;
    }

    /* Headings */
    h1{margin:0 0 4px;font-size:28px;font-weight:800;line-height:1.1;}
    .asof{color:#e5e7eb;font-size:14px;}

    /* Cards */
    .card{background:var(--card);border-radius:12px;box-shadow:var(--shadow);padding:14px 16px;}
    .card-head{display:flex;align-items:center;gap:10px;justify-content:space-between;margin-bottom:6px;}
    .title{font-weight:700;font-size:16px;line-height:1.25;}
    .sub{color:var(--muted);font-size:12px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;}
    .target{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
    .actions{display:flex;gap:8px;align-items:center;}
    .btn{background:#0d4a7a;color:#fff;border:none;border-radius:8px;padding:6px 10px;font-size:12px;text-decoration:none;display:inline-flex;align-items:center;gap:6px;box-shadow:0 2px 8px rgba(0,0,0,.12);}
    .btn:hover{filter:brightness(1.05);}
    .dot{width:9px;height:9px;border-radius:50%;display:inline-block;background:var(--ok);}
    /* Center the donut vertically in the middle card */
    .card.mid{ display:flex; flex-direction:column; }
    .card.mid .row{ flex:1; display:flex; align-items:center; justify-content:center; }
    .card.mid .kv{ margin-top:auto; } /* keep the outage block pinned below the donut */
    /* 90-day bar */
    .bar{display:flex;gap:2px;flex-wrap:wrap;margin-top:10px;}
    .cell{width:8px;height:14px;border-radius:2px;background:#d1d5db;}
    .ok{background:var(--ok);} .warn{background:var(--warn);} .miss{background:var(--miss);}
    .err{background:var(--err);} .none{background:var(--none);}

    /* Legend */
    .legend{display:flex;gap:14px;font-size:12px;color:var(--muted);margin-top:10px;flex-wrap:wrap;}
    .legend .ld{display:flex;align-items:center;gap:6px;}

    /* Tablet & down: force single column and shrink cells a bit */
    @media (max-width: 1024px){
      .grid{ grid-template-columns: 1fr; }
      .cell{ width:7px; height:13px; }
    }

    /* Narrow phones: tighter typography/cells */
    @media (max-width: 560px){
      h1{ font-size:22px; }
      .title{ font-size:15px; }
      .btn{ padding:6px 9px; }
      .cell{ width:6px; height:12px; }
      .card-head{ flex-direction:column; align-items:flex-start; gap:8px; }
      .sub{ font-size:11.5px; }
    }
  </style>
</head>
<body>
  <div class="topbar"><div class="inner">FAST - Flood Assessment System for TxDOT</div></div>
  <div class="hero">
    <div class="inner">
      <h1>FAST Availability Statistics</h1>
      <div class="asof">As of {{ now_utc }} UTC</div>
    </div>
  </div>

  <div class="wrap">
    <div class="grid">
      {% for item in rows %}
        <div class="card mid">
          <div class="card-head">
            <div class="title">{{ item.name }}</div>
            <div class="actions">
              <a class="btn" href="download/{{ item.id }}" title="Open this resource">Open</a>
            </div>
          </div>

          <div class="sub">
            <span><span class="dot"></span> {{ item.uptime_pct }}% uptime (last 90 days)</span>
            <span>• Current streak: {{ item.streak_label }}</span>
            <span class="target" title="{{ item.target }}">• {{ item.target }}</span>
          </div>

          <div class="bar" aria-label="90 day availability sparkline">
            {% for c in item.cells %}
              <div class="cell {{ c.cls }}" title="{{ c.title | e }}" aria-label="{{ c.title | e }}"></div>
            {% endfor %}
          </div>

          <div class="legend">
            <div class="ld"><span class="cell ok"></span> OK</div>
            <div class="ld"><span class="cell warn"></span> Some missing (&lt;10%)</div>
            <div class="ld"><span class="cell miss"></span> Missing (≥10%)</div>
            <div class="ld"><span class="cell err"></span> Error</div>
            <div class="ld"><span class="cell none"></span> No checks</div>
          </div>
        </div>
      {% endfor %}
    </div>
  </div>
</body></html>
"""

STATS_DASH_TEMPLATE = r"""
<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>FAST Availability Statistics</title>
<style>
  :root{
    --navy:#153a57; --hero:#6b7280; --bg:#eef1f4; --card:#ffffff;
    --text:#1f2937; --muted:#6b7280; --shadow:0 6px 20px rgba(0,0,0,.12);
  }
  html,body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,sans-serif;}
  .topbar{background:var(--navy);color:#fff;}
  .topbar .inner{max-width:1200px;margin:0 auto;padding:10px 16px;font-weight:600;letter-spacing:.2px;}
  .hero{background:var(--hero);color:#fff;}
  .hero .inner{max-width:1200px;margin:0 auto;padding:20px 16px;}
  h1{margin:0 0 6px;font-size:26px;font-weight:800;}
  .range{color:#e5e7eb;font-size:14px;}
  .wrap{max-width:1200px;margin:16px auto 40px; padding:0 16px;}

  .cols{display:grid;grid-template-columns:1fr 1fr 1fr; gap:16px;}
  .card{background:var(--card);border-radius:12px;box-shadow:var(--shadow);padding:16px;}
  .card h2{margin:0 0 10px;font-size:18px;}
  .row{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start;}
  .ring{display:flex;flex-direction:column;align-items:center;gap:6px;min-width:160px;}
  .ring label{font-size:12px;color:var(--muted);text-align:center;max-width:200px}
  .kv{margin-top:10px;font-size:13px;color:var(--text);}
  .kv div{margin:2px 0;}
    /* Center the donut vertically in the middle card */
    .card.mid{ display:flex; flex-direction:column; }
    .card.mid .row{ flex:1; display:flex; align-items:center; justify-content:center; }
    .card.mid .kv{ margin-top:auto; } /* keep the outage block pinned below the donut */

  /* Notes card */
  .notes{margin-top:16px;}
  .notes .notehead{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;}
  .notes .actions{display:flex;gap:8px;flex-wrap:wrap;}
  .btn{background:#0d4a7a;color:#fff;border:none;border-radius:8px;padding:6px 10px;font-size:12px;text-decoration:none;display:inline-flex;align-items:center;gap:6px;box-shadow:0 2px 8px rgba(0,0,0,.12);cursor:pointer;}
  .btn.secondary{background:#6b7280;}
  .btn:hover{filter:brightness(1.05);}
  #notesBox{min-height:110px; border:1px solid #e5e7eb; border-radius:10px; padding:10px; background:#fff;}
  #notesBox:focus{outline:2px solid #93c5fd; outline-offset:2px;}

  @media (max-width: 1024px){ .cols{grid-template-columns:1fr;} .ring{min-width:140px;} }
</style>
</head>
<body>
  <div class="topbar"><div class="inner">FAST - Flood Assessment System for TxDOT</div></div>
  <div class="hero">
    <div class="inner">
      <h1>FAST Availability Statistics</h1>
      <div class="range">From: {{ from_str }} &nbsp; to: {{ to_str }} &nbsp; • Duration: {{ duration_days }} days</div>
    </div>
  </div>

  <div class="wrap">
    <div class="cols">
      <!-- LEFT: FAST Web App (URLs) -->
      <div class="card">
        <h2>FAST Web App (Frontend)</h2>
        <div class="row">
          {% for u in urls %}
            <div class="ring">
              {{ u.donut | safe }}
              <label>{{ u.label }}</label>
            </div>
          {% endfor %}
        </div>
        <div class="kv">
          <div><b>Longest outage:</b> {{ urls_meta.max_outage }}</div>
          <div><b>Total outage:</b> {{ urls_meta.total_outage }}</div>
        </div>
      </div>

      <!-- MIDDLE: FAST Layer Generation (aggregate S3) -->
      <div class="card mid">
        <h2>FAST Layer Generation</h2>
        <div class="row">
          <div class="ring">
            {{ s3_agg.donut | safe }}
            <label>Aggregate of FAST layers</label>
          </div>
        </div>
        <div class="kv">
          <div><b>Max continuous outage:</b> {{ s3_agg.max_outage }}</div>
          <div><b>Total outage:</b> {{ s3_agg.total_outage }}</div>
          <div><b>Min age:</b> {{ s3_agg.min_age }} &nbsp; <b>Max age:</b> {{ s3_agg.max_age }} &nbsp; <b>Avg age:</b> {{ s3_agg.avg_age }}</div>
        </div>
      </div>

      <!-- RIGHT: Data Assimilation (two key layers) -->
      <div class="card">
        <h2>Data Assimilation</h2>
        <div class="row">
          {% for d in da_layers %}
            <div class="ring">
              {{ d.donut | safe }}
              <label>{{ d.label }}</label>
            </div>
          {% endfor %}
        </div>
        <div class="kv">
          <div><b>Max continuous outage:</b> {{ da_meta.max_outage }}</div>
          <div><b>Total outage:</b> {{ da_meta.total_outage }}</div>
          <div><b>Min age:</b> {{ da_meta.min_age }} &nbsp; <b>Max age:</b> {{ da_meta.max_age }} &nbsp; <b>Avg age:</b> {{ da_meta.avg_age }}</div>
        </div>
      </div>
    </div>

    <!-- Notes card -->
    <div class="card notes">
      <div class="notehead">
        <h2 style="margin:0">Notes</h2>
        <div class="actions">
          <button class="btn secondary" id="resetBtn" type="button">Reset</button>
          <button class="btn" id="copyBtn" type="button">Copy</button>
        </div>
      </div>
      <div id="notesBox" contenteditable="true" spellcheck="true"
           placeholder="Type your remarks here..."></div>
      <div style="margin-top:6px;color:var(--muted);font-size:12px;">
        Notes are saved locally in your browser for this time range.
      </div>
    </div>
  </div>

<script>
(function(){
  const key = "fast-notes::{{ range_key }}";
  const box = document.getElementById('notesBox');
  const copyBtn = document.getElementById('copyBtn');
  const resetBtn = document.getElementById('resetBtn');

  // initial content: prefer localStorage, else server-provided `notes_text`
  const stored = localStorage.getItem(key);
  box.innerText = stored !== null ? stored : ({{ notes_text | tojson | safe }} || "");

  let saveTimer = null;
  function scheduleSave(){
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      localStorage.setItem(key, box.innerText.trim());
    }, 300);
  }
  box.addEventListener('input', scheduleSave);
  box.addEventListener('blur', scheduleSave);

  copyBtn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(box.innerText.trim());
      copyBtn.textContent = "Copied!";
      setTimeout(()=>copyBtn.textContent="Copy", 1000);
    } catch(e) {}
  });

  resetBtn.addEventListener('click', () => {
    localStorage.removeItem(key);
    box.innerText = "";
  });
})();
</script>
</body></html>
"""


STATS_TREND_TEMPLATE = r"""
<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>FAST Availability — Trend</title>
<style>
  :root{ --navy:#153a57; --hero:#6b7280; --bg:#eef1f4; --card:#ffffff;
         --text:#1f2937; --muted:#6b7280; --shadow:0 6px 20px rgba(0,0,0,.12); }
  html,body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,sans-serif;}
  .topbar{background:var(--navy);color:#fff;}
  .topbar .inner{max-width:1200px;margin:0 auto;padding:10px 16px;font-weight:600;letter-spacing:.2px;}
  .hero{background:var(--hero);color:#fff;}
  .hero .inner{max-width:1200px;margin:0 auto;padding:20px 16px;}
  h1{margin:0 0 6px;font-size:26px;font-weight:800;}
  .range{color:#e5e7eb;font-size:14px;}
  .wrap{max-width:1200px;margin:16px auto 40px; padding:0 16px;}

  .cols{display:grid;grid-template-columns:1fr 1fr 1fr; gap:16px;}
  .card{background:var(--card);border-radius:12px;box-shadow:var(--shadow);padding:16px;}
  .card h2{margin:0 0 10px;font-size:18px;}
  .row{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start;}
  .ring{display:flex;flex-direction:column;align-items:center;gap:6px;min-width:160px;}
  .ring label{font-size:12px;color:var(--muted);text-align:center;max-width:200px}
  .kv{margin-top:10px;font-size:13px;color:var(--text);}
  .kv div{margin:4px 0;}
  .small{color:var(--muted);font-size:12px}

    /* Center the donut vertically in the middle card */
    .card.mid{ display:flex; flex-direction:column; }
    .card.mid .row{ flex:1; display:flex; align-items:center; justify-content:center; }
    .card.mid .kv{ margin-top:auto; } /* keep the outage block pinned below the donut */

  .metric{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .metric b{min-width:180px;display:inline-block;}
  .curr{font-weight:700;}
  .prev{color:var(--muted);}
  .arrow{display:inline-block;margin:0 4px;}
  @media (max-width: 1024px){ .cols{grid-template-columns:1fr;} .ring{min-width:140px;} }
</style>
</head>
<body>
  <div class="topbar"><div class="inner">FAST - Flood Assessment System for TxDOT</div></div>
  <div class="hero">
    <div class="inner">
      <h1>FAST Availability — Trend</h1>
      <div class="range">
        Current: {{ cur_from }} → {{ cur_to }} ({{ cur_days }} days)
        &nbsp; • &nbsp;
        Previous: {{ prev_from }} → {{ prev_to }} ({{ prev_days }} days)
      </div>
      <div class="small">Arrows compare current vs previous (▲/▼). Uptime: higher is better. Outages/Ages: lower is better.</div>
    </div>
  </div>

  <div class="wrap">
    <div class="cols">
      <!-- LEFT: URLs -->
      <div class="card">
        <h2>FAST Web App (Frontend)</h2>
        <div class="row">
          {% for u in urls %}
            <div class="ring">
              {{ u.donut | safe }}
              <label>{{ u.label }}</label>
              <div class="small">
                <span class="curr">{{ u.curr_uptime }}</span>
                <span class="arrow">{{ u.uptime_arrow | safe }}</span>
                <span class="prev">{{ u.prev_uptime }}</span>
              </div>
            </div>
          {% endfor %}
        </div>
        <div class="kv">
          <div class="metric">
            <b>Longest outage:</b>
            <span class="curr">{{ urls_meta.max_outage }}</span>
            <span class="arrow">{{ urls_meta.max_outage_arrow | safe }}</span>
            <span class="prev">{{ urls_meta.max_outage_prev }}</span>
          </div>
          <div class="metric">
            <b>Total outage:</b>
            <span class="curr">{{ urls_meta.total_outage }}</span>
            <span class="arrow">{{ urls_meta.total_outage_arrow | safe }}</span>
            <span class="prev">{{ urls_meta.total_outage_prev }}</span>
          </div>
        </div>
      </div>

      <!-- MIDDLE: S3 aggregate -->
      <div class="card mid">
        <h2>FAST Layer Generation</h2>
        <div class="row">
          <div class="ring">
            {{ s3_agg.donut | safe }}
            <label>Aggregate of FAST layers</label>
            <div class="small">
              <span class="curr">{{ s3_agg.curr_uptime }}</span>
              <span class="arrow">{{ s3_agg.uptime_arrow | safe }}</span>
              <span class="prev">{{ s3_agg.prev_uptime }}</span>
            </div>
          </div>
        </div>
        <div class="kv">
          <div class="metric">
            <b>Max continuous outage:</b>
            <span class="curr">{{ s3_agg.max_outage }}</span>
            <span class="arrow">{{ s3_agg.max_outage_arrow | safe }}</span>
            <span class="prev">{{ s3_agg.max_outage_prev }}</span>
          </div>
          <div class="metric">
            <b>Total outage:</b>
            <span class="curr">{{ s3_agg.total_outage }}</span>
            <span class="arrow">{{ s3_agg.total_outage_arrow | safe }}</span>
            <span class="prev">{{ s3_agg.total_outage_prev }}</span>
          </div>
          <div class="metric">
            <b>Min age:</b>
            <span class="curr">{{ s3_agg.min_age }}</span>
            <span class="arrow">{{ s3_agg.min_age_arrow | safe }}</span>
            <span class="prev">{{ s3_agg.min_age_prev }}</span>
          </div>
          <div class="metric">
            <b>Max age:</b>
            <span class="curr">{{ s3_agg.max_age }}</span>
            <span class="arrow">{{ s3_agg.max_age_arrow | safe }}</span>
            <span class="prev">{{ s3_agg.max_age_prev }}</span>
          </div>
          <div class="metric">
            <b>Avg age:</b>
            <span class="curr">{{ s3_agg.avg_age }}</span>
            <span class="arrow">{{ s3_agg.avg_age_arrow | safe }}</span>
            <span class="prev">{{ s3_agg.avg_age_prev }}</span>
          </div>
        </div>
      </div>

      <!-- RIGHT: DA pair -->
      <div class="card">
        <h2>Data Assimilation</h2>
        <div class="row">
          {% for d in da_layers %}
            <div class="ring">
              {{ d.donut | safe }}
              <label>{{ d.label }}</label>
              <div class="small">
                <span class="curr">{{ d.curr_uptime }}</span>
                <span class="arrow">{{ d.uptime_arrow | safe }}</span>
                <span class="prev">{{ d.prev_uptime }}</span>
              </div>
            </div>
          {% endfor %}
        </div>
        <div class="kv">
          <div class="metric">
            <b>Max continuous outage:</b>
            <span class="curr">{{ da_meta.max_outage }}</span>
            <span class="arrow">{{ da_meta.max_outage_arrow | safe }}</span>
            <span class="prev">{{ da_meta.max_outage_prev }}</span>
          </div>
          <div class="metric">
            <b>Total outage:</b>
            <span class="curr">{{ da_meta.total_outage }}</span>
            <span class="arrow">{{ da_meta.total_outage_arrow | safe }}</span>
            <span class="prev">{{ da_meta.total_outage_prev }}</span>
          </div>
          <div class="metric">
            <b>Min age:</b>
            <span class="curr">{{ da_meta.min_age }}</span>
            <span class="arrow">{{ da_meta.min_age_arrow | safe }}</span>
            <span class="prev">{{ da_meta.min_age_prev }}</span>
          </div>
          <div class="metric">
            <b>Max age:</b>
            <span class="curr">{{ da_meta.max_age }}</span>
            <span class="arrow">{{ da_meta.max_age_arrow | safe }}</span>
            <span class="prev">{{ da_meta.max_age_prev }}</span>
          </div>
          <div class="metric">
            <b>Avg age:</b>
            <span class="curr">{{ da_meta.avg_age }}</span>
            <span class="arrow">{{ da_meta.avg_age_arrow | safe }}</span>
            <span class="prev">{{ da_meta.avg_age_prev }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</body></html>
"""


env = Environment(loader=BaseLoader(), autoescape=select_autoescape())


def summarize_day(day_date, day_logs):
    """
    Classification:
      - none: no checks that day (grey)
      - err: any errors that day (purple)
      - ok:  0% missing (green)
      - warn: 0 < missing% < 10% (yellow)
      - miss: missing% >= 10% (red)
    Tooltip shows counts and latest LastModified.
    """
    if not day_logs:
        return {"cls": "none", "title": f"{day_date.isoformat()} UTC — No checks"}

    n = len(day_logs)
    ok = sum(1 for l in day_logs if l.status == Status.ok)
    miss = sum(1 for l in day_logs if l.status == Status.missing)
    err = sum(1 for l in day_logs if l.status == Status.error)
    miss_rate = miss / n if n else 0.0

    if err > 0:
        cls, label = "err", "Error"
    elif miss == 0:
        cls, label = "ok", "OK"
    elif 0 < miss_rate < 0.10:
        cls, label = "warn", "Some missing (<10%)"
    else:
        cls, label = "miss", "Missing (≥10%)"

    lms = [lg.last_modified for lg in day_logs if lg.last_modified]
    lm_line = ""
    if lms:
        lm_latest = max(ensure_utc(x) for x in lms)
        lm_line = f"\nlast LastModified: {lm_latest.strftime('%H:%MZ')}"

    title = (
        f"{day_date.isoformat()} UTC — {label}\n"
        f"checks={n} | OK={ok}, Missing={miss}, Error={err}"
        f"{lm_line}"
    )
    return {"cls": cls, "title": title}


def pct_uptime(logs: List[CheckLog]) -> float:
    if not logs:
        return 0.0
    ok = sum(1 for l in logs if l.status == Status.ok)
    return round(100.0 * ok / len(logs), 3)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    # floor to midnight UTC for a clean 90-day window
    end_mid = now.replace(hour=0, minute=0, second=0, microsecond=0)  # today 00:00 UTC
    start_mid = end_mid - timedelta(days=89)  # 90 days inclusive

    res = await db.execute(select(Watch).order_by(Watch.id))
    watches: List[Watch] = list(res.scalars())

    rows = []
    for w in watches:
        q = (
            select(CheckLog)
            .where(CheckLog.watch_id == w.id, CheckLog.checked_at >= start_mid)
            .order_by(CheckLog.checked_at.asc())
        )
        rs = await db.execute(q)
        logs_all = list(rs.scalars())

        # --- normalize & bucket by UTC calendar day ---
        buckets = {}  # {date: [CheckLog, ...]}
        for lg in logs_all:
            ca = ensure_utc(lg.checked_at)
            buckets.setdefault(ca.date(), []).append(lg)

        # most recent record for streak label
        last_q = (
            select(CheckLog)
            .where(CheckLog.watch_id == w.id)
            .order_by(CheckLog.checked_at.desc())
            .limit(1)
        )
        last_res = await db.execute(last_q)
        last = last_res.scalar_one_or_none()
        streak_label = (
            f"{last.consec_ok}× OK"
            if last and last.status == Status.ok
            else (
                f"{last.consec_missing}× MISSING"
                if last and last.status == Status.missing
                else "—"
            )
        )

        # render 90 cells (one per day)
        cells = []
        start_date = start_mid.date()
        for i in range(90):
            d = start_date + timedelta(days=i)
            day_logs = buckets.get(d, [])
            cells.append(summarize_day(d, day_logs))

        # color the row title based on TODAY's cell class
        name_cls = cells[-1]["cls"] if cells else "none"

        rows.append(
            {
                "id": w.id,
                "name": w.name,
                "name_cls": name_cls,
                "uptime_pct": pct_uptime(logs_all),
                "cells": cells,
                "streak_label": streak_label,
                "target": _display_target(w),
            }
        )

    template = env.from_string(DASH_TEMPLATE)
    html = template.render(now_utc=now.strftime("%Y-%m-%d %H:%M"), rows=rows)
    return HTMLResponse(html)


@app.get("/stats")
async def stats_endpoint(
    from_param: Optional[str] = Query(None, alias="from"),
    to_param: Optional[str] = Query(None, alias="to"),
    period: Optional[str] = Query(None),
    fmt: str = Query("json", pattern="^(json|csv)$"),
    db: AsyncSession = Depends(get_db),
):
    start, end = _resolve_range(from_param, to_param, period)
    if end <= start:
        raise HTTPException(400, "'to' must be after 'from'")

    # Fetch watches first
    res_w = await db.execute(select(Watch).order_by(Watch.id))
    watches = list(res_w.scalars())

    if not watches:
        data = []
        return (
            JSONResponse(data)
            if fmt == "json"
            else PlainTextResponse("", media_type="text/csv")
        )

    watch_by_id = {w.id: w for w in watches}
    watch_ids = [w.id for w in watches]

    # Pull all logs in window in one query, then bucket in Python
    q = (
        select(CheckLog)
        .where(
            CheckLog.watch_id.in_(watch_ids),
            CheckLog.checked_at >= start,
            CheckLog.checked_at < end,
        )
        .order_by(CheckLog.watch_id.asc(), CheckLog.checked_at.asc())
    )
    res_logs = await db.execute(q)
    logs = list(res_logs.scalars())

    # Bucket by watch_id
    buckets: dict[int, list[CheckLog]] = {}
    for lg in logs:
        buckets.setdefault(lg.watch_id, []).append(lg)

    rows = []
    scan_minutes = settings.SCAN_INTERVAL_SECONDS / 60.0

    for w in watches:
        items = buckets.get(w.id, [])

        # Counts
        n_ok = sum(1 for x in items if x.status == Status.ok)
        n_miss = sum(1 for x in items if x.status == Status.missing)
        n_err = sum(1 for x in items if x.status == Status.error)
        total = n_ok + n_miss + n_err
        uptime = (100.0 * n_ok / total) if total > 0 else 0.0

        # Streaks of missing (to get max consecutive and outages)
        max_consec_miss = 0
        total_outage_mins = 0.0
        max_outage_mins = 0.0

        current_streak = 0
        for x in items:
            if x.status == Status.missing:
                current_streak += 1
            else:
                if current_streak > 0:
                    outage = current_streak * scan_minutes
                    total_outage_mins += outage
                    if outage > max_outage_mins:
                        max_outage_mins = outage
                    if current_streak > max_consec_miss:
                        max_consec_miss = current_streak
                    current_streak = 0
        # tail streak (if window ends on missing)
        if current_streak > 0:
            outage = current_streak * scan_minutes
            total_outage_mins += outage
            if outage > max_outage_mins:
                max_outage_mins = outage
            if current_streak > max_consec_miss:
                max_consec_miss = current_streak

        # Ages for S3 only
        is_url = w.bucket == URL_SENTINEL_BUCKET
        s3_ages = [
            x.lag_minutes for x in items if (not is_url and x.lag_minutes is not None)
        ]
        min_age = min(s3_ages) if s3_ages else None
        max_age = max(s3_ages) if s3_ages else None
        avg_age = mean(s3_ages) if s3_ages else None

        # URL column: actual URL for URL sentinel, s3:// for S3
        url_col = w.key if is_url else f"s3://{w.bucket}/{w.key}"
        type_col = "url" if is_url else "s3"

        rows.append(
            {
                "watch_id": w.id,
                "watch_name": w.name,
                "url": url_col,
                "type": type_col,
                "uptime_perc(%)": round(uptime, 3),
                "max consecutive misses": max_consec_miss,
                "max outage (mins)": round(max_outage_mins, 3),
                "total outage (mins)": round(total_outage_mins, 3),
                "n_success": n_ok,
                "n_misses": n_miss,
                "n_error": n_err,
                "min_age (s3)": (round(min_age, 3) if min_age is not None else None),
                "max_age (s3)": (round(max_age, 3) if max_age is not None else None),
                "avg_age (s3)": (round(avg_age, 3) if avg_age is not None else None),
            }
        )

    if fmt == "json":
        return JSONResponse(rows)

    # CSV
    fieldnames = [
        "watch_id",
        "watch_name",
        "url",
        "type",
        "uptime_perc(%)",
        "max consecutive misses",
        "max outage (mins)",
        "total outage (mins)",
        "n_success",
        "n_misses",
        "n_error",
        "min_age (s3)",
        "max_age (s3)",
        "avg_age (s3)",
    ]
    buf = io.StringIO()
    wcsv = csv.DictWriter(buf, fieldnames=fieldnames)
    wcsv.writeheader()
    for r in rows:
        wcsv.writerow(r)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


@app.get("/stats/dashboard", response_class=HTMLResponse)
async def stats_dashboard(
    from_param: Optional[str] = Query(None, alias="from"),
    to_param: Optional[str] = Query(None, alias="to"),
    period: Optional[str] = Query(None),
    notes: str = Query("", alias="notes"),
    db: AsyncSession = Depends(get_db),
):
    start, end = _resolve_range(from_param, to_param, period)
    if end <= start:
        raise HTTPException(400, "'to' must be after 'from'")

    rows = await _compute_rows(db, start, end)

    # --- Grouping rules ---
    # URLs: pick the two URL watches (by name order)
    urls = [r for r in rows if r["type"] == "url"]
    urls = sorted(urls, key=lambda r: r["watch_name"])[:2]

    # DA “streamflow” & “gage layer” by filename (adjust if your names differ)
    is_streamflow = lambda r: r["type"] == "s3" and r["url"].endswith(
        "streamflow_kf_sr.nc"
    )
    is_gages = lambda r: r["type"] == "s3" and r["url"].endswith(
        "streamflow_gages.geojson"
    )
    da_items = [r for r in rows if is_streamflow(r) or is_gages(r)]

    # S3 aggregate for “FAST layers”: all other S3 items excluding the DA pair
    s3_fast_layers = [r for r in rows if r["type"] == "s3" and r not in da_items]

    # --- Build view models ---
    def agg_uptime(rs):
        if not rs:
            return 0.0
        ok = sum(1 for r in rs for _ in range(r["n_ok"]))  # number of OK samples
        total = sum(r["n_ok"] + r["n_miss"] + r["n_err"] for r in rs)
        return 100.0 * ok / total if total > 0 else 0.0

    def agg_max_outage(rs):
        return max((r["max_outage_mins"] for r in rs), default=0.0)

    def agg_total_outage(rs):
        return sum((r["total_outage_mins"] for r in rs), 0.0)

    def agg_age(rs, fn):
        vals = [
            r[k] for r in rs for k in [fn] if r[k] is not None
        ]  # flatten by picking field
        if not vals:
            return None
        if fn == "avg_age":
            return mean(vals)
        return min(vals) if fn == "min_age" else max(vals)

    # URLs (left)
    urls_vm = []
    for r in urls:
        color = _uptime_color(r["uptime"])
        urls_vm.append(
            {
                "label": r["watch_name"],
                "donut": _donut_svg(r["uptime"], color=color),
            }
        )
    urls_meta = {
        "max_outage": _fmt_minutes(agg_max_outage(urls)),
        "total_outage": _fmt_minutes(agg_total_outage(urls)),
    }

    # S3 aggregate (middle)
    s3_uptime = agg_uptime(s3_fast_layers)
    s3_vm = {
        "donut": _donut_svg(s3_uptime, color=_uptime_color(s3_uptime)),
        "max_outage": _fmt_minutes(agg_max_outage(s3_fast_layers)),
        "total_outage": _fmt_minutes(agg_total_outage(s3_fast_layers)),
        "min_age": _fmt_minutes(agg_age(s3_fast_layers, "min_age")),
        "max_age": _fmt_minutes(agg_age(s3_fast_layers, "max_age")),
        "avg_age": _fmt_minutes(agg_age(s3_fast_layers, "avg_age")),
    }

    # DA pair (right)
    da_vm = []
    for r in da_items:
        color = _uptime_color(r["uptime"])
        da_vm.append(
            {
                "label": r["watch_name"]
                .replace("Data Assimilation ", "")
                .replace("DA - ", "")
                .strip(),
                "donut": _donut_svg(r["uptime"], color=color),
            }
        )
    da_meta = {
        "max_outage": _fmt_minutes(agg_max_outage(da_items)),
        "total_outage": _fmt_minutes(agg_total_outage(da_items)),
        "min_age": _fmt_minutes(agg_age(da_items, "min_age")),
        "max_age": _fmt_minutes(agg_age(da_items, "max_age")),
        "avg_age": _fmt_minutes(agg_age(da_items, "avg_age")),
    }

    # Render
    template = env.from_string(STATS_DASH_TEMPLATE)
    html = template.render(
        from_str=start.strftime("%Y-%m-%d %H:%M"),
        to_str=end.strftime("%Y-%m-%d %H:%M"),
        duration_days=int((end - start).total_seconds() // 86400),
        urls=urls_vm,
        urls_meta=urls_meta,
        s3_agg=s3_vm,
        da_layers=da_vm,
        da_meta=da_meta,
        notes_text=notes,  # <— add this
        range_key=f"{start.isoformat()}__{end.isoformat()}",  # for localStorage key
    )
    return HTMLResponse(html)

@app.get("/stats/dashboard_trend", response_class=HTMLResponse)
async def stats_dashboard_trend(
    from_param: Optional[str] = Query(None, alias="from"),
    to_param: Optional[str] = Query(None, alias="to"),
    period: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    # Resolve current window from either (from,to) or period
    if period and (from_param is None and to_param is None):
        cur_end = datetime.now(timezone.utc)
        duration = _parse_period(period)
        cur_start = cur_end - duration
    else:
        cur_start, cur_end = _resolve_range(from_param, to_param, None)

    # previous period has the same duration immediately before cur_start
    duration = cur_end - cur_start
    prev_end = cur_start
    prev_start = prev_end - duration

    # compute rows for both periods
    rows_cur = await _compute_rows(db, cur_start, cur_end)
    rows_prev = await _compute_rows(db, prev_start, prev_end)

    # index previous by (type,url/name) to match easily
    def key_of(r):  # stable key
        return (r["type"], r["url"] if r["type"] == "url" else r["watch_name"])
    prev_map = {key_of(r): r for r in rows_prev}

    # ----- grouping predicates (same as your other dashboard) -----
    urls_cur = sorted([r for r in rows_cur if r["type"] == "url"], key=lambda r: r["watch_name"])[:2]
    is_streamflow = lambda r: r["type"] == "s3" and r["url"].endswith("streamflow_kf_sr.nc")
    is_gages = lambda r: r["type"] == "s3" and r["url"].endswith("streamflow_gages.geojson")
    da_cur = [r for r in rows_cur if is_streamflow(r) or is_gages(r)]
    s3_fast_cur = [r for r in rows_cur if r["type"] == "s3" and r not in da_cur]

    def agg_uptime(rs):
        if not rs: return 0.0
        total_ok = sum(r["n_ok"] for r in rs)
        total = sum(r["n_ok"] + r["n_miss"] + r["n_err"] for r in rs)
        return 100.0 * total_ok / total if total > 0 else 0.0
    def agg_max_outage(rs): return max((r["max_outage_mins"] for r in rs), default=0.0)
    def agg_total_outage(rs): return sum((r["total_outage_mins"] for r in rs), 0.0)
    def agg_age(rs, field):
        vals = [r[field] for r in rs if r[field] is not None]
        if not vals: return None
        from statistics import mean
        return mean(vals) if field == "avg_age" else (min(vals) if field=="min_age" else max(vals))

    # ----- URLs card -----
    urls_vm = []
    urls_prev = [prev_map.get(key_of(r)) for r in urls_cur]
    for cur, prv in zip(urls_cur, urls_prev):
        color = _uptime_color(cur["uptime"])
        prev_up = (prv["uptime"] if prv else None)
        urls_vm.append({
            "label": cur["watch_name"],
            "donut": _donut_svg(cur["uptime"], color=color),
            "curr_uptime": _pct_fmt(cur["uptime"]),
            "prev_uptime": _pct_fmt(prev_up),
            "uptime_arrow": _arrow(cur["uptime"], prev_up, higher_is_better=True),
        })
    # outages aggregate over both URL watches
    def wrap_out(v): return _fmt_minutes(v)
    urls_meta = {
        "max_outage": wrap_out(agg_max_outage(urls_cur)),
        "total_outage": wrap_out(agg_total_outage(urls_cur)),
    }
    prev_urls = [p for p in urls_prev if p]
    urls_meta["max_outage_prev"] = wrap_out(agg_max_outage(prev_urls))
    urls_meta["total_outage_prev"] = wrap_out(agg_total_outage(prev_urls))
    urls_meta["max_outage_arrow"]  = _arrow(agg_max_outage(urls_cur), agg_max_outage(prev_urls), higher_is_better=False)
    urls_meta["total_outage_arrow"] = _arrow(agg_total_outage(urls_cur), agg_total_outage(prev_urls), higher_is_better=False)

    # ----- S3 aggregate card -----
    s3_prev = [prev_map.get(key_of(r)) for r in s3_fast_cur if prev_map.get(key_of(r))]
    s3_uptime_cur = agg_uptime(s3_fast_cur)
    s3_uptime_prev = agg_uptime(s3_prev)
    s3_vm = {
        "donut": _donut_svg(s3_uptime_cur, color=_uptime_color(s3_uptime_cur)),
        "curr_uptime": _pct_fmt(s3_uptime_cur),
        "prev_uptime": _pct_fmt(s3_uptime_prev),
        "uptime_arrow": _arrow(s3_uptime_cur, s3_uptime_prev, higher_is_better=True),
        "max_outage": _fmt_minutes(agg_max_outage(s3_fast_cur)),
        "total_outage": _fmt_minutes(agg_total_outage(s3_fast_cur)),
        "min_age": _fmt_minutes(agg_age(s3_fast_cur, "min_age")),
        "max_age": _fmt_minutes(agg_age(s3_fast_cur, "max_age")),
        "avg_age": _fmt_minutes(agg_age(s3_fast_cur, "avg_age")),
        "max_outage_prev": _fmt_minutes(agg_max_outage(s3_prev)),
        "total_outage_prev": _fmt_minutes(agg_total_outage(s3_prev)),
        "min_age_prev": _fmt_minutes(agg_age(s3_prev, "min_age")),
        "max_age_prev": _fmt_minutes(agg_age(s3_prev, "max_age")),
        "avg_age_prev": _fmt_minutes(agg_age(s3_prev, "avg_age")),
        "max_outage_arrow": _arrow(agg_max_outage(s3_fast_cur), agg_max_outage(s3_prev), higher_is_better=False),
        "total_outage_arrow": _arrow(agg_total_outage(s3_fast_cur), agg_total_outage(s3_prev), higher_is_better=False),
        "min_age_arrow": _arrow(agg_age(s3_fast_cur, "min_age"), agg_age(s3_prev, "min_age"), higher_is_better=False),
        "max_age_arrow": _arrow(agg_age(s3_fast_cur, "max_age"), agg_age(s3_prev, "max_age"), higher_is_better=False),
        "avg_age_arrow": _arrow(agg_age(s3_fast_cur, "avg_age"), agg_age(s3_prev, "avg_age"), higher_is_better=False),
    }

    # ----- DA pair card -----
    da_prev = [prev_map.get(key_of(r)) for r in da_cur if prev_map.get(key_of(r))]
    da_vm = []
    for cur in da_cur:
        prv = prev_map.get(key_of(cur))
        color = _uptime_color(cur["uptime"])
        prev_up = (prv["uptime"] if prv else None)
        da_vm.append({
            "label": cur["watch_name"].replace("Data Assimilation ", "").replace("DA - ", "").strip(),
            "donut": _donut_svg(cur["uptime"], color=color),
            "curr_uptime": _pct_fmt(cur["uptime"]),
            "prev_uptime": _pct_fmt(prev_up),
            "uptime_arrow": _arrow(cur["uptime"], prev_up, higher_is_better=True),
        })
    def da_agg(rs):  # helper to aggregate DA pair
        return {
            "max_out": agg_max_outage(rs),
            "tot_out": agg_total_outage(rs),
            "min_age": agg_age(rs, "min_age"),
            "max_age": agg_age(rs, "max_age"),
            "avg_age": agg_age(rs, "avg_age"),
        }
    cur_da = da_agg(da_cur)
    prv_da = da_agg(da_prev)
    da_meta = {
        "max_outage": _fmt_minutes(cur_da["max_out"]),
        "total_outage": _fmt_minutes(cur_da["tot_out"]),
        "min_age": _fmt_minutes(cur_da["min_age"]),
        "max_age": _fmt_minutes(cur_da["max_age"]),
        "avg_age": _fmt_minutes(cur_da["avg_age"]),
        "max_outage_prev": _fmt_minutes(prv_da["max_out"]),
        "total_outage_prev": _fmt_minutes(prv_da["tot_out"]),
        "min_age_prev": _fmt_minutes(prv_da["min_age"]),
        "max_age_prev": _fmt_minutes(prv_da["max_age"]),
        "avg_age_prev": _fmt_minutes(prv_da["avg_age"]),
        "max_outage_arrow": _arrow(cur_da["max_out"], prv_da["max_out"], higher_is_better=False),
        "total_outage_arrow": _arrow(cur_da["tot_out"], prv_da["tot_out"], higher_is_better=False),
        "min_age_arrow": _arrow(cur_da["min_age"], prv_da["min_age"], higher_is_better=False),
        "max_age_arrow": _arrow(cur_da["max_age"], prv_da["max_age"], higher_is_better=False),
        "avg_age_arrow": _arrow(cur_da["avg_age"], prv_da["avg_age"], higher_is_better=False),
    }

    # Render
    template = env.from_string(STATS_TREND_TEMPLATE)
    html = template.render(
        cur_from=cur_start.strftime("%Y-%m-%d %H:%M"),
        cur_to=cur_end.strftime("%Y-%m-%d %H:%M"),
        prev_from=prev_start.strftime("%Y-%m-%d %H:%M"),
        prev_to=prev_end.strftime("%Y-%m-%d %H:%M"),
        cur_days=int(duration.total_seconds() // 86400),
        prev_days=int(duration.total_seconds() // 86400),
        urls=urls_vm, urls_meta=urls_meta,
        s3_agg=s3_vm,
        da_layers=da_vm, da_meta=da_meta,
    )
    return HTMLResponse(html)

# ---------------- Entrypoint ----------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("s3_watch:app", host="0.0.0.0", port=8000, reload=False)
