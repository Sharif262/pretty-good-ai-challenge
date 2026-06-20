"""Start the FastAPI server for Twilio webhooks and ConversationRelay."""

import uvicorn

from src.settings import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "src.server:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
    )
