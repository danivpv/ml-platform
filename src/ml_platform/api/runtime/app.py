"""
api/runtime/app.py
===================
FastAPI Catalog API app.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ml_platform.api.runtime.exceptions import CatalogException
from ml_platform.api.runtime.router import router

app = FastAPI(title="ML Platform Catalog API", version="2.0.0")

app.include_router(router)


@app.exception_handler(CatalogException)
async def catalog_exception_handler(request: Request, exc: CatalogException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message},
    )
