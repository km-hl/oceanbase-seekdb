# 赛题一：第六轮实验 — IK 分词器处理器数组化

## 已评分版本（保留）

- `fulltext-index-v5`、Commit `1bcb1cbeb9f77477c935838b24a9ab818512f239`
- 2026-10-31 16:10 官方记录：**18.238 / 50**；综合提升指标 `fts_mean_improvement=0.18238427656413936`。
- 测试命中数：中文 8001、BENG 11000、中英混合 7332、LIMIT 20。
- 本实验分支 `fulltext-index-v6` 基于此提交创建，**没有修改 v5 的已评分版本**。

## 核心变更

`src/storage/fts/ob_ik_ft_parser.h/.cpp`：

- IK 分词器此前用 `ObList<ObIIKProcessor*, ObIAllocator>` 保存 4 个 processor，每遇到一个字符都要遍历一次链表。
- 现在改为具有 4 个 inline slots 的 `ObSEArray<ObIIKProcessor*, 4>`，按索引遍历。
- 初始化顺序和处理器的调用顺序 **完全相同**；尤其量词处理器仍排在 CJK 处理器之前。
- 仍使用原来的 processor 分配、初始化与释放，**没有引入跨文档缓存或线程本地状态**。
- 该小范围重构的思路也可见于 OceanBase seekdb 开源 FTS 优化讨论：
  <https://github.com/oceanbase/seekdb/pull/2246>。

对 `tools/benchmark/fts_semantics_compare.py` 增加了 5 个 IK 边界用例，覆盖 ASCII 连接符、小数、CJK 标点、Unicode、emoji 与重复片段。该脚本用于对比 v5 与 v6 的实际数据库输出，不是预录制预期值。

## 验收流程

1. 分别编译 v5 与 v6 的 seekdb Release 二进制，不要复用上一次的程序文件。
2. 在隔离实例上以相同测试语料运行 `tools/benchmark/fts_large_bench.sh`，配置：`ROWS=20000 BATCH=500 ROUNDS=3000 QUERY_ROUNDS=200 SAMPLES=3 WARMUP=30 SKIP_LOAD=0`。
3. 新旧实例均建立索引后运行：
   ```bash
   python3 tools/benchmark/fts_semantics_compare.py \
     --before-mysql 'mysql -h127.0.0.1 -P2881 -uroot' \
     --after-mysql 'mysql -h127.0.0.1 -P2882 -uroot'
   ```
4. 运行项目自带 mysqltest FTS 回归，特别是 `match_filter_without_score`。
5. 重复 A/B 对照至少两轮，关注 `build_ik_all_sec`、`build_ik_content_sec`、`tokenize_ik_avg_ms`、四项 query 时间以及命中数。评测波动可能比单项优化效果更大。

**状态：代码已提交，但当前环境没有完成完整 C++ 构建、mysqltest 或官方性能评测。** 若出现编译、语义或性能回退，保留上面已证实得 18.238 分的 v5 版本。

**安全说明：** 请仅在交流中使用不带 PAT 的仓库地址：`https://github.com/km-hl/oceanbase-seekdb`。已经公开的 PAT 应撤销。
