"""Independent decision engines for Case Hunter."""

from .contact_trust import ContactAssessment, assess_contact

__all__ = ["ContactAssessment", "assess_contact"]
