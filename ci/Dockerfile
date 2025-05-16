FROM 857556598075.dkr.ecr.us-west-1.amazonaws.com/plivo/app/base/python:3.12-bullseye AS base

USER root

WORKDIR /app

COPY requirements.txt .

RUN pip install uv==0.4.25

RUN uv venv && \
    uv pip install --no-cache -r requirements.txt

COPY . .

USER plivo

FROM 857556598075.dkr.ecr.us-west-1.amazonaws.com/plivo/app/base/python:3.12-slim-bullseye AS final

ENV HOME=/home/plivo \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/home/plivo/src:$PYTHONPATH"

WORKDIR ${HOME}

USER root

RUN apt-get update && \
    apt-get install --no-install-recommends -y curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY --chown=plivo:plivo --from=base /app/.venv /app/.venv
COPY --chown=plivo:plivo . .

EXPOSE 8000

USER plivo

ENTRYPOINT ["/bin/bash", "./ci/entrypoint.sh"]
