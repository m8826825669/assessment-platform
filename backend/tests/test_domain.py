import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from assessment_core import Attempt, Exam, Item, RuleViolation


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 1, 9, tzinfo=timezone.utc)
        self.item = Item("tenant-a", "item-v1", "Choose one", ("A", "B"), 1, approved=True)
        self.exam = Exam("tenant-a", "publication-1", (self.item,), 600)
        self.attempt = self.start()

    def start(self, **overrides):
        values = dict(
            tenant_id="tenant-a",
            candidate_id="candidate-1",
            exam=self.exam,
            opens_at=self.now,
            closes_at=self.now + timedelta(hours=1),
            now=self.now,
        )
        values.update(overrides)
        return Attempt(**values)

    def save(self, **overrides):
        values = dict(
            tenant_id="tenant-a",
            candidate_id="candidate-1",
            item_version_id="item-v1",
            choice=1,
            expected_revision=0,
            operation_key="save-1",
            now=self.now,
        )
        values.update(overrides)
        return self.attempt.save(**values)

    def submit(self, **overrides):
        values = dict(tenant_id="tenant-a", candidate_id="candidate-1", now=self.now)
        values.update(overrides)
        return self.attempt.submit(**values)

    def test_question_version_is_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            self.item.prompt = "Changed"

    def test_publication_copies_input_sequence(self):
        source = [self.item]
        exam = Exam("tenant-a", "p", source, 60)
        source.clear()
        self.assertEqual(len(exam.items), 1)

    def test_unapproved_content_is_denied(self):
        with self.assertRaisesRegex(RuleViolation, "unapproved_item"):
            Exam("tenant-a", "p", (replace(self.item, approved=False),), 60)

    def test_foreign_tenant_content_is_denied(self):
        with self.assertRaisesRegex(RuleViolation, "tenant_mismatch"):
            Exam("tenant-b", "p", (self.item,), 60)

    def test_duplicate_version_is_denied(self):
        with self.assertRaisesRegex(RuleViolation, "duplicate_item"):
            Exam("tenant-a", "p", (self.item, self.item), 60)

    def test_candidate_projection_has_no_key(self):
        self.assertEqual(set(self.item.candidate_view()), {"version_id", "prompt", "options"})

    def test_hash_changes_with_scoring_policy(self):
        changed = Exam("tenant-a", "publication-1", (replace(self.item, marks=Decimal("2")),), 600)
        self.assertNotEqual(changed.content_hash, self.exam.content_hash)

    def test_wrong_tenant_cannot_start(self):
        with self.assertRaisesRegex(RuleViolation, "tenant_mismatch"):
            self.start(tenant_id="tenant-b")

    def test_naive_time_is_denied(self):
        with self.assertRaisesRegex(RuleViolation, "timezone_required"):
            self.start(now=self.now.replace(tzinfo=None))

    def test_start_at_close_is_denied(self):
        with self.assertRaisesRegex(RuleViolation, "outside_start_window"):
            self.start(now=self.now + timedelta(hours=1))

    def test_extra_time_is_capped_at_sitting_close(self):
        attempt = self.start(extra_seconds=9000)
        self.assertEqual(attempt.deadline, self.now + timedelta(hours=1))

    def test_wrong_candidate_cannot_save(self):
        with self.assertRaisesRegex(RuleViolation, "access_denied"):
            self.save(candidate_id="candidate-2")

    def test_save_at_deadline_is_denied(self):
        with self.assertRaisesRegex(RuleViolation, "outside_answer_window"):
            self.save(now=self.attempt.deadline)

    def test_identical_retry_returns_original_revision(self):
        first = self.save()
        second = self.save(now=self.now + timedelta(seconds=1))
        self.assertEqual(first, second)
        self.assertEqual(second.revision, 1)

    def test_changed_idempotent_payload_is_denied(self):
        self.save()
        with self.assertRaisesRegex(RuleViolation, "idempotency_conflict"):
            self.save(choice=0)

    def test_stale_revision_cannot_overwrite(self):
        self.save()
        with self.assertRaisesRegex(RuleViolation, "revision_conflict"):
            self.save(choice=0, operation_key="save-2")
        self.assertEqual(self.attempt.responses["item-v1"].choice, 1)

    def test_next_revision_can_update_answer(self):
        self.save()
        response = self.save(choice=0, expected_revision=1, operation_key="save-2")
        self.assertEqual(response.revision, 2)

    def test_unknown_question_is_denied(self):
        with self.assertRaisesRegex(RuleViolation, "unknown_item"):
            self.save(item_version_id="foreign-item")

    def test_bool_is_not_an_option_index(self):
        with self.assertRaisesRegex(RuleViolation, "invalid_choice"):
            self.save(choice=True)

    def test_submission_retry_returns_same_snapshot(self):
        self.save()
        first = self.submit()
        second = self.submit(now=self.now + timedelta(hours=2))
        self.assertIs(first, second)
        self.assertEqual(len(first.responses), 1)

    def test_new_answer_after_submission_is_denied(self):
        self.save()
        self.submit()
        with self.assertRaisesRegex(RuleViolation, "already_submitted"):
            self.save(operation_key="save-2", expected_revision=1)

    def test_acknowledged_save_retry_after_submission_is_safe(self):
        first = self.save()
        self.submit()
        self.assertEqual(first, self.save(now=self.now + timedelta(hours=2)))

    def test_foreign_candidate_cannot_read_receipt_via_submit(self):
        self.submit()
        with self.assertRaisesRegex(RuleViolation, "access_denied"):
            self.submit(candidate_id="candidate-2")

    def test_response_mapping_cannot_be_edited_by_caller(self):
        with self.assertRaises(TypeError):
            self.attempt.responses["x"] = "bad"

    def test_submission_at_deadline_is_denied(self):
        with self.assertRaisesRegex(RuleViolation, "outside_submission_window"):
            self.submit(now=self.attempt.deadline)


if __name__ == "__main__":
    unittest.main()
