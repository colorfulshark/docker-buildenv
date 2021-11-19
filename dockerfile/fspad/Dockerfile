FROM ubuntu:14.04

ARG DEBIAN_FRONTEND=noninteractive
ARG base_pkgs='vim git bc'
ARG dep_pkgs='build-essential u-boot-tools gawk libc6:i386 libncurses5:i386 libstdc++6:i386 zlib1g:i386 busybox'

ENV TZ=Asia/Shanghai

RUN dpkg --add-architecture i386
RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y locales && locale-gen en_US.UTF-8

ENV LC_ALL en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US.UTF-8

RUN apt-get install -y $base_pkgs $dep_pkgs && apt-get clean

CMD [ "bash" ]
