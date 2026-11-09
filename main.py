"""DREAMEROL FORK SYNC - Main entry point."""

import argparse
import getpass
import os
import sys

from dotenv import load_dotenv
from requests.exceptions import RequestException

from fork_sync.accounts import AccountManager
from fork_sync.github import GitHubClient
from fork_sync.synchronizer import ForkSynchronizer


def build_parser():
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Safely synchronize GitHub forks with their upstream repositories."
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--add-account",
        action="store_true",
        help="Add an account; its token is requested securely.",
    )
    actions.add_argument(
        "--list-accounts",
        action="store_true",
        help="List accounts saved in the system keyring.",
    )
    parser.add_argument(
        "--account",
        help="Use a saved account by GitHub username.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show selected forks without changing them or prompting for confirmation.",
    )
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        metavar="OWNER/REPO",
        help="Only select this fork (repeat to select multiple repositories).",
    )
    return parser


def filter_repositories(forks, requested_repositories):
    """Select forks by exact owner/repository name; reject unknown selections."""
    if not requested_repositories:
        return forks

    requested = {name.strip() for name in requested_repositories if name.strip()}
    available = {
        repo.get("full_name")
        for repo in forks
        if isinstance(repo, dict) and isinstance(repo.get("full_name"), str)
    }
    missing = sorted(requested - available)
    if missing:
        raise ValueError(
            "Not found among this account's forks: " + ", ".join(missing)
        )

    return [
        repo for repo in forks
        if isinstance(repo, dict) and repo.get("full_name") in requested
    ]


def confirm_synchronization(forks, input_fn=input, output=print):
    """Require an explicit typed confirmation before changing any fork."""
    if not forks:
        output("No fork repositories selected.")
        return False

    output("The following default branches may be changed:")
    for repo in forks:
        output(f" - {repo.get('full_name', 'unknown')}")
    try:
        response = input_fn("Type SYNC to continue, or anything else to cancel: ")
    except (EOFError, OSError):
        return False
    return response.strip() == "SYNC"


def _get_github_client(args, accounts):
    """Resolve the requested credential source and return a GitHub client."""
    if args.account:
        return accounts.get_client(args.account)

    token = os.getenv("GITHUB_TOKEN")
    if token:
        return GitHubClient(token)

    saved_accounts = accounts.list_accounts()
    if len(saved_accounts) == 1:
        return accounts.get_client(saved_accounts[0])
    if len(saved_accounts) > 1:
        raise ValueError(
            "More than one account is saved; select one with --account USERNAME. "
            "Saved accounts: " + ", ".join(saved_accounts)
        )
    raise ValueError(
        "No token configured. Set GITHUB_TOKEN or add an account with --add-account."
    )


def main(argv=None):
    """Run account management or the fork synchronization workflow."""
    args = build_parser().parse_args(argv)
    load_dotenv()
    accounts = AccountManager()

    if args.add_account:
        token = getpass.getpass("GitHub token (input hidden): ").strip()
        if not token:
            print("Error: token cannot be empty.", file=sys.stderr)
            return 1
        try:
            username = accounts.add_account(token)
            print(f"Account '{username}' added to the system keyring.")
            return 0
        except Exception as error:
            print(f"Could not add account: {error}", file=sys.stderr)
            return 1

    if args.list_accounts:
        try:
            saved_accounts = accounts.list_accounts()
        except Exception as error:
            print(f"Could not read saved accounts: {error}", file=sys.stderr)
            return 1
        if not saved_accounts:
            print("No saved accounts. Add one with: python main.py --add-account")
        else:
            print("Saved accounts:")
            for username in saved_accounts:
                print(f" - {username}")
        return 0

    github = None
    try:
        github = _get_github_client(args, accounts)
        user = github.get_authenticated_user()
        if not isinstance(user, dict) or not user.get("login"):
            raise ValueError("GitHub returned invalid authenticated-user data.")
        print(f"\nGitHub account: {user['login']}")

        synchronizer = ForkSynchronizer(github)
        forks = filter_repositories(synchronizer.get_forks(), args.repo)
        print(f"Selected {len(forks)} fork repository/repositories.\n")

        if args.dry_run:
            results = synchronizer.preview_all(forks=forks)
        else:
            if not confirm_synchronization(forks):
                print("Synchronization cancelled.")
                return 0
            results = synchronizer.sync_all(forks=forks)

        for result in results:
            print(f"{result['repository']}: {result['status']}")
            if result.get("message"):
                print(f"  {result['message']}")
        return 1 if any(result.get("status") in {"error", "conflict"} for result in results) else 0

    except (RequestException, ValueError, KeyError, TypeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Unexpected error: {error}", file=sys.stderr)
        return 1
    finally:
        if github is not None:
            github.session.close()


if __name__ == "__main__":
    raise SystemExit(main())
