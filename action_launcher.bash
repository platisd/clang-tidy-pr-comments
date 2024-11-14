#!/bin/bash

set -eu

if [ -n "$INPUT_PULL_REQUEST_ID" ]; then
  pull_request_id="$INPUT_PULL_REQUEST_ID"
elif [ -n "$PULL_REQUEST_ID" ]; then
  pull_request_id="$PULL_REQUEST_ID"
else
  echo "Could not find the pull request ID. Is this a pull request?"
  exit 0
fi

repository_name="$(basename "$GITHUB_REPOSITORY")"
recreated_runner_dir="$INPUT_REPO_PATH_PREFIX/$repository_name"
mkdir -p "$recreated_runner_dir"
recreated_repo_dir="$recreated_runner_dir/$repository_name"

ln -s "$(pwd)" "$recreated_repo_dir"

cd "$recreated_repo_dir"

"${GITHUB_ACTION_PATH}/venv/bin/python" "${GITHUB_ACTION_PATH}/run_action.py" \
  --clang-tidy-fixes "$INPUT_CLANG_TIDY_FIXES" \
  --pull-request-id "$pull_request_id" \
  --repository "$GITHUB_REPOSITORY" \
  --repository-root "$recreated_repo_dir" \
  --request-changes "$INPUT_REQUEST_CHANGES" \
  --suggestions-per-comment "$INPUT_SUGGESTIONS_PER_COMMENT" \
  --auto-resolve-conversations "$INPUT_AUTO_RESOLVE_CONVERSATIONS"
