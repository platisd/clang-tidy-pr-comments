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
        "'([^']*)'", lambda match: "`` " + unescape_chars(match.group(1)) + " ``", s
    )

    return s


def get_lines(change):
    split_change = change.split(",")
    start = int(split_change[0])
    if len(split_change) > 1:
        size = int(split_change[1])
    else:
        size = 1
    return list(range(start, start + size))


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

        pull_request_files.extend(pull_files_chunk)

    files_and_lines_available_for_comments = {}
    for pull_request_file in pull_request_files:
        # Not all PR file metadata entries may contain a patch section
        # For example, entries related to removed binary files may not contain it
        if "patch" not in pull_request_file:
            continue

        git_line_tags = re.findall(
            r"^@@ -.*? +.*? @@", pull_request_file["patch"], re.MULTILINE
        )
        # The result is something like ['@@ -101,8 +102,11 @@', '@@ -123,9 +127,7 @@']
        # We need to get it to a state like this: ['102,11', '127,7']
        lines_and_changes = [
            line_tag.replace("@@", "").strip().split()[1].replace("+", "")
            for line_tag in git_line_tags
        ]
        lines_available_for_comments = [
            get_lines(change) for change in lines_and_changes
        ]
        lines_available_for_comments = list(
            itertools.chain.from_iterable(lines_available_for_comments)
        )
        files_and_lines_available_for_comments[
            pull_request_file["filename"]
        ] = lines_available_for_comments

    clang_tidy_fixes = {}
    with open(args.clang_tidy_fixes, encoding="utf_8") as file:
        clang_tidy_fixes = yaml.safe_load(file)

    pull_request_reviews_url = "%s/repos/%s/pulls/%d/reviews" % (
        github_api_url,
        repo,
        args.pull_request_id,
    )
    warning_comment_prefix = (
        ":warning: `clang-tidy` found issue(s) with the introduced code"
    )
    if (
        clang_tidy_fixes is None
        or "Diagnostics" not in clang_tidy_fixes.keys()
        or len(clang_tidy_fixes["Diagnostics"]) == 0
    ):
        print("No warnings found by clang-tidy")
        dismiss_change_requests(
            pull_request_reviews_url, github_token, warning_comment_prefix
        )
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
    clang_tidy_diagnostics = []
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
        else:
            # If there are multiple replacements we need to determine whether they are consecutive.
            # If they are, then they need to be applied all at once, therefore we need to merge
            # them all into a single suggestion
            # If not, then we need to create a separate suggestion for each replacement
            # Check if the replacements are consecutive
            replacements_are_consecutive = True
            for i in range(len(diagnostic["DiagnosticMessage"]["Replacements"]) - 1):
                current_offset = diagnostic["DiagnosticMessage"]["Replacements"][i][
                    "Offset"
                ]
                current_length = diagnostic["DiagnosticMessage"]["Replacements"][i][
                    "Length"
                ]
                next_offset = diagnostic["DiagnosticMessage"]["Replacements"][i + 1][
                    "Offset"
                ]
                if current_offset + current_length < next_offset - 1:
                    replacements_are_consecutive = False
                    break

            if replacements_are_consecutive:
                file_paths = []
                file_offsets = []
                replacement_lengths = []
                replacement_texts = []
                for replacement in diagnostic["DiagnosticMessage"]["Replacements"]:
                    file_paths.append(replacement["FilePath"])
                    file_offsets.append(replacement["Offset"])
                    replacement_lengths.append(replacement["Length"])
                    replacement_texts.append(replacement["ReplacementText"])

                assert all(path == file_paths[0] for path in file_paths)
                clang_tidy_diagnostics.append(
                    {
                        "DiagnosticName": diagnostic["DiagnosticName"],
                        "Message": diagnostic["DiagnosticMessage"]["Message"],
                        "FilePath": file_paths[0],
                        "FileOffset": file_offsets[
                            0
                        ],  # Start from the first replacement
                        "ReplacementText": "".join(
                            replacement_texts
                        ),  # Concatenate all replacement texts
                        "ReplacementLength": sum(
                            replacement_lengths
                        ),  # Sum all replacement lengths
                    }
                )
            else:
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
        if diagnostic["FilePath"] in files_and_lines_available_for_comments.keys()
    ]

    if len(clang_tidy_diagnostics) == 0:
        print("No warnings found in files changed in this pull request")
        return 0

    # Create the review comments
    review_comments = []
    for diagnostic in clang_tidy_diagnostics:
        file_path = diagnostic["FilePath"]

        # Apparently Clang-Tidy doesn't support multibyte encodings and measures offsets in bytes
        with open(repository_root + file_path, encoding="latin_1") as f:
            source_file = f.read()
        suggestion_begin = diagnostic["FileOffset"]
        start_line_number = source_file[:suggestion_begin].count("\n") + 1
        # Compose code suggestion/replacement (if available)
        if "ReplacementText" not in diagnostic.keys():
            suggestion = ""
            finish_line_number = start_line_number
        else:
            suggestion_end = suggestion_begin + diagnostic["ReplacementLength"]
            finish_line_number = source_file[:suggestion_end].count("\n") + 1

            # We know exactly what we want to replace, however our GitHub suggestion needs to
            # replace the entire lines, from the first to the last
            lines_to_replace_begin = source_file.rfind("\n", 0, suggestion_begin) + 1
            lines_to_replace_end = source_file.find("\n", suggestion_end)
            source_file_line = (
                source_file[lines_to_replace_begin:suggestion_begin]
                + diagnostic["ReplacementText"]
                + source_file[suggestion_end:lines_to_replace_end]
            )

            # Make sure the code suggestion ends with a newline character
            if not source_file_line or source_file_line[-1] != "\n":
                source_file_line += "\n"
            suggestion = "\n```suggestion\n" + source_file_line + "```"

        # Ignore comments on lines that were not changed in the pull request
        changed_lines = files_and_lines_available_for_comments[file_path]
        if (
            start_line_number in changed_lines
        ):  # The finish line may be outside the changed lines
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
                    "line": finish_line_number,
                    "side": "RIGHT",
                    "body": review_comment_body,
                }
            )
            # The start line number should be added only when needed or GitHub complains
            if start_line_number < finish_line_number:
                review_comments[-1]["start_line"] = start_line_number
                review_comments[-1]["start_side"] = "RIGHT"

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

        existing_pull_request_comments.extend(pull_comments_chunk)

    # Exclude already posted comments
    for comment in existing_pull_request_comments:
        review_comments = list(
            filter(
                lambda review_comment: not (
                    review_comment["path"] == comment["path"]
                    and review_comment["line"] == comment["line"]
                    and review_comment["side"] == comment["side"]
                    and review_comment["body"] == comment["body"]
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
        warning_comment = warning_comment_prefix + " (%i/%i)" % (
            current_review,
            total_reviews,
        )
        current_review += 1

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


def dismiss_change_requests(
    pull_request_reviews_url, github_token, warning_comment_prefix
):
    print("Checking if there are any previous requests for changes to dismiss")
    pull_request_reviews_result = requests.get(
        pull_request_reviews_url,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "Authorization": "token %s" % github_token,
        },
    )
    if pull_request_reviews_result.status_code != requests.codes.ok:
        print(
            "Request to get pull request reviews failed with error code: "
            + str(pull_request_reviews_result.status_code)
        )
        return

    pull_request_reviews_list = json.loads(pull_request_reviews_result.text)
    # Dismiss only our own reviews
    reviews_to_dismiss = [
        review["id"]
        for review in pull_request_reviews_list
        if review["state"] == "CHANGES_REQUESTED"
        and warning_comment_prefix in review["body"]
        and review["user"]["login"] == "github-actions[bot]"
    ]
    pull_request_dismiss_url = pull_request_reviews_url + "/%d/dismissals"
    for review_id in reviews_to_dismiss:
        print("Dismissing review %d" % review_id)
        dismiss_result = requests.put(
            pull_request_dismiss_url % review_id,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "Authorization": "token %s" % github_token,
            },
            json={
                "message": "No clang-tidy warnings found so I assume my comments were addressed",
                "event": "DISMISS",
            },
        )
        if dismiss_result.status_code != requests.codes.ok:
            print(
                "Request to dismiss review failed with error code: "
                + str(dismiss_result.status_code)
            )
        time.sleep(1)  # Avoid triggering abuse detection


if __name__ == "__main__":
    sys.exit(main())
