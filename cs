#! /usr/bin/env bash

function init_global_env() {
	uid=`id -u`
	username=`id -nu`
	attach_user=$username
	rootuser='root'
	git_name=`git config user.name`
	git_email=`git config user.email`
	workspace=`pwd`
}

function container_cmd() {
	user=$1
	cmd=$2
	docker exec -i -u $user $container_id bash -c "$cmd"
}

function init_docker() {
	container_cmd $rootuser "useradd -m -s /bin/bash -u $uid $username"
	container_cmd $username "git config --global user.email '$git_email'"
	container_cmd $username "git config --global user.name '$git_name'"
}

function find_container() {
	if [ "x$target" == "x" ]; then
		echo 'you must specify a container name'
		exit
	fi
	container_id=$(docker ps -a -q -f "name=^$container_name$")
	if [ "x$container_id" == "x" ]; then
		echo "container $container_name does not exist"
	else
		echo "found $container_name: $container_id"
	fi
}

function start_docker() {
	run_cmd="docker run
			-dt
			$volume
			--name $container_name
			$docker_image
			/bin/bash"
	find_container
	if [ "x$container_id" == "x" ]; then
		echo "create container $container_name" now
		container_id=$($run_cmd)
		if [ "x$?" != "x0" ]; then
			echo "failed to start container $container_name"
			exit
		fi
		init_docker $container_id
	else
		docker start $container_id > /dev/null
	fi
	docker exec -it -u $attach_user $container_id /bin/bash
}

function stop_docker() {
	find_container
	if [ "x$container_id" == "x" ]; then
		return
	fi
	echo "stop and remove container..."
	docker stop $container_id > /dev/null
	docker rm $container_id > /dev/null
}

function list_container() {
	docker ps -a -f "name=^${username}"
}

function show_help() {
	echo 'Usage: cs [OPTIONS]'
	echo ''
	echo 'A script used to start a container with custom configuration'
	echo ''
	echo 'Options:'
	echo '-r	start a container, this is the default option,'
	echo '	you need to specify docker image and container name'
	echo '-s	stop a container, you need to specify container name'
	echo '-h	show this help message'
	echo '-n	specify container name'
	echo '-i	specify docker image'
	echo '-v	specify mount volumn'
}

function parse_argument() {
	init_global_env
	command='run'
	while getopts 'hi:ln:rsv:' opt
	do
		case $opt in
			'h')
			command='help'
			;;
			'i')
			docker_image="$OPTARG"
			;;
			'l')
			command='list'
			;;
			'n')
			target="$OPTARG"
			;;
			'r')
			attach_user=$rootuser
			;;
			's')
			command='stop'
			;;
			'v')
			volume="$volume""-v $OPTARG "
			;;
			?)
			return 1
			;;
		esac
	done
	shift $(($OPTIND-1))
	container_name="${username}_${target}"
}

function start_process() {
	case $command in
		'run')
		start_docker
		;;
		'stop')
		stop_docker
		;;
		'list')
		list_container
		;;
		'help')
		show_help
		;;
	esac
}

parse_argument $*
start_process

