#!/bin/env bash

# we need root permission for installation
if [ $(id -ru) -ne 0 ]; then
	echo 'please execute install.sh with sudo'
	exit -1
fi

echo 'install buildenv to /usr/local/bin'
cp buildenv /usr/local/bin/

echo 'install templates to /etc/buildenv'
rm -rf /etc/buildenv &> /dev/null
cp -r templates /etc/buildenv

echo 'install success'
