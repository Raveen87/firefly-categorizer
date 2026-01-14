import uvicorn

from firefly_categorizer.app import app
from firefly_categorizer.logger import get_logging_config

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=get_logging_config())
