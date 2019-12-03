#! /bin/bash

uid=`id -u`
user_name=`id -nu`
user_root='root'
git_name=`git config user.name`
git_email=`git config user.email`
ws=`pwd`

function stop_docker() {
	running=$(docker ps -a -q -f "name=$user_name")
	for c in $running
	do
		echo "Stop and remove container: $c"
		docker stop $c > /dev/null
		docker rm $c > /dev/null
	done
}

function init_docker() {
	docker exec -i  -u $user_root $cid bash -c "useradd -m -s /bin/bash -u $uid $user_name" 2> /dev/null
	docker exec -i  -u $user_name $cid bash -c "git config --global user.email '$git_email'"
	docker exec -i  -u $user_name $cid bash -c "git config --global user.name '$git_name'"
	docker exec -i  -u $user_name $cid bash -c "git config --global --add sendemail.suppresscc all"
	docker exec -i  -u $user_name $cid bash -c "git config --global --add wrgit.username $user_name"
}

function start_docker() {
	# start a detached container, and will never attach to it
	run_cmd="docker run
			-dt
			-v $ws:/buildarea--name "$user_name"
			--name "$user_name"
			30153be5f1a4
			/bin/bash"
	running=$(docker ps -a -q -f "name=$user_name" | head -1)
	if [ "x$running" = "x" ]; then
		cid=$($run_cmd)
		if [ "x$?" != "x0" ]; then
			echo "Failed to start container"
			return 1
		fi
		init_docker
	else
		cid=$running
		docker start $cid > /dev/null
	fi
	docker exec -it -u $user_name $cid /bin/bash
}

case $1 in
	'stop')
	stop_docker
	;;
	*)
	start_docker
	;;
esac
