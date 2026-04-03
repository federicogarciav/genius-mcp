import logging
import os
import uvicorn
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware

from app import mcp

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

if __name__ == "__main__":
    if os.getenv("STREAMABLE_HTTP", "true").lower() == "true":
        starlette_app = mcp.http_app(transport="streamable-http", stateless_http=True)
        app = CORSMiddleware(
            starlette_app,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        uvicorn.run(app, host="127.0.0.1", port=8080)
    else:
        mcp.run()
