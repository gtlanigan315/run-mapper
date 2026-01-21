
"""FastAPI application entry point for Run Mapper."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from run_mapper import __version__
from run_mapper.api.routes import router
from run_mapper.api.strava import router as strava_router

app = FastAPI(
    title="Run Mapper",
    description="Find comparable running routes based on elevation profiles",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS for web clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api/v1", tags=["routes"])
app.include_router(strava_router, prefix="/api/v1", tags=["strava"])


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Run Mapper API",
        "version": __version__,
        "docs": "/docs",
    }
