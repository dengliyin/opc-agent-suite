FROM public.ecr.aws/docker/library/python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8788

CMD ["python", "-u", "-m", "opc_engine.features.script_adaptation.script_adaptation_agent_web", "--host", "0.0.0.0", "--port", "8788"]
