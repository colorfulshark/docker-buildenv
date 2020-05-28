#! /bin/bash

uid=`id -u`
user_name=`id -nu`
user_root='root'
git_name=`git config user.name`
git_email=`git config user.email`
ws=`pwd`

function stop_docker() {
	# parse options
	while getopts 'a:' opt
	do
		case $opt in
			'a')
			;;
			?)
			return 1
			;;
		esac
	done
	shift $(($OPTIND-1))

	if [ "x$*" == "x" ]; then
		target='default'
	else
		target=$*
	fi
	container_name="$user_name"_"$target"
	running=$(docker ps -a -q -f "name=$container_name")
	cnt=$(echo $running | wc -w)

	if [ "$cnt" -gt "1" ]; then
		# more then 1 matched container, don't know what to do
		echo "ERROR: More than one satisfied target"
		docker ps -a -f "name=$container_name"
		return 1
	elif [ "$cnt" -eq "1" ]; then
		# only 1 matched container, stop and remove it
		echo "Stop and remove container..."
		echo "$container_name: $running"
		docker stop $running > /dev/null
		docker rm $running > /dev/null
	else
		# no matched container, just ignore it
		echo "Container $container_name does not exist"
	fi
}

function init_docker() {
	cid=$1
	docker exec -i  -u $user_root $cid bash -c "useradd -m -s /bin/bash -u $uid $user_name" 2> /dev/null
	docker exec -i  -u $user_name $cid bash -c "git config --global user.email '$git_email'"
	docker exec -i  -u $user_name $cid bash -c "git config --global user.name '$git_name'"
	docker exec -i  -u $user_name $cid bash -c "git config --global --add sendemail.suppresscc all"
	docker exec -i  -u $user_name $cid bash -c "git config --global --add wrgit.username $user_name"
}

function start_docker() {
	while getopts 'i:n:v:' opt
	do
		case $opt in
			'i')
			docker_image="$OPTARG"
			;;
			'n')
			target="$OPTARG"
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

	if [ "x$target" == "x" ]; then
		target='default'
	fi
	container_name="$user_name"_"$target"
	run_cmd="docker run
			-dt
			$volume
			--name $container_name
			$docker_image
			/bin/bash"
	running=$(docker ps -a -q -f "name=$container_name")
	cnt=$(echo $running | wc -w)

	if [ "$cnt" -gt "1" ]; then
		# more then 1 matched container, don't know what to do
		echo "ERROR: More than one satisfied target"
		docker ps -a -f "name=$container_name"
		return 1
	elif [ "$cnt" -eq "1" ]; then
		echo "Found 1 container named $container_name, just start it"
		# only 1 matched container, just start it
		cid=$running
		docker start $cid > /dev/null
	else
		# no matched container, just create one
		echo "Container $container_name does not exist, create one"
		cid=$($run_cmd)
		if [ "x$?" != "x0" ]; then
			echo "Failed to start container $container_name"
			return 1
		fi
		init_docker $cid
	fi

	docker exec -it -u $user_name $cid /bin/bash
}

function help() {
	echo 'To be implemented...'
}

case $1 in
	'stop')
	shift
	stop_docker $*
	;;
	'run')
	shift
	start_docker $*
	;;
	'help')
	help
	;;
	*)
	start_docker $*
	;;
esac
