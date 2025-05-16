#!/bin/bash

set -e

echo "Python version: $(python --version)"
echo "App run command args: $@"
echo "APP_ENVIRONMENT: $ENV"
echo "REGION: $REGION"

sed -i -e 's/<ENV>/'"$ENV"'/g' /home/plivo/env.ctmpl
sed -i -e 's/<REGION>/'"$REGION"'/g' /home/plivo/env.ctmpl

echo "Getting config from consul..."
/usr/sbin/consul-template \
    -consul-addr "$CONSUL" \
    -template "/home/plivo/env.ctmpl:/home/plivo/.env" \
    -once
status="$?"
echo "Exit status after getting env: $status"
if [ "$status" != "0" ]
then
  echo "Deployment failed due to config fetch failure"
  exit 1
fi

echo "Starting uvicorn server"
env $(cat /home/plivo/.env | grep -v '^#' | xargs) python src/server/main.py
