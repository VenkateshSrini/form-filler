from __future__ import annotations

import os
from pathlib import Path

import uvicorn
import gradio as gr
from fastapi import FastAPI
from dotenv import load_dotenv

from app import INPUT_FORMS_DIR, build_app

# ── Constants ──────────────────────────────────────────────────────────────────
_HOST: str = os.getenv("APP_HOST", "127.0.0.1")
_PORT: int = int(os.getenv("APP_PORT", "7860"))
_GRADIO_MOUNT_PATH: str = "/"


def create_asgi_app() -> FastAPI:
    """
    Build the Gradio Blocks and mount it onto a FastAPI ASGI application.
    gr.mount_gradio_app returns the FastAPI instance — uvicorn serves it directly.
    No subprocess is used.
    """
    fastapi_app = FastAPI(
        title="PDF Form Filler",
        description="Local desktop web app for filling PDF forms.",
        version="1.0.0",
    )
    demo = build_app()
    gr.mount_gradio_app(fastapi_app, demo, path=_GRADIO_MOUNT_PATH)
    return fastapi_app


if __name__ == "__main__":
    # Load environment variables from .env if present
    load_dotenv()

    # Ensure required directories exist before the server starts
    INPUT_FORMS_DIR.mkdir(exist_ok=True)
    db_path = Path(os.getenv("DB_PATH", "./data/formfiller_db"))
    db_path.mkdir(parents=True, exist_ok=True)

    asgi_app = create_asgi_app()

    uvicorn.run(
        asgi_app,
        host=_HOST,
        port=_PORT,
        log_level="info",
    )
