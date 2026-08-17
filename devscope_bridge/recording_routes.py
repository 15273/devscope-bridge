"""POST /recordings/to-mp4 — WebM → MP4 for DevScope tab recordings."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from devscope_bridge.recording_transcode import webm_to_mp4

router = APIRouter(tags=["recordings"])


@router.post("/recordings/to-mp4")
async def recordings_to_mp4(file: UploadFile = File(...)) -> Response:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty body")
    try:
        mp4 = webm_to_mp4(data)
    except RuntimeError as exc:
        msg = str(exc)
        status = 413 if "too large" in msg else 503
        raise HTTPException(status_code=status, detail=msg) from exc
    return Response(
        content=mp4,
        media_type="video/mp4",
        headers={"Content-Disposition": 'attachment; filename="devscope-recording.mp4"'},
    )
