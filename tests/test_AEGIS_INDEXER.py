"""Swarm-seeded smoke test for AEGIS_INDEXER."""
import importlib, os, sys


def test_AEGIS_INDEXER_importable():
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    m = importlib.import_module('AEGIS_INDEXER')
    assert m is not None
