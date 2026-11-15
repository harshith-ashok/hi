# whisper.cpp `whisper-server` (CPU). Builds from source; the model downloads on first start into /models.
FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ARG WHISPER_CPP_REF=v1.7.6
RUN git clone --depth 1 --branch ${WHISPER_CPP_REF} https://github.com/ggml-org/whisper.cpp /src
WORKDIR /src
RUN cmake -B build -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF \
    && cmake --build build --target whisper-server -j"$(nproc)"

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/bin/whisper-server /usr/local/bin/whisper-server
COPY entrypoint.sh /entrypoint.sh
ENV WHISPER_MODEL=base.en
EXPOSE 8080
ENTRYPOINT ["sh", "/entrypoint.sh"]
