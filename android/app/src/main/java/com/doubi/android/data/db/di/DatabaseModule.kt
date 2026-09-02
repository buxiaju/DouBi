package com.doubi.android.data.db.di

import android.content.Context
import androidx.room.Room
import com.doubi.android.data.db.DouBiDatabase
import com.doubi.android.data.db.Migrations
import com.doubi.android.data.db.dao.IncrementCheckpointDao
import com.doubi.android.data.db.dao.MediaItemDao
import com.doubi.android.data.db.dao.PendingTaskDao
import com.doubi.android.data.db.dao.TaskDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * Room + Hilt 装配。
 *
 * 桌面版对照：`src/doubi/ui/app.py:create_app()` 里的 `Database` 装配。
 *
 * 设计决定：
 * - **绝对路径**：用 `Context.getDatabasePath()`，不复刻桌面版 `database_path`
 *   相对路径导致的卸载残留坑（详见桌面版 BUILD §6.5）
 * - **WAL**：Room 默认启用
 * - **欠账 #3 已还（v0.1.0）**：从 v0.1.0 起，**release 不再走 `fallbackToDestructiveMigration()`**，
 *   强制走显式 `addMigrations(*Migrations.ALL)`。schema 演进必须写 `Migration` 对象并加
 *   `MigrationTestHelper` 仪器测试覆盖（详见 [com.doubi.android.data.db.Migrations]）。
 * - **Debug 也走 `addMigrations`**：开发期写 migration 跟在 release 一样严格，不要双标。
 *   仍保留 `fallbackToDestructiveMigrationOnDowngrade()`：版本号降级（开发者手动改 version）
 *   时清空，避免 Room 报「schema 不识别」崩溃。
 */
@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): DouBiDatabase {
        return Room.databaseBuilder(
            context,
            DouBiDatabase::class.java,
            DouBiDatabase.DATABASE_NAME,
        )
            // 显式迁移链——空也注册，让 Room 知道「这是受控演进」
            .addMigrations(*Migrations.ALL)
            // 版本号降级时清空：仅在开发者手动改 schema version 时触发，正常用户升级不会
            // Room 2.7+ 起参数化 dropAllTables（true=清全部表，false=按 schema 对比清），
            // 我们要的是「不在受控链里就清干净」，传 true
            .fallbackToDestructiveMigrationOnDowngrade(dropAllTables = true)
            .build()
    }

    @Provides
    fun provideMediaItemDao(db: DouBiDatabase): MediaItemDao = db.mediaItemDao()

    @Provides
    fun provideTaskDao(db: DouBiDatabase): TaskDao = db.taskDao()

    @Provides
    fun providePendingTaskDao(db: DouBiDatabase): PendingTaskDao = db.pendingTaskDao()

    @Provides
    fun provideIncrementCheckpointDao(db: DouBiDatabase): IncrementCheckpointDao = db.incrementCheckpointDao()
}
