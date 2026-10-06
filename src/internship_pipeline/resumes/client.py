"""Shared generation errors; new resumes use original LaTeX without a renderer client."""

from __future__ import annotations


class ResumeMatcherError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, ambiguous: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.ambiguous = ambiguous


class ResumeReconciliationRequired(ResumeMatcherError):
    """A saved generation checkpoint needs inspection before a safe retry."""

