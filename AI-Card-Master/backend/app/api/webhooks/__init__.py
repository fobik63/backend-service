"""External provider webhook routers."""

from app.api.webhooks.midjourney import router as midjourney_webhook_router

__all__ = ["midjourney_webhook_router"]
