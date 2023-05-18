FROM fedora:latest

RUN dnf install --repo=fedora -y zip rpm cpio

# This is where the ZIP will be placed
RUN mkdir /output

# Copy the script over
WORKDIR /app
COPY build.sh build.sh
RUN chmod 700 build.sh

ENV RELEASE=37
ENTRYPOINT /app/build.sh