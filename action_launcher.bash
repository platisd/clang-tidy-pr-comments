#!/bin/bash

set -eu

if [ -z "$INPUT_PULL_REQUEST_ID" ]; then
  pull_request_id="$(jq "if (.issue.number != null) then .issue.number else .number end" < "$GITHUB_EVENT_PATH")"

  if [ "$pull_request_id" == "null" ]; then
    echo "Could not find the pull request ID. Is this a pull request?"
    exit 0
  fi
else
  pull_request_id="$INPUT_PULL_REQUEST_ID"
fi

repository_name="$(basename "$GITHUB_REPOSITORY")"
recreated_runner_dir="$INPUT_REPO_PATH_PREFIX/$repository_name"
mkdir -p "$recreated_runner_dir"
recreated_repo_dir="$recreated_runner_dir/$repository_name"

ln -s "$(pwd)" "$recreated_repo_dir"

cd "$recreated_repo_dir"

if [ ! -f "$INPUT_CLANG_TIDY_FIXES" ]; then
  echo "Could not find the clang-tidy fixes file '$INPUT_CLANG_TIDY_FIXES'. Perhaps it wasn't created?"
  exit 0
fi

"${GITHUB_ACTION_PATH}/venv/bin/python" "${GITHUB_ACTION_PATH}/run_action.py" \
  --clang-tidy-fixes "$INPUT_CLANG_TIDY_FIXES" \
  --pull-request-id "$pull_request_id" \
  --repository "$GITHUB_REPOSITORY" \
  --repository-root "$recreated_repo_dir" \
  --request-changes "$INPUT_REQUEST_CHANGES" \
  --suggestions-per-comment "$INPUT_SUGGESTIONS_PER_COMMENT"
