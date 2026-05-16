"""
Package entry-point
===================
"""

import uvicorn

from controller import create_app
from controller.utilities.config import get_settings


def main() -> None:
    """Create the FastAPI app and run it via Uvicorn."""

    settings = get_settings()
    app = create_app(settings)
    uvicorn.run(
        app,
        host='0.0.0.0',
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips='*',
    )


if __name__ == '__main__':
    main()
