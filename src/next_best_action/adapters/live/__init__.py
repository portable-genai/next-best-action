"""The ``live`` laptop profile's adapters: ``local`` with the shared local open-weight model.

Only the model-calling port lives here. Every other port binds the ``local`` adapter, so the
live lane differs from the offline one in exactly which model answers.
"""
