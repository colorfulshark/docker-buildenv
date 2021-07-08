FROM ubuntu:12.04

ARG base_pkgs='vim git bc'
ARG dep_pkgs='build-essential libncurses-dev gcc make libc6-dev'

RUN sed -i 's/archive.ubuntu/old-releases.ubuntu/' /etc/apt/sources.list
RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y locales && locale-gen en_US.UTF-8
RUN apt-get install -y $base_pkgs $dep_pkgs && apt-get clean

ENV LC_ALL en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US.UTF-8

CMD [ "bash" ]
