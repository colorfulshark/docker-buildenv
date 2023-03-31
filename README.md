# docker-buildenv
## What is it

This tool can start a OS-Level container, just like LXC/LXD does!

So why not LXC/LXD? If you can use LXC/LXD, just play with it! If you can't, please keep reading.

Docker is normally a APP-Level container, it's OK for **deployment**, but not for **development**, Why?

1. Lack of init process
In a development environment, we need a real init process, such as systemd, rather that a fake one, like bash.

2. Hard to keep changes
Docker use overlayfs for rootfs, which will grow up all the time, and once you delete the container, you lose everything.


How does buildenv solve those problems:
1. Start real init process
While running the container, buildenv will launch the init program, such as systemd.

2. Mount everything outside the container
We use a empty docker image as the base system, and mount the whole rootfs into the container, so everything will be kept.

Finally, you will get a nearly real OS container, you can install every program or service in it, even a desktop is possible!

Try it by yourself!


## How to use

You need to install docker engine first, and you need to have permission to operate with docker!
Please refer to https://docs.docker.com/engine/install

1. Install buildenv

```
sudo ./install.sh
```

2. Edit project config
```
sudo vim /etc/buildenv/projects/project
```

For example
```
# buildenv template, you can list all templates with 'buildenv template'
template="debian-11"

# the directory to store the rootfs, this directory must exist and be empty
rootfs_dir='/opt/docker/debian-11'
```

3. Init your project
```
buildenv init project
```

4. Start your project
```
buildenv start project
```

Now you are there!

You can also just execute buildenv for help.



