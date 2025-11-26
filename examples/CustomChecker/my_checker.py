#coding=utf-8

from ucagent.checkers.base import Checker

class MyChecker(Checker):

    def __init__(self, joke_file, word_count_min, word_count_max, **kwargs):
        self.joke_file = joke_file
        self.word_count_min = word_count_min
        self.word_count_max = word_count_max
        self.set_human_check_needed(kwargs.get("need_human_check", False))

    def do_check(self, timeout=0, **kwargs) -> tuple[bool, object]:
        """A simple checker that alternates between success and failure."""
        joke_path = self.get_path(self.joke_file)
        try:
            with open(joke_path, 'r', encoding='utf-8') as f:
                joke = f.read().strip()
            if "jimmy" not in joke.lower():
                return False, {"error": "No Jimmy find in your joke."}
            if len(joke) < self.word_count_min:
                return False, {"error": f"Joke is too short. Min word count is {self.word_count_min}."}
            if len(joke) > self.word_count_max:
                return False, {"error": f"Joke is too long. Max word count is {self.word_count_max}."}
            return True, {"joke": joke}
        except Exception as e:
            return False, {"error": str(e)}
