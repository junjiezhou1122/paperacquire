"""paperacquire: project-scoped paper acquisition and citation-graph tooling.

Forked and improved from AgentRG's ``paper_acquisition``. Key differences:
- storage is project-scoped (``PAPER_ACQUIRE_HOME`` / ``.paperacquire.toml``)
  instead of a single hard-wired global library;
- records carry first-class ``tags`` and ``collection`` fields with CLI
  commands (``tag``/``untag``/``collection``/``list --tag``) and a ``where``
  command that prints the active library so the storage location is never a
  guess.
"""

__version__ = "0.1.0"
