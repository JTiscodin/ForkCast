# Hugging Face Docker Space for the Forkcast API.
# Space repo layout: this Dockerfile + README.md at the root, plus the backend/ folder.
FROM python:3.11-slim

# HF runs the container as uid 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user backend/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
COPY --chown=user backend/ .
# never ship local secrets or the local DB; Space secrets arrive as env vars
RUN rm -f .env mealplanner.db

EXPOSE 7860
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
