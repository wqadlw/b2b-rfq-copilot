# Backend image: uv-managed Python 3.12, src-layout package.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY backend/src ./backend/src

RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "uvicorn", "rfq_copilot.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
