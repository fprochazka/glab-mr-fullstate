# glab-mr-fullstate

A CLI tool to fetch comprehensive GitLab merge request information.

## Features

- Fetches complete MR details (description, link, author, etc.)
- Downloads all comments and notes
- Gets latest pipeline status and job details
- Fetches job logs for all pipeline jobs
- Organizes everything into well-structured temp files
- Auto-detects MR from current branch (or accepts MR ID)

## Installation

```bash
uv sync
```

## Usage

```bash
# Run from within a Git repository with an open merge request
cd /path/to/your/repo
glab-mr-fullstate
```

The tool auto-detects the MR from your current branch using `glab` CLI.
It must be run from within a Git repository that has an open merge request.

## Output

Creates a timestamped directory in `/tmp` with:
- `mr-info.txt`: Full MR details (human-readable and JSON)
- `comments-resolved.txt`: Resolved threads and non-resolvable comments
- `comments-unresolved.txt`: Active unresolved discussion threads
- `full-pipeline-summary.txt`: Latest pipeline status and all jobs
- `job-logs/`: Directory with individual log files for each job

## Requirements

- Python 3.12+
- `glab` CLI installed and configured
