"""
FastAPI Web Chat Server for Rule-Based Swing Trading Engine.
Serves static cockpit UI and interactive command REST API.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .handlers import CommandHandler

logger = logging.getLogger(__name__)

handler = CommandHandler()
static_dir = Path(__file__).parent / "static"


async def auto_scan_background_worker():
    """Continuously runs the scan loop in the background every 30 minutes."""
    logger.info("Background auto-scanner started.")
    # Initial scan shortly after boot
    await asyncio.sleep(5)
    while True:
        try:
            logger.info("Running automated background market scan...")
            await asyncio.to_thread(handler.scheduler.run_daily_scan)
        except Exception as e:
            logger.error(f"Error in background auto-scanner: {e}")
        # Wait 30 minutes before next automatic scan cycle
        await asyncio.sleep(1800)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background auto-scan task on server startup
    scan_task = asyncio.create_task(auto_scan_background_worker())
    yield
    scan_task.cancel()


app = FastAPI(title="Swing Trading Signal Cockpit", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    command: str


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    try:
        reply = handler.handle(req.message)
        cmd = req.message.split()[0] if req.message.strip() else ""
        return ChatResponse(reply=reply, command=cmd)
    except Exception as e:
        logger.error(f"Error handling chat command: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/status")
async def status_endpoint():
    ks = handler.scheduler.kill_switch.get_status()
    return {
        "mode": handler.scheduler.config.mode,
        "live_trading": handler.scheduler.config.live_trading,
        "can_trade": ks.can_trade,
        "equity": ks.current_equity,
        "drawdown_pct": ks.drawdown_pct,
        "open_positions": len(handler.scheduler.paper_broker.open_positions),
    }


# Mount static assets
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"status": "Trading cockpit API active. Static UI not found."}
