#coding: utf-8 -*-


from .base import AgentBackendBase

class UCAgentCmdLineBackend(AgentBackendBase):
    """
    Command-line based agent backend implementation.
    """

    def __init__(self, vagent, config, **kwargs):
        super().__init__(vagent, config, **kwargs)
