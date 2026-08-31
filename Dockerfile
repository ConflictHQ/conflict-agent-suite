# Stdlib only -- an agent that needed a model endpoint to answer would cost
# money to idle and fail for reasons unrelated to what is being demonstrated.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY agent.py ./
RUN useradd --create-home --uid 10001 astro && chown -R astro:astro /app
USER astro
CMD ["python", "agent.py"]
