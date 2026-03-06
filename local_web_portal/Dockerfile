FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.base.txt
COPY local_web_portal/requirements.txt /app/requirements.web.txt
RUN pip install --no-cache-dir -r /app/requirements.base.txt -r /app/requirements.web.txt

COPY . /app

EXPOSE 8010

CMD ["uvicorn", "local_web_portal.app.main:app", "--host", "0.0.0.0", "--port", "8010", "--workers", "2"]

