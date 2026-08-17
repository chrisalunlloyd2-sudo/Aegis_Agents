"""Swarm-seeded smoke test for Aegis_Igniter."""
import importlib, os, sys


def test_Aegis_Igniter_importable():
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    m = importlib.import_module('Aegis_Igniter')
    assert m is not None
