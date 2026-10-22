FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip setuptools wheel
# Install dependencies using CPU index url for light-weight PyTorch build
RUN pip install --no-cache-dir -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

COPY . /app

# Whitenoise serves the compiled/manifest static files, so collect them at build
# time (without this the app ships with no CSS, JS or map assets).
RUN python manage.py collectstatic --noinput

CMD ["gunicorn", "agri_dashboard.wsgi:application", "--bind", "0.0.0.0:8000"]
