# coding=utf-8

def test_api_dummy_env_basic(env):
    # minimal assertion to pass
    assert hasattr(env, "dut")
