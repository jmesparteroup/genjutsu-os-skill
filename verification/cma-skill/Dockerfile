FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg rubberband-cli python3 python3-venv ca-certificates && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/genjutsu
ENV PATH="/opt/genjutsu/bin:${PATH}"
RUN python -m pip install --no-cache-dir fal-client==1.0.3 numpy==2.2.6
COPY .claude/skills/genjutsu-fal-cma /opt/skill
COPY verification/cma-skill /opt/tests
WORKDIR /opt
