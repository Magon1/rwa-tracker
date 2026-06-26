FROM python:3.13-slim
WORKDIR /app
COPY . /app
# stdlib-only app — no pip install needed
ENV PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
