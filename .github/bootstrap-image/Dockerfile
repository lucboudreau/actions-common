FROM one.hitachivantara.com/pnt-docker/jenkins-build/maven/open-jdk/17

ARG VERSION_MERGER=1.0.8
ARG ARTIFACTORY_URL=https://one.hitachivantara.com/artifactory/maven

RUN --mount=type=secret,id=myuser \
    --mount=type=secret,id=mytoken\
    PENTAHO_CICD_ONE_USER=$(cat /run/secrets/myuser) && \
    PENTAHO_CICD_ONE_KEY=$(cat /run/secrets/mytoken) && \
    curl -Sf -L -u$PENTAHO_CICD_ONE_USER:$PENTAHO_CICD_ONE_KEY -X GET ${ARTIFACTORY_URL}/pentaho/version-merger/${VERSION_MERGER}/version-merger-${VERSION_MERGER}.jar --output version-merger.jar

RUN curl -fL https://install-cli.jfrog.io | sh

ARG JQ_VERSION=1.6

RUN curl -L -o jq-linux64 https://github.com/stedolan/jq/releases/download/jq-${JQ_VERSION}/jq-linux64 && \
    mv jq-linux64 /usr/local/bin/jq && \
    chmod +x /usr/local/bin/jq

# Install Python and Pip
RUN apt-get update && \
    apt-get install -y python3-pip python3.11-venv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
