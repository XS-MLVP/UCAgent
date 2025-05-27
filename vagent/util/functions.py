#coding=utf-8


def fmt_time_deta(sec):
    """
    Format time duration in seconds to a human-readable string.
    :param sec: Time duration in seconds.
    :return: Formatted string representing the time duration.
    """
    sec = int(sec)
    s = sec % 60
    m = (sec // 60) % 60
    h = (sec // 3600) % 24
    deta_time = f"{h:02d}:{m:02d}:{s:02d}"
    return deta_time
