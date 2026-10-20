FROM python:3.12-slim
WORKDIR /app
COPY communities.json taxonomy.json ./
COPY app/*.py ./app/
COPY app/static ./app/static/
ENV PYTHONUNBUFFERED=1 CNVRTED_DATA_DIR=/data
EXPOSE 8080
CMD ["python", "app/server.py"]
