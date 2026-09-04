"""
horilla/backends.py
"""

import logging
import ssl

from django.core.mail.backends.smtp import EmailBackend as SMTPBackend

# import certifi
from base.email_logging import record_email_log

logger = logging.getLogger(__name__)


class CustomSSLContext(ssl.SSLContext):
    """
    CustomSSLContext
    """

    def __init__(self):
        super().__init__()
        # self.load_verify_locations(cafile=certifi.where())


class ZimbraBackend(SMTPBackend):
    """
    ZimbraBackend Class
    """

    def __init__(self, *args, **kwargs):
        # Initialize the parent SMTP backend
        super().__init__(*args, **kwargs)
        self.ssl_context = CustomSSLContext()

    def open(self):
        """Establish the SMTP connection using the custom SSL context and TLS."""
        if self.connection:
            return False  # Connection already open

        try:
            # Create the SMTP connection with the custom SSL context
            self.connection = self.connection_class(
                host=self.host, port=self.port, timeout=self.timeout
            )

            if self.use_tls:
                # Start TLS with custom SSL context
                self.connection.starttls(context=self.ssl_context)
                logger.info("Started TLS on %s:%s", self.host, self.port)

            # Authenticate after starting TLS
            self.connection.login(self.username, self.password)
            logger.info("Connected and authenticated on %s:%s", self.host, self.port)

        except Exception:
            logger.exception("Failed to connect or authenticate to Zimbra SMTP")
            self.close()
            return False
        return True

    def send_messages(self, email_messages):
        """Send messages and log the results to the database."""
        if not self.open():
            logger.error("Failed to open Zimbra SMTP connection")
            return 0

        response = super().send_messages(email_messages)
        for message in email_messages:
            record_email_log(
                subject=message.subject,
                from_email=message.from_email,
                to=message.to,
                body=message.body,
                status="sent" if response else "failed",
            )
        return response

    def close(self):
        """Ensure the SMTP connection is closed after use."""
        if self.connection:
            try:
                self.connection.quit()
            except Exception:
                logger.exception("Error closing Zimbra SMTP connection")
            finally:
                self.connection = None
