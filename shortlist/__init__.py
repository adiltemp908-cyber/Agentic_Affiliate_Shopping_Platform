"""Shortlist: local shopping research with explicit evidence and freshness."""
import os

# This application is local-only, even if a shell inherited tracing credentials.
os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'

