#!/bin/bash
set -xeu

if [ -z "$INPUT_PULL_REQUEST_ID" ]; then
  pull_request_id=$(cat "$GITHUB_EVENT_PATH" | jq 'if (.issue.number != null) then .issue.number else .number end')

  if [ "$pull_request_id" == "null" ]; then
    echo "Could not find a pull request ID. Is this a pull request?"
    exit 0
  fi
else
  pull_request_id="$INPUT_PULL_REQUEST_ID"
fi

repository_name=$(basename $GITHUB_REPOSITORY)
recreated_runner_dir="/home/runner/work/$repository_name"
mkdir -p $recreated_runner_dir
recreated_repo_dir="$recreated_runner_dir/$repository_name"

ln -s $(pwd) $recreated_repo_dir

cd $recreated_repo_dir

eval python3 /action/run_action.py \
  --clang-tidy-fixes $INPUT_CLANG_TIDY_FIXES \
  --pull-request-id $pull_request_id \
  --repository-root $recreated_repo_dir
