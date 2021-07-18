# clang-tidy pull request comments
![clang-tidy-8 support] ![clang-tidy-9 support] ![clang-tidy-10 support] ![clang-tidy-11 support] ![clang-tidy-12 support]

A GitHub Action to post `clang-tidy` warnings and suggestions as review comments on your pull request.

![action preview](https://i.imgur.com/lQiFdT9.png)

## What

`platisd/clang-tidy-pr-comments` is a GitHub Action that utilizes the *exported fixes* of
`clang-tidy` for your C++ project and posts them as **code review comments** in the related **pull request**.

If `clang-tidy` has a concrete recommendation on how you should modify your code to fix the issue that's detected,
then it will be presented as a *suggested change* that can be committed directly. Alternatively,
the offending line will be highlighted along with a description of the warning.

The GitHub Action can be configured to *request changes* if `clang-tidy` warnings are found or merely
leave a comment without blocking the pull request from being merged. It should fail only if it has been
misconfigured by you, due to a bug (please contact me if that's the case) or the GitHub API acting up.

Please note the following:
* It will **not** run `clang-tidy` for you. You are responsible for doing that and then
  supply the Action with the path to your generated report (see examples below).<br>
  Specifically, the YAML report that includes the *fixes* is generated via the `-export-fixes` argument
  to the `run-clang-tidy` utility script. Alternatively, you may use `--export-fixes` with `clang-tidy`
  itself and then, in both cases, specify the path where you would like the report to be exported.<br>
  The very same path should be supplied to the GitHub Action.
* It will *only* comment on files and lines changed in the pull request. This is due to GitHub not allowing
  comments on other files outside the pull request `diff`.
  This means that there may be more warnings in your project. Make sure you fix
  them *before* starting to use this Action to ensure new warnings will not be introduced in the future.
* This Action *respects* existing comments and doesn't repeat the same warnings for the same line (no spam).

### Supported clang-tidy versions

YAML files containing generated fixes by the following `clang-tidy` versions are currently supported:
* `clang-tidy-8`
* `clang-tidy-9`
* `clang-tidy-10`
* `clang-tidy-11`
* `clang-tidy-12`

## How

Since this action comments on files changed in pull requests, naturally, it can be only run
on `pull_request` events. That being said, if it happens to be triggered in a different context,
e.g. a `push` event, it will **not** run and fail *softly* by returning a *success* code.

A basic configuration for the `platisd/clang-tidy-pr-comments` action can be seen below:

```yaml
name: Static analysis

on: pull_request

jobs:
  clang-tidy:
    runs-on: ubuntu-20.04
    steps:
      - uses: actions/checkout@v2
      - name: Build project and/or unit tests
        run: ./your-build-script.sh
      - name: Run clang-tidy
        run: ./your-clang-tidy-script.sh --fixes-path fixes.yaml
      - name: Run clang-tidy-pr-comments action
        uses: platisd/clang-tidy-pr-comments@master
        with:
          # The GitHub token (or a personal access token)
          github_token: ${{ secrets.GITHUB_TOKEN }}
          # The path to the clang-tidy fixes generated previously
          clang_tidy_fixes: fixes.yaml
          # Optionally set to true if you want the Action to request
          # changes in case warnings are found
          request_changes: true
          # Optionally set the number of comments per review
          # to avoid GitHub API timeouts for heavily loaded
          # pull requests
          suggestions_per_comment: 10
```

If you want to trigger the Action manually, i.e. by leaving a comment with a particular *keyword*
in the pull request, then you can try the following:

```yaml
name: Static analysis

# Don't trigger it on pull_request events but issue_comment instead
on: issue_comment

jobs:
  clang-tidy:
    # Trigger the job only when someone comments: run_clang_tidy
    if: github.event.issue.pull_request && contains(github.event.comment.body, 'run_clang_tidy')
    runs-on: ubuntu-20.04
    steps:
      - uses: actions/checkout@v2
      - name: Build project and/or unit tests
        run: ./your-build-script.sh
      - name: Run clang-tidy
        run: ./your-clang-tidy-script.sh --fixes-path fixes.yaml
      - name: Run clang-tidy-pr-comments action
        uses: platisd/clang-tidy-pr-comments@master
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          clang_tidy_fixes: fixes.yaml
```

If you want to trigger the Action using the `workflow_run` event to run analysis on pull requests
from forks in a
[secure manner](https://securitylab.github.com/research/github-actions-preventing-pwn-requests/),
then you can try the following:

```yaml
name: Post static analysis results

on:
  workflow_run:
    # Workflow that should provide the results of the analysis via artifact
    workflows: [ "Static analysis" ]
    types: [ completed ]

jobs:
  clang-tidy-results:
    # Trigger the job only if previous workflow completed successfully
    if: ${{ github.event.workflow_run.event == 'pull_request' && github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-20.04
    steps:
      #
      # In the previous steps you will need to download and extract the artifact with the
      # fixes.yaml file and set the pr_id environment variable to the pull request id
      #
      - name: Run clang-tidy-pr-comments action
        uses: platisd/clang-tidy-pr-comments@master
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          clang_tidy_fixes: fixes.yaml
          pull_request_id: ${{ env.pr_id }}
```


[clang-tidy-8 support]: https://img.shields.io/badge/clang--tidy-8-green
[clang-tidy-9 support]: https://img.shields.io/badge/clang--tidy-9-green
[clang-tidy-10 support]: https://img.shields.io/badge/clang--tidy-10-green
[clang-tidy-11 support]: https://img.shields.io/badge/clang--tidy-11-green
[clang-tidy-12 support]: https://img.shields.io/badge/clang--tidy-12-green
