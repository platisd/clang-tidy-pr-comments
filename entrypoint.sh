#!/bin/bash
set -eu

cat $GITHUB_EVENT_PATH

pull_request_id=$(cat "$GITHUB_EVENT_PATH" | jq 'if (.issue.number != null) then .issue.number else .number end')

if [ $pull_request_id == "null" ]; then
  echo "Could not find a pull request ID. Is this a pull request?"
  exit 1
fi

clang_fixes=$(pwd)/clang_fixes.yaml

run-clang-tidy-8 -p=smartcar/test/build -j $(nproc) -header-filter=smartcar/src/* files smartcar/src/* -export-fixes $clang_fixes

echo "!!!!!!!!!!!!!!!!!!!!!!!!!! clang fixes"
cat $clang_fixes

eval python3 /action/run_action.py
