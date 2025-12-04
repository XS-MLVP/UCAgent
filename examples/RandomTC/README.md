
## 随机测试用例

UCAgent生成的随机测试用例通过`ucagent.repeat_count`获取随机测试次数，默认情况下该函数返回的值很小，这样方便UCAgent进行调试。
需要人工进行长时间随机测试时，请通过环境变量`UC_TEST_RCOUNT`设置更大的值。如果用例很多，可通过[pytest-xdist](https://pypi.org/project/pytest-xdist/)进行并发测试。

例如：
```bash
cd unity_test/tests
UC_TEST_RCOUNT=1000000 pytest test_Adder_random*
# 或者
UC_TEST_RCOUNT=1000000 pytest -n auto test_Adder_random*
```
