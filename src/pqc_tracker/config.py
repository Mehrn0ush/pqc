"""Site-wide constants. Change these in one place."""

SITE_URL = "https://pqc.silastron.com"
SITE_NAME = "Silastron PQC Tracker"
REPO = "Mehrn0ush/pqc"
REPO_URL = f"https://github.com/{REPO}"
ISSUES_URL = f"{REPO_URL}/issues"
PULSE_URL = "https://pulse.silastron.com"
NEWSLETTER_URL = "https://silastron.com/newsletter/"
SILASTRON_URL = "https://silastron.com"
# TODO(owner): replace with the URL of the October 2026 PQC essay. Until then the link
# points at the silastron.com home page so the footer never carries a dead link.
ESSAY_URL = "https://silastron.com/"
ESSAY_LABEL = "Read the Silastron PQC essay"
CONTACT_LICENSES = "Code: Apache-2.0. Data: CC BY 4.0."

REVIEW_LABEL = "review-needed"
STALE_AFTER_HOURS = 72

ALGORITHMS = {
    "mlkem": ("ML-KEM", "FIPS 203"),
    "mldsa": ("ML-DSA", "FIPS 204"),
    "slhdsa": ("SLH-DSA", "FIPS 205"),
    "hybrid_kex": ("Hybrid key exchange", "PQ + classical"),
}

STATUS_LABELS = {
    "supported": "Supported",
    "experimental": "Experimental",
    "planned": "Planned",
    "not-supported": "Not supported",
    "unverified": "Unverified",
}

STANDARD_STATUS_LABELS = {
    "final": "Final",
    "draft": "Draft",
    "in-development": "In development",
    "wg-draft": "Working group draft",
    "iesg-evaluation": "IESG evaluation",
    "rfc-ed-queue": "RFC Editor queue",
    "rfc-published": "RFC published",
    "unverified": "Unverified",
}
