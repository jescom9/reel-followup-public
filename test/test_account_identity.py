import unittest
from native.app import account_identity


class AccountIdentityTests(unittest.TestCase):
    def test_new_owner_can_connect_and_aliases_exclude_missing_values(self):
        self.assertEqual(account_identity({'user_id': '123', 'username': 'another_creator'}, {}),
                         ('123', ['123']))

    def test_existing_account_can_refresh_its_token_even_after_username_change(self):
        self.assertEqual(account_identity({'user_id': '123', 'id': '456', 'username': 'renamed'},
                                          {'account_id': '123', 'username': 'old_name'}),
                         ('123', ['123', '456']))

    def test_other_account_cannot_reuse_worker_delivery_history(self):
        with self.assertRaises(ValueError):
            account_identity({'user_id': '789', 'username': 'other'}, {'account_id': '123'})

    def test_incomplete_profile_cannot_connect(self):
        for profile in ({}, {'username': 'creator'}, {'user_id': '123'}):
            with self.assertRaises(ValueError):
                account_identity(profile, {})
