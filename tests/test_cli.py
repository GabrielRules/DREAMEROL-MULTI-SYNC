import main


def test_parser_accepts_dry_run_and_repeatable_repository_filter():
    args = main.build_parser().parse_args([
        "--dry-run",
        "--repo", "octocat/one",
        "--repo", "octocat/two",
        "--account", "octocat",
    ])

    assert args.dry_run is True
    assert args.repo == ["octocat/one", "octocat/two"]
    assert args.account == "octocat"


def test_filter_repositories_selects_exact_matches():
    forks = [
        {"full_name": "octocat/one"},
        {"full_name": "octocat/two"},
    ]

    assert main.filter_repositories(forks, ["octocat/two"]) == [forks[1]]


def test_filter_repositories_rejects_unknown_name():
    import pytest

    with pytest.raises(ValueError, match="Not found"):
        main.filter_repositories([{"full_name": "octocat/one"}], ["octocat/missing"])


def test_confirmation_requires_exact_sync_phrase():
    forks = [{"full_name": "octocat/one"}]

    assert main.confirm_synchronization(forks, input_fn=lambda _: "SYNC", output=lambda _: None)
    assert not main.confirm_synchronization(forks, input_fn=lambda _: "sync", output=lambda _: None)


def test_confirmation_cancels_when_input_is_unavailable():
    def eof(_prompt):
        raise EOFError

    assert not main.confirm_synchronization(
        [{"full_name": "octocat/one"}], input_fn=eof, output=lambda _: None
    )


def test_add_and_list_account_actions_are_mutually_exclusive():
    import pytest

    with pytest.raises(SystemExit):
        main.build_parser().parse_args(["--add-account", "--list-accounts"])


def test_dry_run_displays_preview_status_without_sync_or_confirmation(monkeypatch, capsys):
    fork = {
        "full_name": "octocat/demo-fork",
        "fork": True,
        "default_branch": "main",
        "parent": {
            "full_name": "upstream/demo-fork",
            "default_branch": "main",
        },
    }

    class FakeGitHubClient:
        def __init__(self):
            self.session = type("Session", (), {"close": lambda self: None})()

        def get_authenticated_user(self):
            return {"login": "octocat"}

    github = FakeGitHubClient()

    class FakeAccounts:
        def get_client(self, username):
            assert username == "octocat"
            return github

    class FakeSynchronizer:
        def __init__(self, client):
            assert client is github

        def get_forks(self):
            return [fork]

        def preview_all(self, forks=None):
            assert forks == [fork]
            return [{
                "repository": "octocat/demo-fork",
                "status": "behind",
                "message": "2 upstream commit(s) available.",
            }]

        def sync_all(self, forks=None, dry_run=False):
            raise AssertionError("dry-run must not enter the sync flow")

    def unexpected_confirmation(*args, **kwargs):
        raise AssertionError("dry-run must not ask for live-sync confirmation")

    monkeypatch.setattr(main, "AccountManager", FakeAccounts)
    monkeypatch.setattr(main, "ForkSynchronizer", FakeSynchronizer)
    monkeypatch.setattr(main, "confirm_synchronization", unexpected_confirmation)

    exit_code = main.main(["--dry-run", "--account", "octocat"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "octocat/demo-fork: behind" in captured.out
    assert "2 upstream commit(s) available." in captured.out
