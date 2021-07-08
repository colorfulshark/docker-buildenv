FROM ubuntu:18.04

ARG DEBIAN_FRONTEND=noninteractive
ARG base_pkgs='vim git bc'
ARG dep_pkgs='build-essential asciidoc binutils bzip2 gawk gettext git libncurses5-dev libz-dev patch python3 python2.7 unzip zlib1g-dev lib32gcc1 libc6-dev-i386 subversion flex uglifyjs git-core gcc-multilib p7zip p7zip-full msmtp libssl-dev texinfo libglib2.0-dev xmlto qemu-utils upx libelf-dev autoconf automake libtool autopoint device-tree-compiler g++-multilib antlr3 gperf wget curl swig rsync'

ENV TZ=Asia/Shanghai

RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y locales && locale-gen en_US.UTF-8

ENV LC_ALL en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US.UTF-8

RUN apt-get install -y $base_pkgs $dep_pkgs && apt-get clean

CMD [ "bash" ]
