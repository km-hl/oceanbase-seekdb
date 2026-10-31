# AMD hipVS/HNSW 赛题操作入口

本目录提供独立的 GPU 环境检测和构建入口；实际 seekdb 内核修改仍位于 src/oblib/lib/vector、src/observer/vector_index 和 tools/hipvs_bridge。该目录是补充工具，不代表赛题评测器一定要求 amd/ 目录。

~~~bash
bash amd/run.sh check
bash amd/run.sh build
bash amd/run.sh smoke --help
bash amd/run.sh bench --help
~~~

check 缺少 AMD GPU、ROCm 或 hipVS 时会明确失败；build 在具备环境时编译真正的 GPU 路径。运行测试前请参阅 docs/gpu-vector-index-hipvs-cuvs/COMPETITION_BENCHMARK.md。

当前尚未在本分支独立完成 AMD Radeon/ROCm 实测，不能声称 GPU 加速已达标；评测接口的 failMsg=4 也未证明是代码问题。

来源：OceanBase seekdb 上游 PR #1314、#2228，Apache-2.0。
