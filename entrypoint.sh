#!/bin/bash
set -eu

cat $GITHUB_EVENT_PATH

pull_request_id=$(cat "$GITHUB_EVENT_PATH" | jq 'if (.issue.number != null) then .issue.number else .number end')

if [ $pull_request_id == "null" ]; then
  echo "Could not find a pull request ID. Is this a pull request?"
  exit 1
fi

eval python3 /action/run_action.py
