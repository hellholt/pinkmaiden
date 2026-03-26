"""
Image labeling UI for keep/reject classification.

Run:
    uvicorn app:app --host 0.0.0.0 --port 8642

Environment:
    IMAGE_DIR  — root of the sharded image directory (e.g. /mnt/nas/images)
    DB_PATH    — path to SQLite database (default: labels.db)
    BATCH_SIZE — images per page (default: 100)
    THUMB_SIZE — max thumbnail dimension in pixels (default: 256)
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, Response
from PIL import Image

log = logging.getLogger(__name__)

IMAGE_DIR = Path(os.environ.get("IMAGE_DIR", "/mnt/nas/images"))
DB_PATH = os.environ.get("DB_PATH", "labels.db")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "100"))
THUMB_SIZE = int(os.environ.get("THUMB_SIZE", "256"))

app = FastAPI()


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS labels (
                image_path TEXT PRIMARY KEY,
                label TEXT NOT NULL CHECK(label IN ('keep', 'reject')),
                labeled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS image_index (
                image_path TEXT PRIMARY KEY
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_labels_label ON labels(label)
        """)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def build_image_index():
    """Scan IMAGE_DIR and populate the image_index table. Runs once on startup."""
    extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    log.info("Building image index from %s ...", IMAGE_DIR)
    count = 0
    with get_db() as db:
        existing = db.execute("SELECT COUNT(*) as c FROM image_index").fetchone()["c"]
        if existing > 0:
            log.info("Image index already has %d entries, skipping scan. "
                     "Delete labels.db or the image_index table to re-scan.", existing)
            return existing
        batch = []
        for path in IMAGE_DIR.rglob("*"):
            if path.suffix.lower() in extensions and path.is_file():
                batch.append((str(path.relative_to(IMAGE_DIR)),))
                count += 1
                if len(batch) >= 5000:
                    db.executemany("INSERT OR IGNORE INTO image_index (image_path) VALUES (?)", batch)
                    batch.clear()
                    if count % 50000 == 0:
                        log.info("  indexed %d images...", count)
        if batch:
            db.executemany("INSERT OR IGNORE INTO image_index (image_path) VALUES (?)", batch)
    log.info("Indexed %d images.", count)
    return count


def get_unlabeled_images(offset: int = 0, limit: int = BATCH_SIZE):
    """Return a batch of unlabeled images using the pre-built index."""
    with get_db() as db:
        rows = db.execute("""
            SELECT i.image_path FROM image_index i
            LEFT JOIN labels l ON i.image_path = l.image_path
            WHERE l.image_path IS NULL
            ORDER BY i.image_path
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()
    return [r["image_path"] for r in rows]


@app.on_event("startup")
def startup():
    init_db()
    build_image_index()


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html_path.read_text())


@app.get("/api/batch")
def get_batch(offset: int = Query(0, ge=0), limit: int = Query(BATCH_SIZE, ge=1, le=500)):
    """Get a batch of unlabeled images."""
    images = get_unlabeled_images(offset=offset, limit=limit)
    with get_db() as db:
        total_indexed = db.execute("SELECT COUNT(*) as c FROM image_index").fetchone()["c"]
        total_labeled = db.execute("SELECT COUNT(*) as c FROM labels").fetchone()["c"]
        total_rejected = db.execute("SELECT COUNT(*) as c FROM labels WHERE label = 'reject'").fetchone()["c"]
    return {
        "images": images,
        "count": len(images),
        "stats": {
            "total": total_indexed,
            "labeled": total_labeled,
            "rejected": total_rejected,
            "kept": total_labeled - total_rejected,
            "remaining": total_indexed - total_labeled,
        },
    }


@app.post("/api/label")
async def submit_labels(payload: dict):
    """
    Submit labels for a batch.
    Expects: {"rejected": ["path1", "path2", ...], "all": ["path1", "path2", ...]}
    Everything in 'all' not in 'rejected' is labeled 'keep'.
    """
    rejected = set(payload.get("rejected", []))
    all_images = payload.get("all", [])
    if not all_images:
        raise HTTPException(status_code=400, detail="No images in batch")

    with get_db() as db:
        for img_path in all_images:
            label = "reject" if img_path in rejected else "keep"
            db.execute(
                "INSERT OR REPLACE INTO labels (image_path, label) VALUES (?, ?)",
                (img_path, label),
            )

    return {"labeled": len(all_images), "rejected": len(rejected), "kept": len(all_images) - len(rejected)}


@app.get("/api/stats")
def get_stats():
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) as c FROM labels").fetchone()["c"]
        rejected = db.execute("SELECT COUNT(*) as c FROM labels WHERE label = 'reject'").fetchone()["c"]
    return {"labeled": total, "rejected": rejected, "kept": total - rejected}


@app.get("/api/export")
def export_labels():
    """Export all labels as JSON for use in training."""
    with get_db() as db:
        rows = db.execute("SELECT image_path, label, labeled_at FROM labels ORDER BY labeled_at").fetchall()
    return [{"path": r["image_path"], "label": r["label"], "labeled_at": r["labeled_at"]} for r in rows]


@app.get("/img/{path:path}")
def serve_image(path: str, thumb: bool = Query(True)):
    """Serve an image, optionally as a thumbnail."""
    full_path = IMAGE_DIR / path
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    # Security: prevent path traversal
    try:
        full_path.resolve().relative_to(IMAGE_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if thumb:
        try:
            img = Image.open(full_path)
            img.thumbnail((THUMB_SIZE, THUMB_SIZE))
            buf = BytesIO()
            fmt = "JPEG" if full_path.suffix.lower() in (".jpg", ".jpeg") else "PNG"
            img.save(buf, format=fmt, quality=80)
            buf.seek(0)
            content_type = "image/jpeg" if fmt == "JPEG" else "image/png"
            return Response(content=buf.getvalue(), media_type=content_type)
        except Exception:
            pass

    return Response(content=full_path.read_bytes(), media_type="image/jpeg")
