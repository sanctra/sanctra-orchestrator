FROM python:3.11-slim
WORKDIR /app
COPY app/pyproject.toml .
RUN pip install --no-cache-dir uv && uv pip install --system -r <(uv pip compile pyproject.toml)
COPY app /app
EXPOSE 8080
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8080"]
