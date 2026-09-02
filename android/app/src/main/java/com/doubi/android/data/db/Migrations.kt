package com.doubi.android.data.db

import androidx.room.migration.Migration

/**
 * Room Migration 链。
 *
 * 欠账 #3 已还（v0.1.0）：v0.1 之前 `DouBiDatabase` 走 `fallbackToDestructiveMigration()`——
 * 任何 schema 变更都直接清表，用户的 pending_task 状态、历史下载记录全丢。从 v0.1.0 起
 * 强制走显式 Migration 链：升 `version` 必须新增一个 `Migration(n, n+1)` 入口加到
 * [ALL]，否则用户升级会崩。
 *
 * 写迁移的纪律：
 * 1. 加列 → `ALTER TABLE xxx ADD COLUMN ...`，**不删**旧列（避免破坏老 build 的回滚）
 * 2. 改列类型 → 不能 ALTER，只能 `ALTER TABLE RENAME TO` + `INSERT INTO new SELECT` + `DROP old`
 * 3. 加表 → `CREATE TABLE` + 加 `@Entity` + 加 DAO + 升 `version` + 写 `Migration(n, n+1)`
 * 4. **写迁移的同 commit 必加 [androidx.room.testing.MigrationTestHelper] 仪器测试**
 *
 * 桌面版对照：`src/doubi/core/storage/database.py` 用 SQLAlchemy `Base.metadata.create_all()`
 * + 自定义 `upgrade()` 脚本，Android 端用 Room Migration，**本质都是 schema 演进**。
 */
object Migrations {
    /**
     * 当前已注册的所有迁移。Room 会按 startVersion→endVersion 链式匹配。
     *
     * v0.1.0 提交时 schema 还是 version=1，没真实迁移条目——空数组。
     * v0.2.0 起加新表/列时，在这里加 `Migration(1, 2)` 并测试。
     */
    val ALL: Array<Migration> = emptyArray()
}
