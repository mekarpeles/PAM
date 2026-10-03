"""PAM: a general-purpose system for Projects, agents, teams, epics, and their relationships.

PAM is the durable identity-and-policy layer. cmux sits on top for tmux/claudio/session mechanics.
This package MUST NOT import cmux (see tests/test_no_cmux_import.py): `pip install pam` has to work
on a machine with no tmux.
"""

__version__ = "0.1.0"
