#!/usr/bin/env python3
"""
GitLab MR Full State Fetcher

Fetches comprehensive merge request information including:
- MR details (description, link, author, etc.)
- All comments and notes
- Latest pipeline status and job details
- Job logs

Usage:
    glab-mr-fullstate <mr-id> [--hostname HOST]
    glab-mr-fullstate 123
    glab-mr-fullstate !456 --hostname gitlab.example.com

All data is saved to temp files with a summary output showing file locations.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml


def is_interactive_terminal() -> bool:
    """
    Detect if running in an interactive terminal vs AI tool/pipe/automation.
    """
    ai_indicators = ["CLAUDECODE", "AIDER", "CURSOR", "GITHUB_COPILOT"]
    if any(os.environ.get(var) for var in ai_indicators):
        return False

    is_tty = sys.stdin.isatty() and sys.stdout.isatty()

    if is_tty and os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass

    return is_tty


class Colors:
    """ANSI color codes, disabled for non-interactive terminals"""

    _is_interactive = is_interactive_terminal()

    RED = "\033[0;31m" if _is_interactive else ""
    GREEN = "\033[0;32m" if _is_interactive else ""
    YELLOW = "\033[1;33m" if _is_interactive else ""
    BLUE = "\033[0;34m" if _is_interactive else ""
    CYAN = "\033[0;36m" if _is_interactive else ""
    MAGENTA = "\033[0;35m" if _is_interactive else ""
    NC = "\033[0m" if _is_interactive else ""


def get_glab_config_path() -> Path:
    """Get the platform-specific path to the glab config file."""
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "glab-cli" / "config.yml"
    else:
        return Path.home() / ".config" / "glab-cli" / "config.yml"


def get_glab_hostnames() -> list[str]:
    """Parse glab config to get available GitLab hostnames."""
    config_path = get_glab_config_path()

    if not config_path.exists():
        return []

    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not config or "hosts" not in config:
            return []

        return list(config["hosts"].keys())
    except (yaml.YAMLError, OSError):
        return []


class MRFullStateFetcher:
    def __init__(self):
        self.is_interactive = is_interactive_terminal()

        # Will be set after fetching MR data
        self.mr_id = None
        self.output_dir = None
        self.mr_info_file = None
        self.comments_file = None
        self.pipeline_summary_file = None
        self.jobs_dir = None

        # Data storage
        self.mr_data = {}
        self.comments = []
        self.pipeline_data = {}
        self.jobs_data = []

    def setup_output_files(self):
        """Setup output directory and files after we know the MR ID."""
        # Create temp directory for output
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_base = Path(tempfile.gettempdir())
        self.output_dir = temp_base / f"glab-mr-{self.mr_id}-{timestamp}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Output files
        self.mr_info_file = self.output_dir / "mr-info.txt"
        self.comments_resolved_file = self.output_dir / "comments-resolved.txt"
        self.comments_unresolved_file = self.output_dir / "comments-unresolved.txt"
        self.pipeline_summary_file = self.output_dir / "full-pipeline-summary.txt"
        self.jobs_dir = self.output_dir / "job-logs"
        self.jobs_dir.mkdir(exist_ok=True)

    def print_color(self, message: str, color: str = ""):
        """Print colored message."""
        if color:
            print(f"{color}{message}{Colors.NC}")
        else:
            print(message)

    def get_job_log_path(self, job: dict) -> Path:
        """Get the log file path for a given job."""
        job_id = job.get("id")
        job_name = job.get("name", "unknown")
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", job_name)
        return self.jobs_dir / f"{safe_name}-{job_id}.log"

    async def run_glab(self, *args) -> tuple[str, str, int]:
        """Run glab command and return stdout, stderr, and return code."""
        glab_args = ["glab", *args]

        proc = await asyncio.create_subprocess_exec(
            *glab_args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace"), proc.returncode

    async def fetch_mr_info(self):
        """Fetch MR information using glab mr view."""
        if self.is_interactive:
            self.print_color("Fetching MR information...", Colors.BLUE)

        # Use glab mr view with JSON output - auto-detects MR from current branch
        stdout, stderr, code = await self.run_glab("mr", "view", "--output=json")

        if code != 0:
            self.print_color(f"Error fetching MR data: {stderr}", Colors.RED)
            sys.exit(1)

        try:
            self.mr_data = json.loads(stdout)
            self.mr_id = str(self.mr_data.get("iid"))  # Get the actual MR ID from response
            self.setup_output_files()  # Now we can setup files with the correct MR ID
        except json.JSONDecodeError as e:
            self.print_color(f"Error parsing MR data: {e}", Colors.RED)
            sys.exit(1)

        # Also get the text view for human readability
        stdout_view, _, _ = await self.run_glab("mr", "view", self.mr_id)

        # Write both formats to file
        with open(self.mr_info_file, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write("MERGE REQUEST INFORMATION\n")
            f.write("=" * 80 + "\n\n")
            f.write(stdout_view)
            f.write("\n\n" + "=" * 80 + "\n")
            f.write("RAW JSON DATA\n")
            f.write("=" * 80 + "\n\n")
            f.write(json.dumps(self.mr_data, indent=2))

        if self.is_interactive:
            self.print_color(f"✓ MR info saved to: {self.mr_info_file}", Colors.GREEN)

    async def fetch_comments(self):
        """Fetch all comments and notes on the MR."""
        if self.is_interactive:
            self.print_color("Fetching comments and notes...", Colors.BLUE)

        # Fetch notes using API - need project_id and iid
        project_id = self.mr_data.get("project_id")
        stdout, stderr, code = await self.run_glab(
            "api", f"projects/{project_id}/merge_requests/{self.mr_id}/notes?per_page=100", "--paginate"
        )

        if code != 0:
            self.print_color(f"Error fetching comments: {stderr}", Colors.RED)
            return

        try:
            # Fix pagination format
            fixed_json = stdout.replace("][", ",")
            self.comments = json.loads(fixed_json)
        except json.JSONDecodeError as e:
            self.print_color(f"Error parsing comments: {e}", Colors.RED)
            return

        # Split comments into resolved and unresolved
        # If comment is not a resolvable thread (type != "DiffNote"), it goes to resolved
        resolved_comments = []
        unresolved_comments = []

        for comment in self.comments:
            note_type = comment.get("type")
            resolvable = comment.get("resolvable", False)
            resolved = comment.get("resolved", False)

            # If it's not a resolvable type (DiffNote), treat as resolved
            # OR if it's resolvable and actually resolved
            if not resolvable or resolved:
                resolved_comments.append(comment)
            else:
                unresolved_comments.append(comment)

        # Write resolved comments
        with open(self.comments_resolved_file, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"RESOLVED COMMENTS AND NOTES (Total: {len(resolved_comments)})\n")
            f.write("=" * 80 + "\n\n")

            for idx, comment in enumerate(resolved_comments, 1):
                author = comment.get("author", {}).get("name", "Unknown")
                created_at = comment.get("created_at", "Unknown")
                body = comment.get("body", "")
                note_type = comment.get("type", "")
                system = comment.get("system", False)
                position = comment.get("position")

                f.write(f"[{idx}] {author} - {created_at}\n")
                if system:
                    f.write("[SYSTEM NOTE]\n")
                if note_type:
                    f.write(f"Type: {note_type}\n")

                # Add code position if available
                if position:
                    commit = position.get("head_sha", "")[:8]  # Short SHA
                    file_path = position.get("new_path") or position.get("old_path", "")
                    line_num = position.get("new_line") or position.get("old_line")
                    if commit and file_path:
                        f.write(f"Code: {commit} {file_path}")
                        if line_num:
                            f.write(f":{line_num}")
                        f.write("\n")

                f.write("-" * 80 + "\n")
                f.write(body)
                f.write("\n\n" + "=" * 80 + "\n\n")

        # Write unresolved comments
        with open(self.comments_unresolved_file, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"UNRESOLVED COMMENTS AND NOTES (Total: {len(unresolved_comments)})\n")
            f.write("=" * 80 + "\n\n")

            for idx, comment in enumerate(unresolved_comments, 1):
                author = comment.get("author", {}).get("name", "Unknown")
                created_at = comment.get("created_at", "Unknown")
                body = comment.get("body", "")
                note_type = comment.get("type", "")
                system = comment.get("system", False)
                position = comment.get("position")

                f.write(f"[{idx}] {author} - {created_at}\n")
                if system:
                    f.write("[SYSTEM NOTE]\n")
                if note_type:
                    f.write(f"Type: {note_type}\n")

                # Add code position if available
                if position:
                    commit = position.get("head_sha", "")[:8]  # Short SHA
                    file_path = position.get("new_path") or position.get("old_path", "")
                    line_num = position.get("new_line") or position.get("old_line")
                    if commit and file_path:
                        f.write(f"Code: {commit} {file_path}")
                        if line_num:
                            f.write(f":{line_num}")
                        f.write("\n")

                f.write("-" * 80 + "\n")
                f.write(body)
                f.write("\n\n" + "=" * 80 + "\n\n")

        if self.is_interactive:
            self.print_color(
                f"✓ Comments saved: {len(resolved_comments)} resolved, {len(unresolved_comments)} unresolved",
                Colors.GREEN,
            )

    async def fetch_pipeline_info(self):
        """Fetch latest pipeline information and job details."""
        if self.is_interactive:
            self.print_color("Fetching pipeline information...", Colors.BLUE)

        # Check if head_pipeline is already in MR data
        self.pipeline_data = self.mr_data.get("head_pipeline", {})

        if not self.pipeline_data:
            if self.is_interactive:
                self.print_color("No pipeline found for this MR", Colors.YELLOW)
            return

        pipeline_id = self.pipeline_data["id"]
        if self.is_interactive:
            self.print_color(f"Found pipeline {pipeline_id}, fetching jobs...", Colors.CYAN)

        # Get jobs for this pipeline
        project_id = self.mr_data.get("project_id")
        stdout, stderr, code = await self.run_glab("api", f"projects/{project_id}/pipelines/{pipeline_id}/jobs?per_page=100", "--paginate")

        if code != 0:
            self.print_color(f"Warning: Could not fetch jobs: {stderr}", Colors.YELLOW)
            return

        try:
            # Fix pagination format
            fixed_json = stdout.replace("][", ",")
            self.jobs_data = json.loads(fixed_json)
        except json.JSONDecodeError as e:
            self.print_color(f"Error parsing jobs data: {e}", Colors.RED)
            return

        # Write pipeline summary
        with open(self.pipeline_summary_file, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write("PIPELINE SUMMARY\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Pipeline ID: {self.pipeline_data.get('id')}\n")
            f.write(f"Status: {self.pipeline_data.get('status')}\n")
            f.write(f"Ref: {self.pipeline_data.get('ref')}\n")
            f.write(f"Created: {self.pipeline_data.get('created_at')}\n")
            f.write(f"Updated: {self.pipeline_data.get('updated_at')}\n")
            f.write(f"Web URL: {self.pipeline_data.get('web_url')}\n")
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"JOBS ({len(self.jobs_data)} total)\n")
            f.write("=" * 80 + "\n\n")

            for job in self.jobs_data:
                log_file = self.get_job_log_path(job)

                f.write(f"Job: {job.get('name')}\n")
                f.write(f"  ID: {job.get('id')}\n")
                f.write(f"  Status: {job.get('status')}\n")
                f.write(f"  Stage: {job.get('stage')}\n")
                f.write(f"  Duration: {job.get('duration')}s\n")
                f.write(f"  Created: {job.get('created_at')}\n")
                if job.get("started_at"):
                    f.write(f"  Started: {job.get('started_at')}\n")
                if job.get("finished_at"):
                    f.write(f"  Finished: {job.get('finished_at')}\n")
                f.write(f"  Web URL: {job.get('web_url')}\n")
                f.write(f"  Log File: {log_file}\n")
                f.write("\n")

        if self.is_interactive:
            self.print_color(f"✓ Pipeline summary saved to: {self.pipeline_summary_file}", Colors.GREEN)

    async def fetch_job_logs(self):
        """Fetch logs for all jobs."""
        if not self.jobs_data:
            return

        if self.is_interactive:
            self.print_color(f"Fetching logs for {len(self.jobs_data)} jobs...", Colors.BLUE)

        for idx, job in enumerate(self.jobs_data, 1):
            job_id = job.get("id")
            job_name = job.get("name", "unknown")
            job_status = job.get("status", "unknown")

            log_file = self.get_job_log_path(job)

            if self.is_interactive:
                print(f"  [{idx}/{len(self.jobs_data)}] Fetching log for: {job_name} ({job_status})...", end="\r")

            # Fetch job trace/log
            project_id = self.mr_data.get("project_id")
            stdout, stderr, code = await self.run_glab("api", f"projects/{project_id}/jobs/{job_id}/trace")

            if code == 0:
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write(f"Job: {job_name}\n")
                    f.write(f"ID: {job_id}\n")
                    f.write(f"Status: {job_status}\n")
                    f.write(f"Stage: {job.get('stage')}\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(stdout)
            else:
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write(f"Job: {job_name}\n")
                    f.write(f"ID: {job_id}\n")
                    f.write(f"Status: {job_status}\n")
                    f.write(f"Stage: {job.get('stage')}\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(f"ERROR: Could not fetch log\n{stderr}")

        if self.is_interactive:
            print(" " * 100, end="\r")  # Clear progress line
            self.print_color(f"✓ {len(self.jobs_data)} job logs saved to: {self.jobs_dir}", Colors.GREEN)

    async def run(self):
        """Main execution flow."""
        if self.is_interactive:
            self.print_color("=" * 80, Colors.BLUE)
            self.print_color("GitLab MR Full State Fetcher", Colors.BLUE)
            self.print_color("=" * 80, Colors.BLUE)
            print()

        # Fetch all data
        await self.fetch_mr_info()
        await self.fetch_comments()
        await self.fetch_pipeline_info()
        await self.fetch_job_logs()

        # Print summary
        if not self.is_interactive:
            # Non-interactive mode: only show results, no progress messages
            pass
        else:
            print()
            self.print_color("=" * 80, Colors.GREEN)
            self.print_color("FETCH COMPLETE", Colors.GREEN)
            self.print_color("=" * 80, Colors.GREEN)

        print()
        self.print_color("MR Information:", Colors.CYAN)
        if self.mr_data:
            print(f"  Title: {self.mr_data.get('title', 'N/A')}")
            print(f"  Author: {self.mr_data.get('author', {}).get('name', 'N/A')}")
            print(f"  State: {self.mr_data.get('state', 'N/A')}")
            print(f"  URL: {self.mr_data.get('web_url', 'N/A')}")

        print()
        self.print_color("Files Created:", Colors.CYAN)
        print(f"  MR Info:            {self.mr_info_file}")

        # Show comment files with counts
        if self.comments:
            resolved_count = len([c for c in self.comments if not c.get("resolvable", False) or c.get("resolved", False)])
            unresolved_count = len(self.comments) - resolved_count
            print(f"  Comments (resolved):   {self.comments_resolved_file} ({resolved_count} comments)")
            print(f"  Comments (unresolved): {self.comments_unresolved_file} ({unresolved_count} comments)")

        if self.pipeline_data:
            print(f"  Pipeline:           {self.pipeline_summary_file} (status: {self.pipeline_data.get('status')})")

        # Show failed jobs
        if self.jobs_data:
            failed_jobs = [job for job in self.jobs_data if job.get("status") == "failed"]
            if failed_jobs:
                print()
                self.print_color(f"Failed Jobs ({len(failed_jobs)}):", Colors.RED)
                for job in failed_jobs:
                    job_name = job.get("name", "unknown")
                    log_file = self.get_job_log_path(job)
                    print(f"  {job_name}: {log_file}")

        print()
        self.print_color(f"All files in: {self.output_dir}", Colors.YELLOW)


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="GitLab MR Full State Fetcher - Get complete MR info, comments, pipeline, and logs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This tool auto-detects the MR from your current Git branch.
It must be run from within a Git repository with an open merge request.

Output:
  Creates a timestamped directory in /tmp with:
  - mr-info.txt: Full MR details
  - comments-resolved.txt: Resolved threads and non-resolvable comments
  - comments-unresolved.txt: Active unresolved discussion threads
  - full-pipeline-summary.txt: Latest pipeline status and all jobs
  - job-logs/: Directory with individual log files for each job
        """,
    )

    parser.parse_args()  # No arguments needed, but keep parser for --help

    fetcher = MRFullStateFetcher()
    await fetcher.run()


def cli():
    """Entry point for the command line interface."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
