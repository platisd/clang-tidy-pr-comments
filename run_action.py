#!/usr/bin/env python3

import argparse
import itertools
import json
import os
import posixpath
import re
import sys
import time

import requests
import yaml


def chunks(lst, n):
    # Copied from: https://stackoverflow.com/a/312464
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def markdown(s):
    md_chars = "\\`*_{}[]<>()#+-.!|"


    def escape_chars(s):
        for ch in md_chars:
            s = s.replace(ch, "\\" + ch)

        return s


    def unescape_chars(s):
        for ch in md_chars:
            s = s.replace("\\" + ch, ch)

        return s


    # Escape markdown characters
    s = escape_chars(s)
    # Decorate quoted symbols as code
    s = re.sub(
        "'([^']*)'",
        lambda match:
            "`` " + unescape_chars(match.group(1)) + " ``",
        s
    )

    return s


def main():
    parser = argparse.ArgumentParser(
        description="Pull request comments from clang-tidy reports action runner"
    )
    parser.add_argument(
        "--clang-tidy-fixes",
        type=str,
        required=True,
        help="The path to the clang-tidy fixes YAML",
    )
    parser.add_argument(
        "--pull-request-id",
        type=int,
        required=True,
        help="The pull request ID",
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
        "REQUEST_CHANGES"
        if os.environ.get("INPUT_REQUEST_CHANGES") == "true"
        else "COMMENT"
    )
    github_api_url = os.environ.get("GITHUB_API_URL")

    pull_request_files = []
    # Request a maximum of 100 pages (3000 files)
    for page_num in range(1, 101):
        pull_files_url = "%s/repos/%s/pulls/%d/files?page=%d" % (
            github_api_url,
            repo,
            args.pull_request_id,
            page_num,
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

        pull_files_chunk = json.loads(pull_files_result.text)

        if len(pull_files_chunk) == 0:
            break

        pull_request_files += pull_files_chunk

    files_and_lines_available_for_comments = dict()
    for pull_request_file in pull_request_files:
        # Not all PR file metadata entries may contain a patch section
        # For example, entries related to removed binary files may not contain it
        if "patch" not in pull_request_file:
            continue

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

    if (
        clang_tidy_fixes is None
        or "Diagnostics" not in clang_tidy_fixes.keys()
        or len(clang_tidy_fixes["Diagnostics"]) == 0
    ):
        print("No warnings found by clang-tidy")
        return 0

    # If we have a clang-tidy-8 format, then upconvert it to the clang-tidy-9 one
    if "DiagnosticMessage" not in clang_tidy_fixes["Diagnostics"][0].keys():
        clang_tidy_fixes["Diagnostics"][:] = [
            {
                "DiagnosticName": d["DiagnosticName"],
                "DiagnosticMessage": {
                    "FileOffset": d["FileOffset"],
                    "FilePath": d["FilePath"],
                    "Message": d["Message"],
                    "Replacements": d["Replacements"],
                },
            }
            for d in clang_tidy_fixes["Diagnostics"]
        ]

    repository_root = args.repository_root + "/"
    # Normalize paths
    for diagnostic in clang_tidy_fixes["Diagnostics"]:
        diagnostic["DiagnosticMessage"]["FilePath"] = diagnostic["DiagnosticMessage"][
            "FilePath"
        ].replace(repository_root, "")
        diagnostic["DiagnosticMessage"]["FilePath"] = posixpath.normpath(
            diagnostic["DiagnosticMessage"]["FilePath"]
        )
        for replacement in diagnostic["DiagnosticMessage"]["Replacements"]:
            replacement["FilePath"] = replacement["FilePath"].replace(
                repository_root, ""
            )
            replacement["FilePath"] = posixpath.normpath(replacement["FilePath"])
    # Create a separate diagnostic entry for each replacement entry, if any
    clang_tidy_diagnostics = list()
    for diagnostic in clang_tidy_fixes["Diagnostics"]:
        if not diagnostic["DiagnosticMessage"]["Replacements"]:
            clang_tidy_diagnostics.append(
                {
                    "DiagnosticName": diagnostic["DiagnosticName"],
                    "Message": diagnostic["DiagnosticMessage"]["Message"],
                    "FilePath": diagnostic["DiagnosticMessage"]["FilePath"],
                    "FileOffset": diagnostic["DiagnosticMessage"]["FileOffset"],
                }
            )
            continue
        for replacement in diagnostic["DiagnosticMessage"]["Replacements"]:
            clang_tidy_diagnostics.append(
                {
                    "DiagnosticName": diagnostic["DiagnosticName"],
                    "Message": diagnostic["DiagnosticMessage"]["Message"],
                    "FilePath": replacement["FilePath"],
                    "FileOffset": replacement["Offset"],
                    "ReplacementLength": replacement["Length"],
                    "ReplacementText": replacement["ReplacementText"],
                }
            )
    # Mark duplicates
    unique_diagnostics = set()
    for diagnostic in clang_tidy_diagnostics:
        unique_combo = (
            diagnostic["DiagnosticName"],
            diagnostic["FilePath"],
            diagnostic["FileOffset"],
        )
        diagnostic["Duplicate"] = unique_combo in unique_diagnostics
        unique_diagnostics.add(unique_combo)
    # Remove the duplicates
    clang_tidy_diagnostics[:] = [
        diagnostic
        for diagnostic in clang_tidy_diagnostics
        if not diagnostic["Duplicate"]
    ]

    # Remove entries we cannot comment on as the files weren't changed in this pull request
    clang_tidy_diagnostics[:] = [
        diagnostic
        for diagnostic in clang_tidy_diagnostics
        if diagnostic["FilePath"]
        in files_and_lines_available_for_comments.keys()
    ]

    if len(clang_tidy_diagnostics) == 0:
        print("No warnings found in files changed in this pull request")
        return 0

    # Create the review comments
    review_comments = list()
    for diagnostic in clang_tidy_diagnostics:
        suggestion = ""
        with open(
            repository_root + diagnostic["FilePath"]
        ) as source_file:
            character_counter = 0
            newlines_until_offset = 0
            for source_file_line in source_file:
                character_counter += len(source_file_line)
                newlines_until_offset += 1
                # Check if we have found the line with the warning
                if character_counter > diagnostic["FileOffset"]:
                    beginning_of_line = character_counter - len(source_file_line)
                    if "ReplacementText" in diagnostic:
                        # The offset from the beginning of line until the warning
                        warning_begin = diagnostic["FileOffset"] - beginning_of_line
                        warning_end = warning_begin + diagnostic["ReplacementLength"]
                        source_file_line = (
                            source_file_line[: warning_begin]
                            + diagnostic["ReplacementText"]
                            + source_file_line[warning_end :]
                        )
                        # Make sure the code suggestion ends with a newline character
                        if source_file_line[-1] != "\n":
                            source_file_line += "\n"
                        suggestion += "\n```suggestion\n" + source_file_line + "```"
                    break
            diagnostic["LineNumber"] = newlines_until_offset
        # Ignore comments on lines that were not changed in the pull request
        line_number = diagnostic["LineNumber"]
        file_path = diagnostic["FilePath"]
        changed_lines = files_and_lines_available_for_comments[file_path]
        if line_number in changed_lines:
            review_comment_body = (
                ":warning: **"
                + markdown(diagnostic["DiagnosticName"])
                + "** :warning:\n"
                + markdown(diagnostic["Message"])
                + suggestion
            )
            review_comments.append(
                {
                    "path": file_path,
                    "line": line_number,
                    "side": "RIGHT",
                    "body": review_comment_body,
                }
            )

    if len(review_comments) == 0:
        print("Warnings found but none in lines changed by this pull request.")
        return 0

    # Load the existing review comments
    existing_pull_request_comments = []
    # Request a maximum of 100 pages (3000 comments)
    for page_num in range(1, 101):
        pull_comments_url = "%s/repos/%s/pulls/%d/comments?page=%d" % (
            github_api_url,
            repo,
            args.pull_request_id,
            page_num,
        )
        pull_comments_result = requests.get(
            pull_comments_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "Authorization": "token %s" % github_token,
            },
        )

        if pull_comments_result.status_code != requests.codes.ok:
            print(
                "Request to get pull request comments failed with error code: "
                + str(pull_comments_result.status_code)
            )
            return 1

        pull_comments_chunk = json.loads(pull_comments_result.text)

        if len(pull_comments_chunk) == 0:
            break

        existing_pull_request_comments += pull_comments_chunk

    # Exclude already posted comments
    for comment in existing_pull_request_comments:
        review_comments = list(
            filter(
                lambda review_comment: not (
                    review_comment["path"] == comment["path"] and
                    review_comment["line"] == comment["line"] and
                    review_comment["side"] == comment["side"] and
                    review_comment["body"] == comment["body"]
                ),
                review_comments,
            )
        )

    if len(review_comments) == 0:
        print("No new warnings found for this pull request.")
        return 0

    # Split the comments in chunks to avoid overloading the server
    # and getting 502 server errors as a response for large reviews
    suggestions_per_comment = int(os.environ.get("INPUT_SUGGESTIONS_PER_COMMENT"))
    review_comments = list(chunks(review_comments, suggestions_per_comment))
    total_reviews = len(review_comments)
    current_review = 1
    for comments_chunk in review_comments:
        warning_comment = (
            ":warning: "
            "`clang-tidy` found issue(s) with the introduced code (%i/%i)"
            % (current_review, total_reviews)
        )
        current_review += 1

        pull_request_reviews_url = "%s/repos/%s/pulls/%d/reviews" % (
            github_api_url,
            repo,
            args.pull_request_id,
        )
        post_review_result = requests.post(
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

        if post_review_result.status_code != requests.codes.ok:
            print(post_review_result.text)
            # Ignore bad gateway errors (false negatives?)
            if post_review_result.status_code != requests.codes.bad_gateway:
                print(
                    "Posting review comments failed with error code: "
                    + str(post_review_result.status_code)
                )
                print("Please report this error to the GitHub Action maintainer")
                return 1
        # Wait before posting all chunks so to avoid triggering abuse detection
        time.sleep(10)

    return 0


if __name__ == "__main__":
    sys.exit(main())
