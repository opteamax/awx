FROM python:3.11-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
      libldap2-dev libsasl2-dev libxmlsec1-dev libxmlsec1-openssl pkg-config \
      libpq-dev libkrb5-dev git gcc g++ make swig rsync curl \
    && rm -rf /var/lib/apt/lists/*
RUN git config --global --add safe.directory '*'
