FROM ubuntu:16.04

ARG base_pkgs='vim git bc'
ARG dep_pkgs='gawk wget git diffstat unzip texinfo gcc build-essential chrpath socat cpio python3 python3-pip python3-pexpect xz-utils debianutils iputils-ping python3-git python3-jinja2 libegl1-mesa libsdl1.2-dev pylint3 xterm python3-subunit mesa-common-dev'

RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y locales && locale-gen en_US.UTF-8
RUN apt-get install -y $base_pkgs $dep_pkgs && apt-get clean

ENV LC_ALL en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US.UTF-8

CMD [ "bash" ]
