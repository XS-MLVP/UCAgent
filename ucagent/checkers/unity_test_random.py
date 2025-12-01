#coding=utf-8


from ucagent.checkers.base import Checker
from typing import Tuple


# TBD:
# 1. check file name 'test_random_*.py'
# 2. check test name 'test_random_<name>'
# 3. check args(env, ...)
# 4. check repeat function 'ucagent.repeat_count'
# 5. check assert
# 6. run random test cases


class RandomTestCasesChecker(Checker):

    def __init__(self, target_file, min_test_count=1, need_human_check=False):
        # TBD
        self.set_human_check_needed(need_human_check)

    def do_check(self, timeout=0, **kw) -> Tuple[bool, object]:
        # TBD
        return True, "Random test cases check pass"
