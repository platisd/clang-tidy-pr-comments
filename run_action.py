#!/usr/bin/env python

import sys
import json
import requests
import argparse


def main():
    # parser = argparse.ArgumentParser(
    #     description="Duplicate code detection action runner")
    # parser.add_argument("--latest-head", type=str,
    #                     default="master", help="The latest commit hash or branch")
    # parser.add_argument("--pull-request-id", type=str,
    #                     required=True, help="The pull request id")
    # args = parser.parse_args()

    repo = os.environ.get('GITHUB_REPOSITORY')
    github_token = os.environ.get('INPUT_GITHUB_TOKEN')
    github_api_url = os.environ.get('GITHUB_API_URL')



    # request_url = '%s/repos/%s/issues/%s/comments' % (
    #     github_api_url, repo, args.pull_request_id)
    # post_result = requests.post(request_url, json={'body': message}, headers={
    #                             'Authorization': 'token %s' % github_token})


    return detection_result.value


if __name__ == "__main__":
    sys.exit(main())
