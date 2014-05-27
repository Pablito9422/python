"""A custom backend for testing."""

from freedom.core.mail.backends.base import BaseEmailBackend


class EmailBackend(BaseEmailBackend):

    def __init__(self, *args, **kwargs):
        super(EmailBackend, self).__init__(*args, **kwargs)
        self.test_outbox = []

    def send_messages(self, email_messages):
        # Messages are stored in a instance variable for testing.
        self.test_outbox.extend(email_messages)
        return len(email_messages)
