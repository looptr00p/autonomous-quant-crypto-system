"""Adversarial validation suite for AQCS Phase-1B.

These tests deliberately attempt to corrupt, tamper with, or mis-configure
AQCS research artifacts and verify that the system fails loudly and
deterministically rather than silently accepting corrupt inputs.

The goal is NOT to prove correctness — it is to discover hidden fragility.
"""
