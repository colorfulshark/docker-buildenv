#!/bin/env bash

# we need root permission for installation
if [ $(id -ru) -ne 0 ]; then
	echo 'please execute install.sh with sudo'
	exit -1
fi

echo 'install buildenv to /usr/local/bin'
cp buildenv /usr/local/bin/

echo 'install templates to /etc/buildenv'
mkdir /etc/buildenv &> /dev/null
if [ $? -eq 0 ]; then
	cp -r templates /etc/buildenv
	cp -r projects /etc/buildenv
	chmod 755 /etc/buildenv
	chmod 755 /etc/buildenv/projects
	chmod 755 /etc/buildenv/templates
	chmod 644 /etc/buildenv/projects/*
	chmod 644 /etc/buildenv/templates/*
else
	echo '/etc/buildenv exists, skip'
fi

echo 'install success'
