FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y wget gzip && \
    wget https://github.com/ginuerzh/gost/releases/download/v2.11.5/gost-linux-amd64-2.11.5.gz && \
    gzip -d gost-linux-amd64-2.11.5.gz && \
    mv gost-linux-amd64-2.11.5 /usr/local/bin/gost && \
    chmod +x /usr/local/bin/gost && \
    rm -rf /var/lib/apt/lists/*
EXPOSE 8888
CMD ["gost", "-L", "mws://admin:123456@:8888"]
