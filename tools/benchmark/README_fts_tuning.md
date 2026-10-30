# 全文索引调优：性能与语义验收

本分支基于 `2026-competition`，**不修改原分支**。本次提交属于 seekdb C++ 内核优化，不是仅修改 SQL 或压测脚本。

## 改动范围

- `src/storage/fts/ob_fts_stop_word.cpp/.h`
  - 当词元与停用词集合使用相同 collation 时，直接查询哈希集合，避免每词创建 `ObArenaAllocator` 和调用通用 `charset_convert`。
  - collation 不同则仍按原路径进行转换；保留已有的错误码和哈希比较规则。
  - 对 `utf8mb4_general_ci` 的 **ASCII 字母、数字和下划线**词元，采用单字节小写化；非 ASCII 或其他 collation 仍使用原有 `ObCharset::tolower`。
  - ASCII 小写化仍向传入 allocator 申请独立内存，避免将词典/倒排构建的哈希表键指向临时的输入缓冲区。

以上改动旨在减少 **索引构建 / TOKENIZE / 查询分词**共享热路径上的重复内存分配和字符集处理，**没有修改分词器词法规则、停用词列表、倒排数据格式或 BM25 评分算法**。

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

**局限**：这组语义冒烟测试不是穷举，也不能代替全量回归、真实查询集召回率测试及编译测试。正式提测前应确认内核编译通过、完整回归通过且优化前后召回率不下降。

## 4. 提测

在「成绩提测」页面填写：

- **代码仓库**：`https://github.com/km-hl/oceanbase-seekdb`
- **Branch**：`fulltext-index-tuning`
- **Commit id**：以该分支经验证的最新提交完整 SHA 为准

**测试状态**：该变更由源码审阅与增量修改产生；当前编辑环境未提供可编译的完整 OceanBase 工程环境或运行中的 seekdb，因此**未在此环境完成内核构建或真实性能跑分**，不应把此分支直接视为已测得加速比或官方通过。
