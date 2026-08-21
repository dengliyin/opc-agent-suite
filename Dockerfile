FROM public.ecr.aws/docker/library/node:22-bookworm-slim AS node-runtime

FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm AS service-base

ARG SYSTEM_PACKAGES=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=Asia/Shanghai

WORKDIR /workspace

RUN attempt=1; \
    sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true; \
    until apt-get -o Acquire::Retries=5 update \
        && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
            ca-certificates \
            curl \
            tini \
            ${SYSTEM_PACKAGES}; do \
        if [ "${attempt}" -ge 3 ]; then exit 1; fi; \
        attempt=$((attempt + 1)); \
    done \
    && rm -rf /var/lib/apt/lists/*

ARG INSTALL_PLAYWRIGHT=0
RUN python -m pip install --upgrade pip \
    && if [ "${INSTALL_PLAYWRIGHT}" = "1" ]; then \
        python -m pip install "playwright==1.60.0"; \
        attempt=1; \
        until python -m playwright install --with-deps chromium; do \
            if [ "${attempt}" -ge 3 ]; then exit 1; fi; \
            attempt=$((attempt + 1)); \
        done; \
       fi

ARG SERVICE_DIR
ARG EXTRA_REQUIREMENTS=""
COPY . /workspace

RUN test -n "${SERVICE_DIR}" \
    && python -m pip install -r "/workspace/${SERVICE_DIR}/requirements.lock.txt" \
    && for requirements in ${EXTRA_REQUIREMENTS}; do \
        python -m pip install -r "/workspace/${requirements}/requirements.lock.txt"; \
       done

ENTRYPOINT ["/usr/bin/tini", "--"]

FROM service-base AS hyperframes

ARG HYPERFRAMES_VERSION=0.7.44

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install --global "hyperframes@${HYPERFRAMES_VERSION}" \
    && browser_path="$(find /ms-playwright -type f -path '*/chrome-linux*/chrome' -print -quit)" \
    && test -n "${browser_path}" \
    && ln -s "${browser_path}" /usr/local/bin/hyperframes-chrome \
    && node --version \
    && hyperframes --version \
    && ffmpeg -version >/dev/null \
    && /usr/local/bin/hyperframes-chrome --version \
    && npm cache clean --force

ENV VIDEO_ASSEMBLY_HYPERFRAMES=/usr/local/bin/hyperframes \
    HYPERFRAMES_BROWSER_PATH=/usr/local/bin/hyperframes-chrome \
    HYPERFRAMES_NO_UPDATE_CHECK=1 \
    HYPERFRAMES_NO_AUTO_INSTALL=1 \
    HYPERFRAMES_NO_TELEMETRY=1

FROM service-base AS service
