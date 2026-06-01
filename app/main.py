from fastapi import FastAPI
from contextlib import asynccontextmanager
import structlog
import uvicorn

from api.routes import router
from app.scheduler import start_scheduler

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    logger.info("Starting Namekart AI Agents service")
    start_scheduler()
    yield
    # Shutdown actions
    logger.info("Shutting down")

app = FastAPI(title="Namekart AI Agents", lifespan=lifespan)

app.include_router(router)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
