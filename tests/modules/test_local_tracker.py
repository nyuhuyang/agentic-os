"""Tests for runner.modules.linear.local_tracker — file-based task tracker."""

import json
import tempfile
from pathlib import Path

import pytest

from runner.modules.linear.local_tracker import LocalTracker


@pytest.fixture
def tracker():
    """Create a LocalTracker in a temp directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir)
        yield LocalTracker(state_dir)


class TestLocalTracker:
    """LocalTracker CRUD operations."""

    def test_create_issue(self, tracker):
        issue = tracker.create_issue("Test task", "Description")
        assert issue["title"] == "Test task"
        assert issue["description"] == "Description"
        assert issue["state"] == "Todo"
        assert issue["identifier"].startswith("LOC-")
        assert issue["id"].startswith("local-")

    def test_create_issue_increments_identifier(self, tracker):
        i1 = tracker.create_issue("First")
        i2 = tracker.create_issue("Second")
        assert i2["identifier"] == "LOC-2"

    def test_fetch_issues_empty(self, tracker):
        assert tracker.fetch_issues() == []

    def test_fetch_issues_all(self, tracker):
        tracker.create_issue("A")
        tracker.create_issue("B")
        assert len(tracker.fetch_issues()) == 2

    def test_fetch_issues_filtered(self, tracker):
        tracker.create_issue("A", state_name="Todo")
        tracker.create_issue("B", state_name="Done")
        issues = tracker.fetch_issues(["Todo"])
        assert len(issues) == 1
        assert issues[0]["title"] == "A"

    def test_fetch_issue_by_id(self, tracker):
        created = tracker.create_issue("Find me")
        fetched = tracker.fetch_issue(created["id"])
        assert fetched is not None
        assert fetched["title"] == "Find me"

    def test_fetch_issue_not_found(self, tracker):
        assert tracker.fetch_issue("nonexistent") is None

    def test_update_issue_state(self, tracker):
        issue = tracker.create_issue("Update me")
        assert tracker.update_issue_state(issue["id"], "In Progress") is True
        assert tracker.fetch_issue(issue["id"])["state"] == "In Progress"

    def test_update_issue_state_not_found(self, tracker):
        assert tracker.update_issue_state("nonexistent", "Done") is False

    def test_update_issue_multiple_fields(self, tracker):
        issue = tracker.create_issue("Original")
        updated = tracker.update_issue(
            issue["id"],
            title="Updated",
            description="New desc",
            state_name="In Review",
        )
        assert updated["title"] == "Updated"
        assert updated["description"] == "New desc"
        assert updated["state"] == "In Review"

    def test_delete_issue(self, tracker):
        issue = tracker.create_issue("Delete me")
        assert tracker.delete_issue(issue["id"]) is True
        assert tracker.fetch_issue(issue["id"]) is None

    def test_delete_issue_not_found(self, tracker):
        assert tracker.delete_issue("nonexistent") is False

    def test_push_state_maps_board_status(self, tracker):
        issue = tracker.create_issue("Board sync")
        tracker.push_state(issue["id"], "running")
        assert tracker.fetch_issue(issue["id"])["state"] == "In Progress"
        tracker.push_state(issue["id"], "review")
        assert tracker.fetch_issue(issue["id"])["state"] == "In Review"
        tracker.push_state(issue["id"], "success")
        assert tracker.fetch_issue(issue["id"])["state"] == "Done"

    def test_push_state_unknown_status(self, tracker):
        """Unknown board statuses should be silently ignored."""
        issue = tracker.create_issue("Unknown")
        tracker.push_state(issue["id"], "failed")
        assert tracker.fetch_issue(issue["id"])["state"] == "Todo"

    def test_post_comment(self, tracker):
        issue = tracker.create_issue("Comment test")
        assert tracker.post_comment(issue["id"], "Hello") is True
        updated = tracker.fetch_issue(issue["id"])
        assert len(updated.get("comment_log", [])) == 1
        assert updated["comment_log"][0]["body"] == "Hello"

    def test_post_comment_not_found(self, tracker):
        assert tracker.post_comment("nonexistent", "Hello") is False

    def test_get_in_progress_ids(self, tracker):
        i1 = tracker.create_issue("Running", state_name="In Progress")
        tracker.create_issue("Todo")
        in_prog = tracker.get_in_progress_ids()
        assert i1["id"] in in_prog
        assert len(in_prog) == 1

    def test_persists_to_disk(self, tracker):
        """Issues should survive a new LocalTracker instance."""
        issue = tracker.create_issue("Persist test")
        # Create a new tracker pointing at same directory
        tracker2 = LocalTracker(tracker._state_dir)
        fetched = tracker2.fetch_issue(issue["id"])
        assert fetched is not None
        assert fetched["title"] == "Persist test"

    def test_is_available(self, tracker):
        assert tracker.is_available is True
