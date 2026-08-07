"""Built-in disposable / temporary email domain denylist."""

from __future__ import annotations

# Curated blocklist of well-known temporary mailbox providers.
# Keep lowercase; matching is done on the normalized domain only.
DISPOSABLE_EMAIL_DOMAINS: frozenset[str] = frozenset(
    {
        "0-mail.com",
        "10minutemail.com",
        "10minutemail.net",
        "10minmail.com",
        "20minutemail.com",
        "33mail.com",
        "guerrillamail.com",
        "guerrillamail.de",
        "guerrillamail.net",
        "guerrillamail.org",
        "guerrillamailblock.com",
        "grr.la",
        "sharklasers.com",
        "spam4.me",
        "mailinator.com",
        "mailinator.net",
        "mailinator2.com",
        "mailinator.org",
        "tempmail.com",
        "temp-mail.org",
        "temp-mail.io",
        "tempmailo.com",
        "tempmailaddress.com",
        "tmpmail.org",
        "tmpmail.net",
        "trashmail.com",
        "trashmail.me",
        "trashmail.net",
        "trash-mail.com",
        "throwaway.email",
        "throwawaymail.com",
        "yopmail.com",
        "yopmail.fr",
        "yopmail.net",
        "cool.fr.nf",
        "jetable.org",
        "nwldx.com",
        "getnada.com",
        "nada.email",
        "emailondeck.com",
        "fakeinbox.com",
        "fakemailgenerator.com",
        "maildrop.cc",
        "discard.email",
        "discardmail.com",
        "dispostable.com",
        "mailnesia.com",
        "moakt.com",
        "mohmal.com",
        "mytemp.email",
        "tempail.com",
        "tempr.email",
        "tmpeml.com",
        "tmpbox.net",
        "burnermail.io",
        "mailcatch.com",
        "inboxalias.com",
        "spamgourmet.com",
        "mailnull.com",
        "spamobox.com",
        "tempinbox.com",
        "tempmail.dev",
        "tempmailgen.com",
        "minuteinbox.com",
        "emailtemporanea.com",
        "emailtemporanea.net",
        "temporary-mail.net",
        "temporarymail.com",
        "tmpnator.live",
        "mailpoof.com",
        "getairmail.com",
        "mailforspam.com",
        "spamfree24.org",
        "trashymail.com",
        "mt2009.com",
        "mt2014.com",
        "mt2015.com",
        "mailscrap.com",
        "crazymailing.com",
        "dropmail.me",
        "emkei.cz",
        "harakirimail.com",
        "incognitomail.org",
        "mailimate.com",
        "mintemail.com",
        "safetymail.info",
        "sogetthis.com",
        "spamherelots.com",
        "spamhereplease.com",
        "tempemail.com",
        "tempemail.net",
        "thankyou2010.com",
        "thisisnotmyrealemail.com",
        "tmails.net",
        "tmail.ws",
        "anonbox.net",
        "anonymbox.com",
        "boun.cr",
        "bugmenot.com",
        "deadaddress.com",
        "emailias.com",
        "filzmail.com",
        "getonemail.com",
        "inboxbear.com",
        "koszmail.pl",
        "mailhazard.com",
        "mailin8r.com",
        "mailinator.us",
        "mailmetrash.com",
        "mailsac.com",
        "mailtothis.com",
        "meltmail.com",
        "mierdamail.com",
        "objectmail.com",
        "proxymail.eu",
        "rcpt.at",
        "reallymymail.com",
        "recode.me",
        "reconmail.com",
        "safe-mail.net",
        "smellfear.com",
        "sneakemail.com",
        "sofimail.com",
        "sute.jp",
        "teleosaurs.xyz",
        "tempomail.fr",
        "temporarily.de",
        "tempymail.com",
        "trbvm.com",
        "wegwerfmail.de",
        "wegwerfmail.net",
        "wuzup.net",
        "wuzupmail.net",
        "zehnminutenmail.de",
        "zippymail.info",
        "1secmail.com",
        "1secmail.org",
        "1secmail.net",
        "linshiyouxiang.net",
    }
)


def extract_email_domain(email: str) -> str:
    """Return the lowercased domain part of an email address."""

    normalized = email.strip().lower()
    if "@" not in normalized:
        return ""
    return normalized.rsplit("@", 1)[-1].strip()


def is_disposable_email(email: str) -> bool:
    """Return True when the address uses a known temporary mailbox domain."""

    domain = extract_email_domain(email)
    if not domain:
        return False
    if domain in DISPOSABLE_EMAIL_DOMAINS:
        return True
    # Match multi-level hosts like ``foo.guerrillamail.com``.
    parts = domain.split(".")
    for index in range(1, len(parts) - 1):
        candidate = ".".join(parts[index:])
        if candidate in DISPOSABLE_EMAIL_DOMAINS:
            return True
    return False
