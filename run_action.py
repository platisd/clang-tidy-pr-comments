#!/usr/bin/env python

import sys
import os
import json
import requests
import argparse
import yaml
import re
import itertools
import posixpath
import time


def chunks(lst, n):
    # Copied from: https://stackoverflow.com/a/312464
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def main():
    parser = argparse.ArgumentParser(
        description="Duplicate code detection action runner"
    )
    parser.add_argument(
        "--clang-tidy-fixes",
        type=str,
        required=True,
        help="The path to the clang-tidy fixes YAML",
    )
    parser.add_argument(
        "--pull-request-id", type=str, required=True, help="The pull request ID"
    )
    parser.add_argument(
        "--repository-root",
        type=str,
        required=True,
        help="The path to the root of the repository containing the code",
    )
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY")
    github_token = os.environ.get("INPUT_GITHUB_TOKEN")
    review_event = (
        "REQUEST_CHANGES" if os.environ.get("INPUT_REQUEST_CHANGES") == 1 else "COMMENT"
    )
    github_api_url = os.environ.get("GITHUB_API_URL")

    pull_files_url = "%s/repos/%s/pulls/%s/files" % (
        github_api_url,
        repo,
        args.pull_request_id,
    )
    pull_files_result = requests.get(
        pull_files_url,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "Authorization": "token %s" % github_token,
        },
    )

    if pull_files_result.status_code != requests.codes.ok:
        print(
            "Request to get list of files failed with error code: "
            + str(pull_files_result.status_code)
        )
        return 1

    pull_request_files = json.loads(pull_files_result.text)

    files_and_lines_available_for_comments = dict()
    for pull_request_file in pull_request_files:
        git_line_tags = re.findall(r"@@.*?@@", pull_request_file["patch"])
        # The result is something like ['@@ -101,8 +102,11 @@', '@@ -123,9 +127,7 @@']
        # We need to get it to a state like this: ['102,11', '127,7']
        lines_and_changes = [
            line_tag.replace("@@", "").strip().split()[1].replace("+", "")
            for line_tag in git_line_tags
        ]
        lines_available_for_comments = [
            list(
                range(
                    int(change.split(",")[0]),
                    int(change.split(",")[0]) + int(change.split(",")[1]),
                )
            )
            for change in lines_and_changes
        ]
        lines_available_for_comments = list(
            itertools.chain.from_iterable(lines_available_for_comments)
        )
        files_and_lines_available_for_comments[
            pull_request_file["filename"]
        ] = lines_available_for_comments

    clang_tidy_fixes = dict()
    with open(args.clang_tidy_fixes) as file:
        clang_tidy_fixes = yaml.full_load(file)

    repository_root = args.repository_root + "/"
    # repository_root = "/home/dimitris/projects/smartcar_shield/"
    clang_tidy_fixes_for_available_files = list()
    # Normalize paths
    for diagnostic in clang_tidy_fixes["Diagnostics"]:
        diagnostic["FilePath"] = diagnostic["FilePath"].replace(repository_root, "")
        diagnostic["FilePath"] = posixpath.normpath(diagnostic["FilePath"])
        # Remove Replacements since we don't use them and cause problems when looking for duplicates
        diagnostic.pop("Replacements", None)
    # Remove duplicates
    clang_tidy_fixes["Diagnostics"] = [
        dict(t) for t in {tuple(d.items()) for d in clang_tidy_fixes["Diagnostics"]}
    ]
    # Remove entries we cannot comment on as the files weren't changed in this pull request
    clang_tidy_fixes["Diagnostics"] = [
        diagnostic
        for diagnostic in clang_tidy_fixes["Diagnostics"]
        if diagnostic["FilePath"] in files_and_lines_available_for_comments.keys()
    ]

    if len(clang_tidy_fixes["Diagnostics"]) == 0:
        print("No warnings found in lines changed in this pull request")
        return 0

    review_comments = list()
    for diagnostic in clang_tidy_fixes["Diagnostics"]:
        with open(repository_root + diagnostic["FilePath"]) as source_file:
            character_counter = 0
            newlines_until_offset = 0
            for source_file_line in source_file:
                character_counter += len(source_file_line)
                newlines_until_offset += source_file_line.count("\n")
                if character_counter >= diagnostic["FileOffset"]:
                    break
            diagnostic["LineNumber"] = newlines_until_offset
        review_comment_body = (
            ":warning: **"
            + diagnostic["DiagnosticName"]
            + "** :warning:\n"
            + diagnostic["Message"]
        )
        review_comments.append(
            {
                "path": diagnostic["FilePath"],
                "line": diagnostic["LineNumber"],
                "side": "RIGHT",
                "body": review_comment_body,
            }
        )

    # Split the comments in chunks to avoid overloading the server
    # and getting 502 server errors as a response for large reviews
    review_comments = list(chunks(review_comments, 10))
    total_reviews = len(review_comments)
    current_review = 1
    for comments_chunk in review_comments:
        warning_comment = (
            ":warning: "
            "`clang-tidy` found several problems with your code (%i/%i)"
            % (current_review, total_reviews)
        )
        current_review += 1

        pull_request_reviews_url = "%s/repos/%s/pulls/%s/reviews" % (
            github_api_url,
            repo,
            args.pull_request_id,
        )
        post_pull_request_review_result = requests.post(
            pull_request_reviews_url,
            json={
                "body": warning_comment,
                "event": review_event,
                "comments": comments_chunk,
            },
            headers={
                "Accept": "application/vnd.github.v3+json",
                "Authorization": "token %s" % github_token,
            },
        )

        if post_pull_request_review_result.status_code != requests.codes.ok:
            print(
                "Posting review comments failed with error code: "
                + str(post_pull_request_review_result.status_code)
            )
            print(post_pull_request_review_result.text)
            return 1
        # Wait before posting all chunks so to avoid triggering abuse detection
        time.sleep(10)

    return 0


if __name__ == "__main__":
    sys.exit(main())
