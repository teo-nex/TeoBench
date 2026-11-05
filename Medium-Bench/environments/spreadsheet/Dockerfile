FROM python@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-calc python3-uno python3-openpyxl python3-tqdm && mkdir -p /opt/teobench && dpkg-query -W > /opt/teobench/dpkg-lock.tsv && rm -rf /var/lib/apt/lists/*
RUN /usr/local/bin/python3 -m pip install --no-cache-dir openpyxl==3.1.5 tqdm==4.67.1
ENV PATH=/usr/local/bin:/usr/bin:/bin
WORKDIR /app
