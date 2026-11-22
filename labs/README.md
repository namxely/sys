# Systems Hands-On Python Labs (`namxely/sys`)

Zero-dependency **Python 3.12+** implementations illustrating core computer systems concepts from [`docs/`](../docs/):

| Lab | Concept Covered | Run |
| :--- | :--- | :--- |
| [`cache_policies.py`](cache_policies.py) | O(1) Doubly-Linked-List `LRUCache`, O(1) Frequency-Bucket `LFUCache`, and hit-rate simulation under Zipfian vs scan workloads | `python labs/cache_policies.py` |
| [`resp_protocol.py`](resp_protocol.py) | Streaming Redis RESP2 wire protocol encoder & incremental decoder handling partial TCP chunk boundaries | `python labs/resp_protocol.py` |
| [`test_sys_labs.py`](test_sys_labs.py) | Automated unit tests (`unittest`) covering eviction edge cases, tie-breaking, RESP2 round trips & fragmented feeds | `python -m unittest discover -s labs -v` |
