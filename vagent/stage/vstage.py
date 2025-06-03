#coding=utf-8


from vagent.util.functions import import_class_from_str
from vagent.util.log import info
import vagent.stage.checkers as checkers


class VerifyStage(object):

    def __init__(self, name, description, task, checker):
        """
        Initialize the VerifyStage with a name, description, task, checker, and checker arguments.
        Args:
            name (str): The name of the stage.
            description (str): A brief description of the stage.
            task (str): The task to be performed in this stage.
            checker (cfg): An Checker CFG to instance checks.
        """
        self.name = name
        self.description = description
        self.task = task
        self._checker = checker
        self.checker = [
            import_class_from_str(c.clss, checkers)(**c.args.as_dict()) for c in self._checker
        ]

    def __repr__(self):
        return f"VerifyStage(name={self.name}, description={self.description}, "+\
               f"checker={'.'.join([n.name for n in self._checker])}, checker_cls={'.'.join([n.clss for n in self._checker])})"



class StageManager(object):
    def __init__(self, cfg, agent):
        """
        Initialize the StageManager with an empty list of stages.
        """
        self.stages = [
            VerifyStage(
                name=f.name,
                description=f.desc,
                task=f.task,
                checker=f.checker
            ) for f in cfg.stage
        ]
        self.agent = agent
        info(f"Initialized StageManager with {len(self.stages)} stages.")
        info("Stages:")
        for stage in self.stages:
            info(f"  - {stage.name}: {stage.description}")

    def get_current_tips(self):
        """
        Get the current tips for the stages.
        """
        return ""
