FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY orion ./orion
RUN mkdir -p /app/data && chown 10001:10001 /app/data
USER 10001:10001
CMD ["python", "-m", "orion"]
