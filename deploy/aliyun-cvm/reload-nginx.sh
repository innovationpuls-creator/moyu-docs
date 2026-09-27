#!/bin/sh
set -eu

pid_file=/run/nginx.pid
if [ -s "$pid_file" ]; then
	kill -HUP "$(cat "$pid_file")"
fi
