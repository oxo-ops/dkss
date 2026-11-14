# SMTP TLS contract acceptance

Depends on #384. Test-only: notification, MFA wrapper and email-change delivery
are exercised against an in-process IPv4 loopback SMTP fixture with real
smtplib/OpenSSL STARTTLS handshakes. Nine cases cover each path with a trusted
matching certificate, an untrusted certificate and a trusted certificate whose
name does not match. Negative cases assert verification codes 18/64, no AUTH,
MAIL, RCPT or DATA, and one STARTTLS attempt. Positive cases accept one synthetic
message after TLS and AUTH.

Functions are selected unchanged from repository AST into isolated namespaces.
This deliberately avoids importing the app, starting background jobs, accessing
DB/config/secrets or sending real mail. It is not full application integration.
The logging sink is replaced; prior safe-logging tests remain responsible for
log redaction. Other dependencies are synthetic, actual SMTP and SSL are not.

Ephemeral self-signed fixture keys are generated in a temporary directory and
removed after the suite. No real credentials or committed private keys. Runtime
environment is cleared by CI. Connection guard permits only the fixture's
127.0.0.1 port; FQDN and resolver are fixed locally, reverse DNS is rejected.
No external SMTP, provider, inbox, production TLS or MFA settings are exercised.

Run from the repository root:

    python -I -B tools/quality/smtp_tls_handshake/test_real_smtp_tls.py

Linux/Python/OpenSSL are required. Dedicated CI requires all nine cases, no skip,
and checks out the exact PR head. This does not merge or deploy #384 and does not
claim that real SMTP certificate configuration or email delivery is accepted.
