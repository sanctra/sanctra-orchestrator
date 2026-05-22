FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir uv && uv pip compile pyproject.toml -o requirements.txt && uv pip install --system -r requirements.txt
COPY app /app
EXPOSE 8080
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8080"]
