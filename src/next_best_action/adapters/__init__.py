"""Adapter families — concrete implementations of the ports.

Three deployment profiles: ``gcp`` (managed Google Cloud, lazy imports), ``local`` (a
WORKING offline SDK-free deterministic stack, the dev/test/CI default), and ``onprem``
(fail-fast migration placeholders). A ``platform`` family wires the shared A1-A5 platform
services over HTTP where natural.
"""
