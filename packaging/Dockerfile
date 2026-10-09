# GitHub Packages distribution bundle. Install the archive on the Linux host.
FROM scratch
ARG VERSION
ARG REVISION
ARG SOURCE_URL
LABEL org.opencontainers.image.title="Zapret Manager release files" \
      org.opencontainers.image.description="Python packages and complete Linux installer source archive in /packages" \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$REVISION \
      org.opencontainers.image.source=$SOURCE_URL \
      org.opencontainers.image.licenses="MIT"
COPY dist/ /packages/
