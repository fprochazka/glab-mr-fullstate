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

## Example Output

### Successful Pipeline

```
MR Information:
  Title: feat: Add user authentication
  Author: John Doe
  State: opened
  URL: https://gitlab.example.com/myorg/myproject/-/merge_requests/123

Files Created:
  MR Info:               /tmp/glab-mr-123-20251125_104940/mr-info.txt
  Comments (resolved):   /tmp/glab-mr-123-20251125_104940/comments-resolved.txt (42 comments)
  Comments (unresolved): /tmp/glab-mr-123-20251125_104940/comments-unresolved.txt (3 comments)
  Pipeline:              /tmp/glab-mr-123-20251125_104940/full-pipeline-summary.txt (status: success)

All files in: /tmp/glab-mr-123-20251125_104940
```

### Failed Pipeline

When jobs fail, they are prominently displayed with direct links to logs:

```
MR Information:
  Title: fix: Update database schema
  Author: Jane Smith
  State: opened
  URL: https://gitlab.example.com/myorg/myproject/-/merge_requests/456

Files Created:
  MR Info:               /tmp/glab-mr-456-20251125_105320/mr-info.txt
  Comments (resolved):   /tmp/glab-mr-456-20251125_105320/comments-resolved.txt (18 comments)
  Comments (unresolved): /tmp/glab-mr-456-20251125_105320/comments-unresolved.txt (2 comments)
  Pipeline:              /tmp/glab-mr-456-20251125_105320/full-pipeline-summary.txt (status: failed)

Failed Jobs (2):
  unit-tests: /tmp/glab-mr-456-20251125_105320/job-logs/unit-tests-2803156.log
  integration-tests: /tmp/glab-mr-456-20251125_105320/job-logs/integration-tests-2803157.log

All files in: /tmp/glab-mr-456-20251125_105320
```

## Requirements

- Python 3.12+
- `glab` CLI installed and configured
