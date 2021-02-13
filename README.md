# docker-buildenv
## background

This project is used to start up a container and set up it for building projects.

Now days the build environment of a software has become more and more complicated. Not only toolchains and libraries need to be installed, but their version need to be compatible with the software we are building. But it's hard to install all kinds of versions of software in a specific distribution, such as Ubuntu.

The old way could be using a virtual machine. Though it does solve the problem, it has some disadvantages, such as resource consumption, low efficiency and not portable.

With the fact that we only use userspace programs while building software, docker turns out to be a better solution for this issue. It uses the kernel of host and doesn't consume extra resources nearly, and the speed is as fast as the program in host.

The only shortcoming may be the complicated configuration. And this is the point this project try to mitigate.

## How to use

There are 2 files in this project:

- buildenv: this main program
- project: this is the environment template of your project

You need to execute following commands to install:

```shell
mkdir /etc/docker-buildenv
cp project /etc/docker-buildenv
cp buildenv /usr/local/bin
```

Then modify the project file.

- image: the docker image name or ID
- name: container name, this script will only start up one container for a project
- workspace: the directory of your workspace in host
- volume: volumes which will be mount into container
- extra_option: additional options for docker run command
- init_project: this function will be called after container has been started

Finally, you just need to execute following command to start the container:

```shell
buildenv project
```

You can create multiple project configuration files and specify any of them as the argument of buildenv.

To stop a container, just use

```shell
buildenv project stop
```

To show help information and all available projects and their status, use

```
buildenv
```

