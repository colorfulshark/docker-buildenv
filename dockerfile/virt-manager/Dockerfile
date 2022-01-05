FROM ubuntu:20.04

ARG base_pkgs='systemd'
ARG dep_pkgs='virt-manager'

RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y locales && locale-gen en_US.UTF-8
RUN apt-get install -y $base_pkgs $dep_pkgs && apt-get clean

ENV LC_ALL en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US.UTF-8

CMD [ "/lib/systemd/systemd" ]
