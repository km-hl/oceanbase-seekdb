# 全文索引调优：性能与语义验收

本分支基于 `2026-competition`，**不修改原分支**。本次提交属于 seekdb C++ 内核优化，不是仅修改 SQL 或压测脚本。

## 改动范围

- `src/storage/fts/ob_fts_stop_word.cpp/.h`
  - 当词元与停用词集合使用相同 collation 时，直接查询哈希集合，避免每词创建 `ObArenaAllocator` 和调用通用 `charset_convert`。
  - collation 不同则仍按原路径进行转换；保留已有的错误码和哈希比较规则。
  - 对 `utf8mb4_general_ci` 的 **ASCII 字母、数字和下划线**词元，采用单字节小写化；非 ASCII 或其他 collation 仍使用原有 `ObCharset::tolower`。
  - ASCII 小写化仍向传入 allocator 申请独立内存，避免将词典/倒排构建的哈希表键指向临时的输入缓冲区。

其他优化（第二轮迭代）：

- `src/sql/engine/expr/ob_expr_tokenize.cpp` / `src/storage/fts/ob_fts_parser_property.cpp`：无显式 parser properties 时跳过无意义的 JSON 重建，保留 IK smart 默认值。
- `src/sql/resolver/ddl/ob_fts_index_builder_util.cpp`：对两个分词密集型辅助索引构建阶段提高并行度，受 CPU 数和 16 worker 上限约束；保留 DOC_ID_ROWKEY 原并行度。
- `src/sql/optimizer/ob_log_plan.cpp`、`src/observer/composition/retrieval/ob_das_legacy_tr_merge_iter.cpp`、`src/storage/retrieval/ob_text_*iter.cpp`、`src/storage/retrieval/ob_sparse_taat_iter.cpp`：仅当自然语言 MATCH 被 `COUNT(*)` 一类标量聚合当作布尔筛选且其相关性分数没有被观察时跳过 BM25 的估计、聚合和计算。需要分数的 SELECT / ORDER BY / MAX(MATCH) / BOOLEAN MODE 路径仍计算相关性。其实现参考开源仓库的 <https://github.com/oceanbase/seekdb/pull/2246>；分词与构建的实现思路参考 <https://github.com/oceanbase/seekdb/pull/2247>。

以上改动旨在减少 **索引构建 / TOKENIZE / 查询分词**共享热路径上的重复分配、转换和冗余聚合，**没有有意修改分词器词法规则、停用词列表、倒排数据格式或用户可见的 BM25 评分语义**。正确性需要依赖下述回归验证，不能只依据查询命中数。

## 第三轮优化与评测记录（2026-10-31）

2026-10-30 23:49 的官方评测：提交 `01105d6af90a0d323e7bf578ea054b2318cbe0e0`，显示 **4.683 / 50**，执行成功。评测 JSON 记录 `fts_mean_improvement=0.04682935928890157`、`fts_raw_score=9.365871857780315`。四个查询命中量仍为 8001 / 11000 / 7332 / 20。`git_dirty=1` 仅表示构建运行环境工作树非 clean，不能据此断言分数为何变化。

第三轮只增加保守的词典/字符处理优化，保留已获分提交供回退：

- `src/storage/fts/dict/ob_ft_range_dict.cpp/.h`：IK 词典分区范围有序且互不重叠时使用二分查找，否则继续执行线性查找；使用 utf8mb4_bin 的逐字节比较快速路径。
- `src/storage/fts/ik/ob_ik_char_util.h`：常见 ASCII 英文字母、数字和连接符避免通用 Unicode 字符分类开销。
- `src/share/text_analysis/ob_token_stream.cpp`：UTF-8 ASCII 路径直接以一个字节推进，非 ASCII 保留多字节长度解析。

这些增量修改基于已公开的 OceanBase seekdb FTS 性能优化实现（<https://github.com/oceanbase/seekdb/pull/2246>），但**本分支本轮代码尚未获得官方基准结果**，不能声称已取得更高分。建议新提交与已知 4.683 分的提交交替重测，观察 `tokenize_ik_avg_ms`、`build_ik_all_sec`、`build_ik_content_sec`、`query_limit_avg_ms`；不要因为一次波动而认定加速有效。

## 1. 准备两套可运行的二进制

建议分别从原分支 `2026-competition` 和优化分支 `fulltext-index-tuning` 构建 seekdb，并在同一台机器上以**不同端口、不同数据目录**启动。保持 CPU、内存、租户配置、并行度、数据规模一致。可依次启动两套服务以降低资源竞争，但不要把两个版本指向同一数据目录。

请按仓库当前构建说明编译；只切换 Git 分支而不重新编译，不能证明内核优化生效。

## 2. 跑统一基准（两套服务分别执行）

下面示例假设旧版监听 2881，新版监听 2882；端口按实际修改。先对两个实例分别执行**完整**的装载、建索引、预热和查询流程，不要误用 `SKIP_LOAD=1` 跳过构建指标。

```bash
MYSQL='mysql -h127.0.0.1 -P2881 -uroot -N -s --default-character-set=utf8mb4' \
MYSQL_VERBOSE='mysql -h127.0.0.1 -P2881 -uroot --default-character-set=utf8mb4' \
LABEL=before ROWS=20000 BATCH=500 ROUNDS=3000 QUERY_ROUNDS=200 SAMPLES=3 WARMUP=30 \
OUTPUT=before.txt bash tools/benchmark/fts_large_bench.sh

MYSQL='mysql -h127.0.0.1 -P2882 -uroot -N -s --default-character-set=utf8mb4' \
MYSQL_VERBOSE='mysql -h127.0.0.1 -P2882 -uroot --default-character-set=utf8mb4' \
LABEL=after ROWS=20000 BATCH=500 ROUNDS=3000 QUERY_ROUNDS=200 SAMPLES=3 WARMUP=30 \
OUTPUT=after.txt bash tools/benchmark/fts_large_bench.sh
```

**注意**：每次测试会对目标实例执行 `DROP DATABASE IF EXISTS fts_large_bench`，请勿在含重要数据的实例上运行。现有 `fts_large_bench_gen.py` 生成确定性测试数据。

基准的主要指标是 `build_ik_all_sec`、`build_ik_content_sec`、`build_beng_en_sec`、`tokenize_ik_avg_ms`、`tokenize_beng_avg_ms` 和四项 `query_*_avg_ms`，这些数值均**越低越好**。查询 `*_hits` 应保持不变，异常下降可能意味着结果不正确。请至少分别执行三轮完整对比，记录中位数并考虑测量波动。

自带的评分脚本可根据仓库提供的历史 CI 基线作参考：

```bash
python3 tools/benchmark/fts_large_bench_score.py after.txt
```

该脚本输出是**仓库内的性能参考分**，不等同于 OceanBase 官方赛题最终得分。

## 3. 语义一致性校验

两套服务均按上述流程灌入**相同数据**并构建对应索引后：

```bash
python3 tools/benchmark/fts_semantics_compare.py \
  --before-mysql 'mysql -h127.0.0.1 -P2881 -uroot' \
  --after-mysql 'mysql -h127.0.0.1 -P2882 -uroot'
```

可先使用 `--tokenize-only` 只比较 Space、Beng、IK 的大小写、数字、重复词、Unicode 和中英混合分词，无需建索引。完整检查还比较表行数、四种 `MATCH ... AGAINST` 查询的结果计数，以及三组按相关性分数与 id 稳定排序的 Top-50 行和 BM25 分数。

另有标准 mysqltest 回归用例 `tools/deploy/mysql_test/test_suite/fts_index/t/match_filter_without_score.test` 与对应 `r/mysql/match_filter_without_score.result`，覆盖布尔 COUNT、显式比较、无命中、BM25 投影与排序、布尔模式和 LIMIT。须按 seekdb 项目内 mysqltest 执行机制运行。

**收到的上一轮官方评测数据**：`fts_mean_improvement = -0.0569268597`、`fts_raw_score = 0`，说明上一轮相比**评测基准**的综合收益为 -5.69%；`git_dirty = 1` 仅表示评测时工作树存在未提交改动，不等同于编译失败或语义错误。历史 `fts_large_bench_baseline.json` 是另一组 CI 测量数据，不可以只凭绝对耗时不同就判断官方分数。

**局限**：这组语义冒烟测试不是穷举，也不能代替全量回归、真实查询集召回率测试及编译测试。正式提测前应确认内核编译通过、完整回归通过且优化前后召回率不下降。

## 4. 提测

在「成绩提测」页面填写：

- **代码仓库**：`https://github.com/km-hl/oceanbase-seekdb`
- **Branch**：`fulltext-index-tuning`
- **Commit id**：以该分支经验证的最新提交完整 SHA 为准

**测试状态**：该变更由源码审阅与增量修改产生；当前编辑环境未提供可编译的完整 OceanBase 工程环境或运行中的 seekdb，因此**未在此环境完成内核构建或真实性能跑分**，不应把此分支直接视为已测得加速比或官方通过。
