"""Stream current manuscripts and isolate each ZIP download from other requests."""

from pathlib import Path
import os
import tempfile
import zipfile

from fastapi import HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from utils.artifacts import latest_chapter_files


def output_download_response(run_dir: Path | None, output_path: str, filename: str):
    files = latest_chapter_files(run_dir) if run_dir else []
    if files:

        def chunks():
            for number, path in enumerate(files):
                if number:
                    yield b"\n\n"
                with path.open("rb") as stream:
                    while data := stream.read(65536):
                        yield data

        return StreamingResponse(
            chunks(),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    if output_path and Path(output_path).is_file():
        return FileResponse(
            output_path, media_type="text/plain; charset=utf-8", filename=filename
        )
    raise HTTPException(status_code=404, detail="No output available yet")


def chapters_archive_response(run_dir: Path, job_id: int):
    files = latest_chapter_files(run_dir)
    if not files:
        raise HTTPException(status_code=404, detail="No chapter output available yet")
    descriptor, name = tempfile.mkstemp(prefix=".download_", suffix=".zip", dir=run_dir)
    archive = Path(name)
    try:
        with os.fdopen(descriptor, "w+b") as stream:
            with zipfile.ZipFile(
                stream, "w", compression=zipfile.ZIP_DEFLATED
            ) as zipped:
                for path in files:
                    zipped.write(path, arcname=path.name)
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=f"job_{job_id}_chapters_latest.zip",
        background=BackgroundTask(archive.unlink, missing_ok=True),
    )
