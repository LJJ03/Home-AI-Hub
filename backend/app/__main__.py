"""Command-line entry point for the backend service."""

import uvicorn

from app.core.config import get_settings
from app.core.logging import configure_logging


def main() -> None:
    """Start the Uvicorn server using validated application settings."""

    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=True,
    )


if __name__ == "__main__":
    main()

